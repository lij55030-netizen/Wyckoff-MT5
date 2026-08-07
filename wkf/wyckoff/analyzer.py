"""威科夫综合分析：三层合一，输出可注入 Prompt 的诊断。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wkf.data.base import KlineFrame
from wkf.wyckoff.background import BackgroundResult, analyze_background
from wkf.wyckoff.orderflow_verify import OrderFlowVerifyResult, verify_orderflow
from wkf.wyckoff.value_area import (
    ValueAreaResult,
    build_profile_from_ohlcv,
    compute_value_area,
)


@dataclass
class WyckoffAnalysis:
    symbol: str
    timeframe: str
    price: float
    background: BackgroundResult
    value_area: ValueAreaResult | None
    orderflow: OrderFlowVerifyResult | None
    bias: str  # "long" | "short" | "neutral"
    trigger: str  # 入场触发条件（可验证）
    invalidation: str  # 失效条件
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "price": round(self.price, 2),
            "bias": self.bias,
            "background": {
                "regime": self.background.regime,
                "phase": self.background.phase,
                "hh_hl": self.background.hh_hl_count,
                "lh_ll": self.background.lh_ll_count,
                "reasoning": self.background.reasoning,
            },
            "value_area": (
                {
                    "vah": round(self.value_area.vah, 2),
                    "val": round(self.value_area.val, 2),
                    "vpoc": round(self.value_area.vpoc, 2),
                    "vwap": round(self.value_area.vwap, 2) if self.value_area.vwap else None,
                    "va_width": round(self.value_area.va_width, 2),
                    "hvn": [round(p, 2) for p in self.value_area.hvn[:5]],
                    "lvn": [round(p, 2) for p in self.value_area.lvn[:5]],
                    "price_position": self.value_area.price_position(self.price),
                }
                if self.value_area
                else None
            ),
            "orderflow": (
                {
                    "delta": round(self.orderflow.delta, 1),
                    "cumulative_delta": round(self.orderflow.cumulative_delta, 1),
                    "active_side": self.orderflow.active_side,
                    "reversal_stage": self.orderflow.reversal_stage,
                    "imbalance_count": len(self.orderflow.imbalances),
                    "stacked_imbalance_count": len(self.orderflow.stacked_imbalances),
                    "reasoning": self.orderflow.reasoning,
                }
                if self.orderflow
                else None
            ),
            "trigger": self.trigger,
            "invalidation": self.invalidation,
            "notes": self.notes,
        }

    def render_text(self) -> str:
        """渲染为面向用户的文本（条件化措辞）。"""
        bg = self.background
        lines = [
            f"【WKF 威科夫分析】{self.symbol} {self.timeframe}",
            f"现价: {self.price:.2f}",
            "",
            f"① 背景: {_REGIME_ZH.get(bg.regime, bg.regime)} / {_PHASE_ZH.get(bg.phase, bg.phase)}",
            *[f"   · {r}" for r in bg.reasoning],
        ]
        if self.value_area:
            va = self.value_area
            pos_zh = {
                "above_va": "价值区域上沿之外",
                "below_va": "价值区域下沿之外",
                "inside_va": "价值区域内",
            }.get(va.price_position(self.price), "")
            lines.append("")
            lines.append("② 价值区域:")
            lines.append(f"   · VA: [{va.val:.2f}, {va.vah:.2f}]  VPOC: {va.vpoc:.2f}")
            if va.vwap:
                lines.append(f"   · VWAP: {va.vwap:.2f}")
            if va.hvn:
                lines.append(f"   · HVN: {', '.join(f'{p:.2f}' for p in va.hvn[:4])}")
            if va.lvn:
                lines.append(f"   · LVN: {', '.join(f'{p:.2f}' for p in va.lvn[:4])}")
            lines.append(f"   · 现价位于{pos_zh}")

        if self.orderflow:
            of = self.orderflow
            lines.append("")
            lines.append("③ 订单流:")
            lines.append(f"   · Delta: {of.delta:+.0f}  累积Delta: {of.cumulative_delta:+.0f}")
            lines.append(f"   · 活跃方: {of.active_side}  反转阶段: {of.reversal_stage}")
            if of.imbalances:
                strongest = max(of.imbalances, key=lambda x: x["level"])
                lines.append(
                    f"   · 最强失衡: {strongest['side']} {strongest['level']}级 "
                    f"({strongest['ratio']}x @ {strongest['price']})"
                )
            if of.stacked_imbalances:
                lines.append(f"   · 堆叠失衡: {len(of.stacked_imbalances)} 组")

        lines.append("")
        lines.append(f"④ 倾向: {_BIAS_ZH.get(self.bias, self.bias)}")
        lines.append(f"⑤ 入场触发: {self.trigger}")
        lines.append(f"⑥ 失效条件: {self.invalidation}")
        return "\n".join(lines)


_REGIME_ZH = {
    "trend_up": "上升趋势（失衡）",
    "trend_down": "下降趋势（失衡）",
    "range": "区间（平衡）",
    "unknown": "背景不明（按区间假设）",
}
_PHASE_ZH = {
    "accumulation": "吸筹倾向",
    "distribution": "派发倾向",
    "markup": "上升阶段",
    "markdown": "下降阶段",
    "neutral": "中性",
}
_BIAS_ZH = {"long": "偏多", "short": "偏空", "neutral": "中性观望"}


def analyze(
    frame: KlineFrame,
    *,
    va_pct: float = 0.682,
    swing_window: int = 40,
    footprint_threshold: float = 2.0,
) -> WyckoffAnalysis:
    """三层威科夫综合分析。"""
    bars = frame.bars
    if not bars:
        raise ValueError("空 frame，无法分析")

    price = bars[0].close
    n = len(bars)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]

    # ── 第二层先行（提供价值区域给背景判定做参考）────────────────────────────
    tick_size = 0.25
    try:
        from wkf.data.mt5_source import get_tick_size

        tick_size = get_tick_size(frame.symbol)
    except Exception:
        pass

    va: ValueAreaResult | None = None
    of_result: OrderFlowVerifyResult | None = None

    # 优先用订单流里的 VolumeProfile（tick 精度高）
    of = frame.orderflow
    if of is not None and of.footprint:
        # 找最近的可用足迹（最新 bar 可能无 tick）
        fp0 = next((fp for fp in of.footprint if fp is not None), None)
        deltas = list(of.delta[:3]) if of.delta else []
        cum = of.cumulative_delta[0] if of.cumulative_delta else 0.0
        if fp0 is not None:
            prices = sorted(fp0.price_levels)
            vols = [sum(fp0.price_levels[p].values()) for p in prices]
            vwap_val = of.buy_vwap[0] if of.buy_vwap and not _isnan(of.buy_vwap[0]) else None
            va = compute_value_area(prices, vols, vwap=vwap_val, va_pct=va_pct)
            of_result = verify_orderflow(
                bars_delta=deltas,
                cumulative_delta=cum,
                footprint=fp0,
                tick_size=tick_size,
                thresholds=(footprint_threshold, footprint_threshold * 1.5, footprint_threshold * 2.0),
            )
        else:
            # 完全无足迹：仅按 delta 序列验证
            of_result = verify_orderflow(
                bars_delta=deltas,
                cumulative_delta=cum,
                footprint=None,
                tick_size=tick_size,
                thresholds=(footprint_threshold, footprint_threshold * 1.5, footprint_threshold * 2.0),
            )
    else:
        # OHLCV 近似
        prices, vols = build_profile_from_ohlcv(highs, lows, closes, volumes, tick_size)
        if prices:
            vwap_val = frame.indicators.vwap[0] if not _isnan(frame.indicators.vwap[0]) else None
            va = compute_value_area(prices, vols, vwap=vwap_val, va_pct=va_pct)

    # ── 第一层：背景判定 ─────────────────────────────────────────────────────
    bg = analyze_background(
        highs,
        lows,
        closes,
        vah=va.vah if va else None,
        val=va.val if va else None,
        swing_window=swing_window,
    )

    # ── 综合倾向 ─────────────────────────────────────────────────────────────
    bias, trigger, invalidation, notes = _compose(
        bg, va, of_result, price, tick_size
    )

    return WyckoffAnalysis(
        symbol=frame.symbol,
        timeframe=frame.timeframe,
        price=price,
        background=bg,
        value_area=va,
        orderflow=of_result,
        bias=bias,
        trigger=trigger,
        invalidation=invalidation,
        notes=notes,
    )


def _isnan(v: float) -> bool:
    import math

    return math.isnan(v)


def _compose(
    bg: BackgroundResult,
    va: ValueAreaResult | None,
    of_result: OrderFlowVerifyResult | None,
    price: float,
    tick_size: float,
) -> tuple[str, str, str, list[str]]:
    """根据三层结果给出倾向 + 触发条件 + 失效条件（条件化措辞）。"""
    notes: list[str] = []

    # 默认
    bias = "neutral"
    trigger = "等待：当前无明确入场信号"
    invalidation = "价格行为否定本判断时放弃计划"

    if va is None:
        notes.append("价值区域数据不足（无成交量分布）")
        return bias, trigger, invalidation, notes

    pos = va.price_position(price)
    above = pos == "above_va"
    below = pos == "below_va"

    # VPOC 控制判断（决策启发式 #1）
    vpoc_control = "buy" if price > va.vpoc else "sell"

    if bg.is_trending:
        # 趋势背景下：顺势 + 回调至价值区域边界测试入场
        if bg.regime == "trend_up":
            bias = "long"
            if above:
                trigger = (
                    f"如果价格回踩 VA 上沿 {va.vah:.2f} 附近出现买方失衡/强势K线，"
                    f"可考虑顺势做多；止损放在 {va.vah - tick_size * 2:.2f} 下方"
                )
            else:
                trigger = (
                    f"如果价格在 VA 内 {va.vpoc:.2f} 上方企稳且出现买方主动行为，"
                    f"可考虑顺势做多；跌破 {va.val:.2f} 则趋势结构受损"
                )
            invalidation = f"如果价格跌破 VA 下沿 {va.val:.2f} 且无快速收回，上升趋势假设失效"
        else:
            bias = "short"
            if below:
                trigger = (
                    f"如果价格回抽 VA 下沿 {va.val:.2f} 附近出现卖方失衡/强势K线，"
                    f"可考虑顺势做空；止损放在 {va.val + tick_size * 2:.2f} 上方"
                )
            else:
                trigger = (
                    f"如果价格在 VA 内 {va.vpoc:.2f} 下方受压且出现卖方主动行为，"
                    f"可考虑顺势做空；突破 {va.vah:.2f} 则趋势结构受损"
                )
            invalidation = f"如果价格突破 VA 上沿 {va.vah:.2f} 且无快速回落，下降趋势假设失效"
    else:
        # 区间：边界拒绝低买高卖（决策启发式 #2/#3）
        if above:
            # 上沿之外：可能假突破（UT）或趋势启动
            if of_result and of_result.active_side == "sell":
                bias = "short"
                trigger = (
                    f"价格在 {va.vah:.2f} 上方形成上冲回落（UT）且出现卖方失衡，"
                    f"可考虑区间做空；止损放在最近高点上方"
                )
                invalidation = f"如果价格放量站稳 {va.vah:.2f} 上方并持续（真突破），做空计划失效"
            else:
                bias = "neutral"
                trigger = (
                    f"价格处于 VA 上沿之外，等待确认：若回落到 {va.vah:.2f} 内 → 区间上沿做空；"
                    f"若放量突破并回测不跌回 → 趋势跟踪做多"
                )
                invalidation = "方向取决于随后价格行为，两者均需确认"
        elif below:
            if of_result and of_result.active_side == "buy":
                bias = "long"
                trigger = (
                    f"价格在 {va.val:.2f} 下方形成弹簧效应（Spring）且出现买方失衡，"
                    f"可考虑区间做多；止损放在最近低点下方"
                )
                invalidation = f"如果价格放量跌破 {va.val:.2f} 并持续（真突破），做多计划失效"
            else:
                bias = "neutral"
                trigger = (
                    f"价格处于 VA 下沿之外，等待确认：若回升到 {va.val:.2f} 内 → 区间下沿做多；"
                    f"若放量跌破并回测不收复 → 趋势跟踪做空"
                )
                invalidation = "方向取决于随后价格行为，两者均需确认"
        else:
            # 价值区域内：围绕中枢两端拒绝交易（决策启发式 #2）
            bias = "neutral"
            trigger = (
                f"价格在价值区域内 [{va.val:.2f}, {va.vah:.2f}]，默认观望；"
                f"若回踩 {va.val:.2f} 获支撑做多，或反弹至 {va.vah:.2f} 受压做空"
            )
            invalidation = (
                f"若价格放量突破 {va.vah:.2f} 或跌破 {va.val:.2f} 且回测不回收，"
                f"区间框架失效，转趋势跟踪"
            )

    # 订单流增强说明
    if of_result:
        if of_result.reversal_stage == "active":
            notes.append(
                "订单流已达「主动」阶段（衰竭→吸收→主动完整），反转信号增强"
            )
        elif of_result.reversal_stage != "none":
            notes.append(
                f"订单流处于反转「{of_result.reversal_stage}」阶段，尚需主动行为确认"
            )
        if of_result.stacked_imbalances:
            notes.append("检测到堆叠失衡，关键价位存在强买/卖压力")

    return bias, trigger, invalidation, notes

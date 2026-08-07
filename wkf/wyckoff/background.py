"""第一层：威科夫背景判定。

趋势（失衡）= HH+HL 或 LH+LL 排列，且价格持续位于价值区域外沿。
区间（平衡）= 高低点基本水平，价格在 VAH-VAL 内往返。
无法判定 → 标注"背景不明"，按区间假设处理。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BackgroundResult:
    regime: str  # "trend_up" | "trend_down" | "range" | "unknown"
    phase: str  # "accumulation" | "distribution" | "markup" | "markdown" | "neutral"
    hh_hl_count: int  # 高点抬高+低点抬高 组数
    lh_ll_count: int  # 高点降低+低点降低 组数
    swing_highs: list[float] = field(default_factory=list)
    swing_lows: list[float] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)

    @property
    def is_trending(self) -> bool:
        return self.regime in ("trend_up", "trend_down")

    @property
    def is_range(self) -> bool:
        return self.regime == "range"


def _find_swings(
    highs: list[float],
    lows: list[float],
    left: int = 2,
    right: int = 2,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """找摆动高低点（枢轴）。返回 (highs_idx_val, lows_idx_val)，时间顺序旧→新。"""
    n = len(highs)
    swing_h: list[tuple[int, float]] = []
    swing_l: list[tuple[int, float]] = []
    for i in range(left, n - right):
        if all(highs[i] >= highs[i - j] for j in range(1, left + 1)) and all(
            highs[i] >= highs[i + j] for j in range(1, right + 1)
        ):
            swing_h.append((i, highs[i]))
        if all(lows[i] <= lows[i - j] for j in range(1, left + 1)) and all(
            lows[i] <= lows[i + j] for j in range(1, right + 1)
        ):
            swing_l.append((i, lows[i]))
    return swing_h, swing_l


def analyze_background(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    vah: float | None = None,
    val: float | None = None,
    swing_window: int = 40,
) -> BackgroundResult:
    """判定背景（趋势/区间）与阶段（吸筹/派发/上升/下降/中性）。

    Parameters
    ----------
    highs/lows/closes:
        新→旧 顺序的序列。
    vah/val:
        价值区域上下界（来自第二层，可选；用于判断价格位置）。
    swing_window:
        取最近 N 根 bar 找摆动点。
    """
    n = len(closes)
    reasoning: list[str] = []
    if n < 12:
        return BackgroundResult("unknown", "neutral", 0, 0, [], [], ["K线数量不足，无法判定背景"])

    # 取窗口内数据（新→旧），内部反转成旧→新做枢轴
    seg_h = highs[:swing_window][::-1]
    seg_l = lows[:swing_window][::-1]
    seg_c = closes[:swing_window][::-1]

    sw_h, sw_l = _find_swings(seg_h, seg_l)
    highs_vals = [v for _, v in sw_h]
    lows_vals = [v for _, v in sw_l]

    # 将摆动点按时间顺序合并，跟踪 prev_high / prev_low 统计 HH/HL、LH/LL
    points: list[tuple[int, str, float]] = [
        *[(idx, "high", val) for idx, val in sw_h],
        *[(idx, "low", val) for idx, val in sw_l],
    ]
    points.sort(key=lambda x: x[0])

    hh_hl = 0
    lh_ll = 0
    prev_high: float | None = None
    prev_low: float | None = None
    for _, ptype, pval in points:
        if ptype == "high":
            if prev_high is not None:
                if pval > prev_high:
                    hh_hl += 1
                elif pval < prev_high:
                    lh_ll += 1
            prev_high = pval
        else:
            if prev_low is not None:
                if pval > prev_low:
                    hh_hl += 1
                elif pval < prev_low:
                    lh_ll += 1
            prev_low = pval

    # 区间宽度（相对 ATR 或绝对比例）
    hi = max(seg_h)
    lo = min(seg_l)
    span = hi - lo if hi > 0 else 0
    mean_price = sum(seg_c) / len(seg_c)
    span_pct = span / mean_price * 100 if mean_price else 0

    # 判定：趋势需至少 2 组同向摆动，且价格位置支持
    price = closes[0]
    above_va = vah is not None and price > vah
    below_va = val is not None and price < val

    if hh_hl >= 2 and hh_hl > lh_ll:
        regime = "trend_up"
        phase = "markup"
        reasoning.append(f"HH+HL 序列 {hh_hl} 组 > 反向 {lh_ll} 组 → 上升趋势（失衡）")
        if above_va:
            reasoning.append("价格位于价值区域上沿之外 → 趋势失衡确认")
        else:
            reasoning.append("价格仍在价值区域内 → 趋势但未远离平衡区")
    elif lh_ll >= 2 and lh_ll > hh_hl:
        regime = "trend_down"
        phase = "markdown"
        reasoning.append(f"LH+LL 序列 {lh_ll} 组 > 反向 {hh_hl} 组 → 下降趋势（失衡）")
        if below_va:
            reasoning.append("价格位于价值区域下沿之外 → 趋势失衡确认")
        else:
            reasoning.append("价格仍在价值区域内 → 趋势但未远离平衡区")
    else:
        # 区间：可能吸筹（低点托稳）或派发（高点受压）
        regime = "range"
        phase = "neutral"
        reasoning.append(f"HH+HL={hh_hl} vs LH+LL={lh_ll} 不构成明确趋势 → 区间（平衡）")
        if span_pct > 0:
            reasoning.append(f"区间宽度约 {span_pct:.2f}%（相对均价的幅度）")
        # 用价格在区间的位置粗判吸筹/派发倾向
        if span > 0:
            pos = (price - lo) / span
            if pos < 0.35:
                phase = "accumulation"
                reasoning.append("价格运行于区间下部 → 潜在吸筹（需求建仓区）")
            elif pos > 0.65:
                phase = "distribution"
                reasoning.append("价格运行于区间上部 → 潜在派发（供应出货区）")
            else:
                reasoning.append("价格运行于区间中部 → 阶段中性，等待边界测试")

    # 兜底：背景不明
    if hh_hl == 0 and lh_ll == 0:
        reasoning.append("未检测到完整摆动序列 → 按区间假设处理（背景不明）")
        if regime != "range":
            regime = "range"
            phase = "neutral"

    return BackgroundResult(
        regime=regime,
        phase=phase,
        hh_hl_count=hh_hl,
        lh_ll_count=lh_ll,
        swing_highs=highs_vals,
        swing_lows=lows_vals,
        reasoning=reasoning,
    )

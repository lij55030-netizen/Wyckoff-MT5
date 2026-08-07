"""第三层：订单流验证。

威科夫2.0：入场信号必须经历 衰竭 → 吸收 → 主动 三步骤。
足迹图失衡阈值：200% / 300% / 400%（2x / 3x / 4x）。

【风险提示】订单流由 MT5 Tick 数据近似换算生成，并非交易所原始盘口订单流，
仅用于威科夫结构定性研判，不建议作为高频短线交易依据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrderFlowVerifyResult:
    delta: float
    cumulative_delta: float
    imbalances: list[dict] = field(default_factory=list)
    stacked_imbalances: list[list[dict]] = field(default_factory=list)
    absorption: bool = False  # 高成交量+失衡与收盘不同价位 = 吸收（拒绝信号）
    exhaustion: bool = False  # 衰竭：放量滞涨/滞跌
    active_side: str = "none"  # "buy" | "sell" | "none"
    reversal_stage: str = "none"  # "none" | "exhaustion" | "absorption" | "active"
    reasoning: list[str] = field(default_factory=list)


def _imbalance_side_level(bid: float, ask: float) -> tuple[str, int] | None:
    """返回 (side, level)，level 1/2/3 = 2x/3x/4x；不满足返回 None。"""
    if bid <= 0 or ask <= 0:
        return None
    if bid / ask >= 4.0:
        return "buy", 3
    if ask / bid >= 4.0:
        return "sell", 3
    if bid / ask >= 3.0:
        return "buy", 2
    if ask / bid >= 3.0:
        return "sell", 2
    if bid / ask >= 2.0:
        return "buy", 1
    if ask / bid >= 2.0:
        return "sell", 1
    return None


def _detect_absorption(
    bars,
    bars_delta: list[float],
    *,
    vol_ratio: float = 1.3,
    narrow_factor: float = 0.8,
) -> tuple[bool, str]:
    """威科夫标准吸收结构三重联合判定。

    吸收 = 主力在高量下逆向承接，三者同时成立才标记：
      ① 放量：当前K线成交量 > 前两根K线最大量的 1.3 倍；
      ② 窄幅：当前K线高低价差相对收盘价明显压缩（< 前两根平均幅度的 0.8 倍）；
      ③ 背离：K线涨跌方向与 Delta 反向（阳线但卖压主导 / 阴线但买压主导）。

    bars: KlineBar 列表（新→旧，bars[0]=当前最新已收盘K线）。
    说明：最新已收盘K线之后无后续K线，"前后对比"取最近两根（前一根/更早一根）。
    """
    if not bars or len(bars) < 3 or not bars_delta:
        return False, ""
    cur, p1, p2 = bars[0], bars[1], bars[2]

    # ① 放量：当前量 > 前两根最大量的 1.3 倍
    vol_max = max(p1.volume, p2.volume)
    if cur.volume <= vol_max * vol_ratio:
        return False, ""

    # ② 窄幅：当前 (high-low)/close 相对前两根平均幅度压缩到 0.8 倍以下
    rng_cur = (cur.high - cur.low) / cur.close if cur.close > 0 else 0.0
    prev_ranges = [
        (b.high - b.low) / b.close if b.close > 0 else 0.0 for b in (p1, p2)
    ]
    avg_prev = sum(prev_ranges) / len(prev_ranges)
    if avg_prev <= 0 or rng_cur >= avg_prev * narrow_factor:
        return False, ""

    # ③ 背离：K线方向与 Delta 符号相反（主力逆向承接）
    bar_dir = 1 if cur.close > cur.open else (-1 if cur.close < cur.open else 0)
    delta = bars_delta[0] if bars_delta else 0.0
    if bar_dir == 0 or delta == 0 or (bar_dir > 0) == (delta > 0):
        return False, ""

    return True, "吸收结构：放量+窄幅震荡+Delta背离三重确认（非单纯放量K线）"


def _compose_reversal_stage(res: OrderFlowVerifyResult) -> None:
    """综合反转阶段：衰竭 → 吸收 → 主动 三步骤。"""
    if res.exhaustion and res.absorption and res.active_side != "none":
        res.reversal_stage = "active"
    elif res.exhaustion:
        res.reversal_stage = "exhaustion"
    elif res.absorption:
        res.reversal_stage = "absorption"
    else:
        res.reversal_stage = "none"


def verify_orderflow(
    *,
    bars_delta: list[float],
    cumulative_delta: float,
    footprint: Any,
    tick_size: float,
    thresholds: tuple[float, ...] = (2.0, 3.0, 4.0),
    bars=None,
) -> OrderFlowVerifyResult:
    """验证最近一根 bar 的订单流。

    Parameters
    ----------
    bars_delta:
        最近几根 bar 的 delta（新→旧）。
    cumulative_delta:
        累积 delta（整体）。
    footprint:
        FootprintBar 或 None。
    bars:
        KlineBar 列表（新→旧），用于吸收结构三重判定；None 时跳过吸收判定。
    """
    res = OrderFlowVerifyResult(
        delta=bars_delta[0] if bars_delta else 0.0,
        cumulative_delta=cumulative_delta,
    )

    # 吸收结构：放量 + 窄幅 + Delta背离 三重联合判定（独立于足迹数据）
    if bars and len(bars) >= 3 and bars_delta:
        res.absorption, note = _detect_absorption(bars, bars_delta)
        if res.absorption:
            res.reasoning.append(note)
        else:
            res.reasoning.append("吸收结构未确认（放量/窄幅/Delta背离未同时满足）")

    # 衰竭：上一根强 delta + 本根方向反转且幅度接近（独立于足迹数据）
    if bars_delta and len(bars_delta) >= 2:
        prev_d = bars_delta[1]
        cur_d = bars_delta[0]
        if abs(prev_d) > 0 and cur_d * prev_d < 0 and abs(cur_d) >= abs(prev_d) * 0.8:
            res.exhaustion = True
            res.reasoning.append(
                f"潜在衰竭：delta 由 {prev_d:+.0f} 反转至 {cur_d:+.0f}，幅度接近"
            )

    if footprint is None:
        res.reasoning.append("无足迹数据，仅按 delta 判断")
        if bars_delta and abs(bars_delta[0]) > 0:
            res.active_side = "buy" if bars_delta[0] > 0 else "sell"
        _compose_reversal_stage(res)
        return res

    # 失衡检测
    imbalances: list[dict] = []
    for price, vols in footprint.price_levels.items():
        bid = vols.get("bid", 0)
        ask = vols.get("ask", 0)
        r = _imbalance_side_level(bid, ask)
        if r:
            side, level = r
            ratio = bid / ask if side == "buy" else ask / bid
            imbalances.append(
                {"price": price, "side": side, "level": level, "ratio": round(ratio, 2)}
            )
    imbalances.sort(key=lambda x: x["price"])
    res.imbalances = imbalances

    # 堆叠失衡
    stacks: list[list[dict]] = []
    cur: list[dict] = []
    prev_price: float | None = None
    for item in imbalances:
        if prev_price is None or abs(item["price"] - prev_price) <= tick_size * 1.01:
            if cur and cur[-1]["side"] == item["side"]:
                cur.append(item)
            else:
                if len(cur) >= 2:
                    stacks.append(cur)
                cur = [item]
        else:
            if len(cur) >= 2:
                stacks.append(cur)
            cur = [item]
        prev_price = item["price"]
    if len(cur) >= 2:
        stacks.append(cur)
    res.stacked_imbalances = stacks

    if imbalances:
        strongest = max(imbalances, key=lambda x: x["level"])
        res.active_side = strongest["side"]
        res.reasoning.append(
            f"足迹图失衡：{strongest['side']}侧 {strongest['level']}级 "
            f"（{strongest['ratio']}x 于 {strongest['price']}）"
        )
    else:
        res.reasoning.append("足迹图无明显失衡（<2x）")

    # 综合反转阶段
    _compose_reversal_stage(res)
    return res

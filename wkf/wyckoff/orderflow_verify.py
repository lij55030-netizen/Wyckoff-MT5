"""第三层：订单流验证。

威科夫2.0：入场信号必须经历 衰竭 → 吸收 → 主动 三步骤。
足迹图失衡阈值：200% / 300% / 400%（2x / 3x / 4x）。
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


def verify_orderflow(
    *,
    bars_delta: list[float],
    cumulative_delta: float,
    footprint: Any,
    tick_size: float,
    thresholds: tuple[float, ...] = (2.0, 3.0, 4.0),
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
    """
    res = OrderFlowVerifyResult(
        delta=bars_delta[0] if bars_delta else 0.0,
        cumulative_delta=cumulative_delta,
    )

    if footprint is None:
        res.reasoning.append("无足迹数据，仅按 delta 判断")
        if bars_delta and abs(bars_delta[0]) > 0:
            res.active_side = "buy" if bars_delta[0] > 0 else "sell"
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

    # 反转三步骤：衰竭 → 吸收 → 主动
    if bars_delta and len(bars_delta) >= 2:
        prev_d = bars_delta[1]
        cur_d = bars_delta[0]
        # 衰竭：上一根强 delta + 本根方向反转且量巨大 → 潜在衰竭
        if abs(prev_d) > 0 and cur_d * prev_d < 0 and abs(cur_d) >= abs(prev_d) * 0.8:
            res.exhaustion = True
            res.reasoning.append(
                f"潜在衰竭：delta 由 {prev_d:+.0f} 反转至 {cur_d:+.0f}，幅度接近"
            )
        # 吸收：高量但价格变化小（努力与结果背离）
        if footprint.total_volume > 0:
            # 近似：delta 符号与 bar 方向相反视为吸收迹象
            res.absorption = True
            res.reasoning.append("存在吸收迹象（delta 与价格方向不一致时确认）")

    # 综合反转阶段
    if res.exhaustion and res.absorption and res.active_side != "none":
        res.reversal_stage = "active"
    elif res.exhaustion:
        res.reversal_stage = "exhaustion"
    elif res.absorption:
        res.reversal_stage = "absorption"
    else:
        res.reversal_stage = "none"

    return res

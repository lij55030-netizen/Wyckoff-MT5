"""Delta：买卖量差与累积Delta。"""
from __future__ import annotations


def compute_delta(
    buy_vols: list[float],
    sell_vols: list[float],
) -> float:
    """单根bar的 Delta = buy - sell。"""
    return sum(buy_vols) - sum(sell_vols)


def compute_cumulative_delta(bars_delta: list[float]) -> list[float]:
    """输入每根bar的delta（新→旧或旧→新一致），输出同序累积值。"""
    out: list[float] = []
    acc = 0.0
    for d in bars_delta:
        acc += d
        out.append(acc)
    return out

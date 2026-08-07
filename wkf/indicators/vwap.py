"""VWAP：标准（OHLCV）+ 订单流（买卖两侧）。"""
from __future__ import annotations

import math


def vwap_full(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> list[float]:
    """会话 VWAP：累计 (typical_price × volume) / 累计 volume。"""
    n = len(highs)
    out: list[float] = [math.nan] * n
    cum_pv = 0.0
    cum_v = 0.0
    for i in range(n):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        v = max(volumes[i], 0.0)
        cum_pv += tp * v
        cum_v += v
        if cum_v > 0:
            out[i] = cum_pv / cum_v
    return out


def vwap_delta(
    prices: list[float],
    volumes: list[float],
    sides: list[str],
) -> tuple[float, float, float, float, float] | None:
    """按买卖方向计算 (buy_vwap, sell_vwap, delta, buy_vol, sell_vol)。"""
    if not prices:
        return None
    b_pv = s_pv = 0.0
    b_v = s_v = 0.0
    for p, v, side in zip(prices, volumes, sides):
        v = max(v, 0.0)
        if side == "buy":
            b_pv += p * v
            b_v += v
        else:
            s_pv += p * v
            s_v += v
    buy_vwap = b_pv / b_v if b_v > 0 else float("nan")
    sell_vwap = s_pv / s_v if s_v > 0 else float("nan")
    return buy_vwap, sell_vwap, b_v - s_v, b_v, s_v

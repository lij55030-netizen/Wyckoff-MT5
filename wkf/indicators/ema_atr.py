"""EMA20 + ATR14（Wilder 平滑，与 PA-Agent 一致）。"""
from __future__ import annotations

import math


def ema_full(closes: list[float], period: int = 20) -> list[float]:
    """指数移动平均，前 period-1 个为 NaN，种子为简单均值。"""
    n = len(closes)
    out: list[float] = [math.nan] * n
    if n < period:
        return out
    k = 2.0 / (period + 1.0)
    seed = sum(closes[:period]) / period
    out[period - 1] = seed
    for i in range(period, n):
        out[i] = closes[i] * k + out[i - 1] * (1.0 - k)
    return out


def atr_full(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """平均真实波幅（Wilder），前 period 个为 NaN。"""
    n = len(highs)
    out: list[float] = [math.nan] * n
    if n <= period:
        return out

    trs: list[float] = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    seed = sum(trs[:period]) / period
    out[period] = seed
    for i in range(period, len(trs)):
        out[i + 1] = (out[i] * (period - 1) + trs[i]) / period
    return out

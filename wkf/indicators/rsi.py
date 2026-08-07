"""RSI (Wilder 平滑)，周期默认 14。"""
from __future__ import annotations

import math


def rsi_full(closes: list[float], period: int = 14) -> list[float]:
    """返回与输入等长的 RSI 序列；前 period+1 个为 NaN（预热）。"""
    n = len(closes)
    out: list[float] = [math.nan] * n
    if n <= period + 1:
        return out

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period, len(gains)):
        g = gains[i]
        l_ = losses[i]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l_) / period
        out[i + 1] = _rsi_from(avg_gain, avg_loss)

    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)

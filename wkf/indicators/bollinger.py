"""布林带：SMA(20) ± 2×总体标准差。"""
from __future__ import annotations

import math


def bollinger_full(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """返回 (upper, middle, lower)，前 period-1 个为 NaN。"""
    n = len(closes)
    upper: list[float] = [math.nan] * n
    middle: list[float] = [math.nan] * n
    lower: list[float] = [math.nan] * n
    if n < period:
        return upper, middle, lower

    running_sum = sum(closes[:period])
    running_sq = sum(c * c for c in closes[:period])

    def _compute(i: int) -> None:
        mean = running_sum / period
        var = max(running_sq / period - mean * mean, 0.0)
        sd = math.sqrt(var)
        upper[i] = mean + num_std * sd
        middle[i] = mean
        lower[i] = mean - num_std * sd

    _compute(period - 1)
    for i in range(period, n):
        out_val = closes[i]
        in_val = closes[i - period]
        running_sum += out_val - in_val
        running_sq += out_val * out_val - in_val * in_val
        _compute(i)

    return upper, middle, lower

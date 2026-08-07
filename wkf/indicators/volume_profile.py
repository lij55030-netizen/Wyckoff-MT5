"""Volume Profile / POC / 价值区域（威科夫2.0：VA=±1σ≈68.2%成交量）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VolumeProfileResult:
    poc_price: float
    vah: float
    val: float
    total_volume: float
    profile: dict[float, float] = field(default_factory=dict)  # price -> volume
    hvn: list[float] = field(default_factory=list)  # 高成交量节点
    lvn: list[float] = field(default_factory=list)  # 低成交量节点
    mean_price: float = 0.0
    std_price: float = 0.0


def compute_volume_profile(
    ticks: list[Any],
    tick_size: float = 0.25,
    va_pct: float = 0.682,
) -> VolumeProfileResult | None:
    """基于 tick 中间价的 Volume Profile。

    威科夫2.0 定义：价值区域 VA = ±1 个标准差，包含约 68.2% 成交量。
    实现：按价格量化到 tick_size，统计各价位成交量；
    从 POC（最大量价位）向两侧扩展，累计至 va_pct 成交量。
    """
    if not ticks:
        return None

    profile: dict[float, float] = {}
    for t in ticks:
        price = round(float(getattr(t, "mid_price", 0.0)) / tick_size) * tick_size
        vol = float(getattr(t, "volume", 1.0))
        if vol > 0:
            profile[price] = profile.get(price, 0.0) + vol

    if not profile:
        return None

    total = sum(profile.values())
    poc = max(profile, key=profile.get)
    sorted_prices = sorted(profile)

    # 从 POC 向两侧扩展
    included = {poc}
    acc = profile[poc]
    lo_idx = sorted_prices.index(poc)
    hi_idx = lo_idx
    while acc < total * va_pct:
        expand_lo = lo_idx > 0
        expand_hi = hi_idx < len(sorted_prices) - 1
        if not expand_lo and not expand_hi:
            break
        if expand_lo and expand_hi:
            lo_vol = profile[sorted_prices[lo_idx - 1]]
            hi_vol = profile[sorted_prices[hi_idx + 1]]
            if lo_vol >= hi_vol:
                lo_idx -= 1
                included.add(sorted_prices[lo_idx])
                acc += lo_vol
            else:
                hi_idx += 1
                included.add(sorted_prices[hi_idx])
                acc += hi_vol
        elif expand_lo:
            lo_idx -= 1
            included.add(sorted_prices[lo_idx])
            acc += profile[sorted_prices[lo_idx]]
        else:
            hi_idx += 1
            included.add(sorted_prices[hi_idx])
            acc += profile[sorted_prices[hi_idx]]

    vah = sorted_prices[hi_idx]
    val = sorted_prices[lo_idx]

    # HVN/LVN：相对平均价位量的 1.2x / 0.6x 阈值
    mean_vol = total / len(profile)
    hvn = [p for p, v in profile.items() if v >= mean_vol * 1.2]
    lvn = [p for p, v in profile.items() if v <= mean_vol * 0.6 and p != poc]

    # 按成交量加权的均价与标准差（用作 VWAP 近似与区域定位）
    wsum = sum(p * v for p, v in profile.items())
    mean_price = wsum / total
    var = sum(v * (p - mean_price) ** 2 for p, v in profile.items()) / total
    std_price = var ** 0.5

    return VolumeProfileResult(
        poc_price=poc,
        vah=vah,
        val=val,
        total_volume=total,
        profile=profile,
        hvn=hvn,
        lvn=lvn,
        mean_price=mean_price,
        std_price=std_price,
    )


def compute_volume_profile_ohlcv(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    tick_size: float = 0.25,
) -> VolumeProfileResult | None:
    """OHLCV 近似：无 tick 时用每根bar成交量按收盘价量化（精度较低）。"""
    if not closes:
        return None
    # 构造伪 tick（每根bar按收盘价+成交量计 1 个价位点）
    class _Pseudo:
        __slots__ = ("mid_price", "volume")

        def __init__(self, p: float, v: float) -> None:
            self.mid_price = p
            self.volume = v

    ticks = [_Pseudo(closes[i], volumes[i]) for i in range(len(closes))]
    return compute_volume_profile(ticks, tick_size=tick_size)

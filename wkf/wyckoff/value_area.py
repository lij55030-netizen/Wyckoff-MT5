"""第二层：价值区域定位。

客观价位：VAH / VAL / VPOC / VWAP / HVN / LVN。
威科夫2.0：价值区域 = ±1σ ≈ 68.2% 成交量。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValueAreaResult:
    vah: float
    val: float
    vpoc: float
    vwap: float | None
    hvn: list[float] = field(default_factory=list)
    lvn: list[float] = field(default_factory=list)
    mean_price: float = 0.0
    std_price: float = 0.0
    total_volume: float = 0.0
    va_width: float = 0.0

    @property
    def midpoint(self) -> float:
        return (self.vah + self.val) / 2.0

    def price_position(self, price: float) -> str:
        """价格相对价值区域的位置。"""
        if price > self.vah:
            return "above_va"
        if price < self.val:
            return "below_va"
        return "inside_va"


def compute_value_area(
    profile_prices: list[float],
    profile_volumes: list[float],
    *,
    vwap: float | None = None,
    va_pct: float = 0.682,
) -> ValueAreaResult | None:
    """从成交量分布（价格-成交量对）计算价值区域。

    与 indicators.volume_profile.compute_volume_profile 相比，本函数接收
    已聚合的 profile（price, volume 平行数组），输出更丰富的区域信息。
    """
    if not profile_prices or len(profile_prices) != len(profile_volumes):
        return None

    total = sum(profile_volumes)
    if total <= 0:
        return None

    vpoc = max(profile_prices, key=lambda p: profile_volumes[profile_prices.index(p)])
    # 从 VPOC 向两侧扩展
    sorted_idx = sorted(range(len(profile_prices)), key=lambda i: profile_prices[i])
    prices = [profile_prices[i] for i in sorted_idx]
    vols = [profile_volumes[i] for i in sorted_idx]

    poc_idx = prices.index(vpoc)
    included = {poc_idx}
    acc = vols[poc_idx]
    lo_idx = hi_idx = poc_idx
    target = total * va_pct
    while acc < target:
        can_lo = lo_idx > 0
        can_hi = hi_idx < len(prices) - 1
        if not can_lo and not can_hi:
            break
        if can_lo and can_hi:
            if vols[lo_idx - 1] >= vols[hi_idx + 1]:
                lo_idx -= 1
                included.add(lo_idx)
                acc += vols[lo_idx]
            else:
                hi_idx += 1
                included.add(hi_idx)
                acc += vols[hi_idx]
        elif can_lo:
            lo_idx -= 1
            included.add(lo_idx)
            acc += vols[lo_idx]
        else:
            hi_idx += 1
            included.add(hi_idx)
            acc += vols[hi_idx]

    vah = prices[hi_idx]
    val = prices[lo_idx]

    # HVN/LVN：相对均值量 1.2x / 0.6x
    mean_vol = total / len(prices)
    hvn = [p for p, v in zip(prices, vols) if v >= mean_vol * 1.2]
    lvn = [p for p, v in zip(prices, vols) if v <= mean_vol * 0.6 and p != vpoc]

    wsum = sum(p * v for p, v in zip(prices, vols))
    mean_price = wsum / total
    var = sum(v * (p - mean_price) ** 2 for p, v in zip(prices, vols)) / total
    std_price = var ** 0.5

    return ValueAreaResult(
        vah=vah,
        val=val,
        vpoc=vpoc,
        vwap=vwap,
        hvn=hvn,
        lvn=lvn,
        mean_price=mean_price,
        std_price=std_price,
        total_volume=total,
        va_width=vah - val,
    )


def build_profile_from_ohlcv(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    tick_size: float,
) -> tuple[list[float], list[float]]:
    """OHLCV 近似聚合：每根 bar 的成交量按价格区间均摊到 tick 价位。"""
    if not closes:
        return [], []
    price_to_vol: dict[float, float] = {}
    for h, l, v in zip(highs, lows, volumes):
        lo = round(l / tick_size) * tick_size
        hi = round(h / tick_size) * tick_size
        if hi < lo:
            hi = lo
        n_levels = max(int(round((hi - lo) / tick_size)) + 1, 1)
        per = v / n_levels
        for k in range(n_levels):
            p = lo + k * tick_size
            price_to_vol[p] = price_to_vol.get(p, 0.0) + per
    prices = sorted(price_to_vol)
    vols = [price_to_vol[p] for p in prices]
    return prices, vols

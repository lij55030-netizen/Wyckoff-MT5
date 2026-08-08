"""MT5 tick 桥接：CFD 报价 → 中间价 → Tick Rule 方向分类。

MT5 CFD tick 仅有 bid/ask 报价，无 BUY/SELL 标记、无真实成交量。
方案：mid_price = (bid+ask)/2，方向按中间价变动分类（Tick Rule），
成交量以 tick 计数代替（每 tick = 1.0 单位）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# 品种映射：WKF 符号 -> MT5 CFD 品种
MT5_TICK_MAP: dict[str, str] = {
    "NQ1!": "USTECHc",
    "ES1!": "US500c",
    "GC1!": "XAUUSD",
}

DEFAULT_TICK_SIZE: dict[str, float] = {
    "NQ1!": 0.25,
    "ES1!": 0.25,
    "GC1!": 0.1,
}


@dataclass(frozen=True)
class TickData:
    time: int
    mid_price: float
    bid: float
    ask: float
    spread: float
    side: str  # "buy" / "sell"
    volume: float  # 1.0 每 tick（计数代理）


def classify_ticks_by_tick_rule(ticks) -> list[TickData]:
    """Tick Rule：中间价上升=买，下降=卖，持平沿用上一方向。

    ``ticks`` 为 MT5 copy_ticks_range 返回的 numpy 结构化数组。
    """
    out: list[TickData] = []
    prev_mid: float | None = None
    prev_side = "buy"
    for t in ticks:
        bid = float(t["bid"]) if t["bid"] is not None else 0.0
        ask = float(t["ask"]) if t["ask"] is not None else 0.0
        if bid <= 0 or ask <= 0:
            continue
        mid = (bid + ask) / 2.0
        if prev_mid is None:
            side = "buy"
        elif mid > prev_mid:
            side = "buy"
        elif mid < prev_mid:
            side = "sell"
        else:
            side = prev_side
        prev_mid = mid
        prev_side = side
        time_msc = int(t["time_msc"]) if "time_msc" in t.dtype.names else int(t["time"]) * 1000
        out.append(
            TickData(
                time=time_msc,
                mid_price=mid,
                bid=bid,
                ask=ask,
                spread=ask - bid,
                side=side,
                volume=1.0,
            )
        )
    return out


def fetch_ticks_for_range(
    symbol: str,
    dt_from: datetime,
    dt_to: datetime,
) -> list[TickData] | None:
    """从 MT5 拉取 CFD tick 并分类。mt5 需已初始化。"""
    import MetaTrader5 as mt5

    # 【改动点】V3.0：支持 MT5 全部品种——映射表覆盖不到的品种直接用原名拉取。
    mt5_sym = MT5_TICK_MAP.get(symbol, symbol)

    ticks_raw = mt5.copy_ticks_range(mt5_sym, dt_from, dt_to, mt5.COPY_TICKS_ALL)
    if ticks_raw is None or len(ticks_raw) == 0:
        return None

    return classify_ticks_by_tick_rule(ticks_raw)


def get_tick_size(symbol: str) -> float:
    return DEFAULT_TICK_SIZE.get(symbol, 0.25)

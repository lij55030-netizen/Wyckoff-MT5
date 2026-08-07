"""WKF 核心数据结构：K线、指标束、订单流束、快照帧。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KlineBar:
    """单根K线（seq=1 为最新已收盘）。"""

    seq: int
    ts_open: int  # epoch ms
    open: float
    high: float
    low:    float
    close: float
    volume: float
    closed: bool = True


@dataclass(frozen=True)
class IndicatorBundle:
    """技术指标束（与 bars 等长，最旧在前）。"""

    ema20: tuple[float, ...] = ()
    atr14: tuple[float, ...] = ()
    rsi14: tuple[float, ...] = ()
    bb_upper: tuple[float, ...] = ()
    bb_middle: tuple[float, ...] = ()
    bb_lower: tuple[float, ...] = ()
    vwap: tuple[float, ...] = ()


@dataclass(frozen=True)
class OrderFlowBundle:
    """订单流数据束（与 bars 等长，最旧在前；None=该bar无tick数据）。"""

    delta: tuple[float, ...] = ()
    cumulative_delta: tuple[float, ...] = ()
    poc_price: tuple[float, ...] = ()
    vah: tuple[float, ...] = ()
    val: tuple[float, ...] = ()
    buy_vwap: tuple[float, ...] = ()
    sell_vwap: tuple[float, ...] = ()
    vwap_delta: tuple[float, ...] = ()
    footprint: tuple[Any, ...] = ()


@dataclass(frozen=True)
class KlineFrame:
    """一次分析快照：bars（新→旧）+ 指标 + 可选订单流。"""

    symbol: str
    timeframe: str
    bars: tuple[KlineBar, ...]
    indicators: IndicatorBundle
    snapshot_ts_local_ms: int = 0
    orderflow: OrderFlowBundle | None = None


def normalize_kline_bar(bar: KlineBar) -> KlineBar:
    """归一化：确保 high >= max(open,close) >= min(open,close) >= low。"""
    o, h, l, c = bar.open, bar.high, bar.low, bar.close
    hi = max(h, o, c)
    lo = min(l, o, c)
    if hi == bar.high and lo == bar.low:
        return bar
    return KlineBar(
        seq=bar.seq, ts_open=bar.ts_open,
        open=o, high=hi, low=lo, close=c,
        volume=bar.volume, closed=bar.closed,
    )

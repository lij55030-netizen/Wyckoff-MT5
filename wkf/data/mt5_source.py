"""MT5 数据源：K线拉取 + 快照构建 + 订单流增强。"""
from __future__ import annotations

import datetime
import math
import os
import bisect
import time
from typing import Any

from wkf.data.base import (
    IndicatorBundle,
    KlineBar,
    KlineFrame,
    OrderFlowBundle,
    normalize_kline_bar,
)
from wkf.indicators.bollinger import bollinger_full
from wkf.indicators.delta import compute_cumulative_delta
from wkf.indicators.ema_atr import atr_full, ema_full
from wkf.indicators.footprint import build_footprint, footprint_to_dict
from wkf.indicators.rsi import rsi_full
from wkf.indicators.volume_profile import compute_volume_profile
from wkf.indicators.vwap import vwap_delta, vwap_full

# MT5 周期映射
TF_MAP = {
    "1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440,
}

# 品种 -> MT5 品种（与 tick bridge 一致）
MT5_SYMBOL_MAP: dict[str, str] = {
    "NQ1!": "USTECHc",
    "ES1!": "US500c",
    "GC1!": "XAUUSD",
}

TICK_SIZE_MAP: dict[str, float] = {
    "NQ1!": 0.25,
    "ES1!": 0.25,
    "GC1!": 0.1,
}

# 旧别名 → MT5 真实品种（兼容历史 settings 记忆）
ALIAS_TO_MT5: dict[str, str] = {
    "GC1!": "XAUUSD",
    "NQ1!": "USTECHc",
    "ES1!": "US500c",
}

# 【改动点】V3.0：品种精简——只保留 黄金/纳指/标普500/白银/比特币。
PREFERRED_SYMBOLS: list[str] = [
    "XAUUSD",    # 黄金
    "USTECHc",   # 纳指
    "US500c",    # 标普500
    "XAGUSD",    # 白银
    "BTCUSDT",   # 比特币
]

# MT5 终端常见安装路径（默认 IPC 发现失败时显式重试，兼容非标准启动方式）
MT5_TERMINAL_PATHS = [
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
    r"D:\Program Files\MetaTrader 5\terminal64.exe",
    r"E:\Program Files\MetaTrader 5\terminal64.exe",
]


def ensure_mt5_initialized(mt5_module) -> bool:
    """初始化 MT5 连接：默认 IPC 失败时按常见安装路径显式重试。

    【改动点】V1.3.2：实测本机 mt5.initialize() 返回 IPC initialize failed，
    显式指定 terminal64.exe 路径后连接成功；统一封装后所有调用点共享该修复。
    """
    if mt5_module.initialize():
        return True
    for path in MT5_TERMINAL_PATHS:
        if os.path.exists(path) and mt5_module.initialize(path):
            return True
    return False


def mt5_timeframe(timeframe: str) -> int:
    """返回 MT5 TIMEFRAME 常量。

    【改动点】周期映射表扩展：新增 3m / 2h(120分) / 1w(周线)，日线 1d 复用。
    【涉及文件】wkf/data/mt5_source.py（对应假设文件 data_fetcher.py 的取数层）
    【验证方式】cli.py XAU 3m / XAU 2h / XAU 1d / XAU 1w 均可拉取对应级别K线
    """
    import MetaTrader5 as mt5

    table = {
        "1m": mt5.TIMEFRAME_M1,
        "3m": mt5.TIMEFRAME_M3,
        "5m": mt5.TIMEFRAME_M5,
        "10m": mt5.TIMEFRAME_M10,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "2h": mt5.TIMEFRAME_H2,
        "4h": mt5.TIMEFRAME_H4,
        "1d": mt5.TIMEFRAME_D1,
        "1w": mt5.TIMEFRAME_W1,
    }
    return table.get(timeframe, mt5.TIMEFRAME_M15)


def resolve_mt5_symbol(symbol: str) -> str:
    """NQ1! -> USTECHc 等；未知原样返回（尝试直接拉取）。"""
    return MT5_SYMBOL_MAP.get(symbol, ALIAS_TO_MT5.get(symbol, symbol))


_tick_size_cache: dict[str, tuple[float, float]] = {}
TICK_SIZE_CACHE_TTL_S = 300


def get_tick_size(symbol: str) -> float:
    """返回品种价格最小变动单位：优先本地映射，其次动态查询 MT5，最后回退 0.25。

    【改动点】V3.0：支持 MT5 全部品种——硬编码映射覆盖不到的品种
    从终端 symbol_info().trade_tick_size 实时查询（带 5 分钟内存缓存，避免反复连接）。
    """
    if symbol in TICK_SIZE_MAP:
        return TICK_SIZE_MAP[symbol]
    hit = _tick_size_cache.get(symbol)
    if hit and time.monotonic() - hit[1] < TICK_SIZE_CACHE_TTL_S:
        return hit[0]
    try:
        import MetaTrader5 as mt5

        if ensure_mt5_initialized(mt5):
            try:
                info = mt5.symbol_info(symbol)
                ts = float(getattr(info, "trade_tick_size", 0) or 0)
                if ts > 0:
                    _tick_size_cache[symbol] = (ts, time.monotonic())
                    return ts
            finally:
                mt5.shutdown()
    except Exception:
        pass
    _tick_size_cache[symbol] = (0.25, time.monotonic())
    return 0.25


def get_mt5_symbols() -> list[str]:
    """获取精简品种列表（黄金/纳指/标普500/白银/比特币）。

    【改动点】V3.0：仅保留用户指定的 5 个品种（按顺序），
    从终端 symbols_get() 校验存在性后返回，失败回退固定 5 品种。
    """
    try:
        import MetaTrader5 as mt5

        if ensure_mt5_initialized(mt5):
            try:
                syms = mt5.symbols_get()
                available = {s.name for s in syms} if syms else set()
                if available:
                    picked = [s for s in PREFERRED_SYMBOLS if s in available]
                    return picked or list(PREFERRED_SYMBOLS)
            finally:
                mt5.shutdown()
    except Exception:
        pass
    return list(PREFERRED_SYMBOLS)


def fetch_mt5_bars(
    symbol: str,
    timeframe: str = "15m",
    n_bars: int = 100,
    close_confirm: bool = True,
) -> list[KlineBar]:
    """从 MT5 拉取 K 线，返回新→旧顺序的 KlineBar 列表。

    注意：必须使用 copy_rates_from_pos 从「最新位置」取数。
    原实现 copy_rates_from(now(), n_bars+20) 的 date_from 参数用本地时间，
    与 GTC 服务器时区(约 GMT+11)错位 3 小时，导致返回的数据滞后约 3 小时
    （最新K线停在本地时间对应的服务器时段，错过真实最新行情）。
    copy_rates_from_pos 从最新 bar 开始往前取，无时区依赖，始终拿到实时数据。

    close_confirm（收线确认）：True 时剔除当前未收盘的 K 线（开盘时间+周期 > 服务器时间），
    保证分析与图表只使用已收盘定型的数据；False 时保留最新一根（含未收盘）。
    """
    import MetaTrader5 as mt5

    if not ensure_mt5_initialized(mt5):
        raise RuntimeError(f"MT5 初始化失败: {mt5.last_error()}")

    mt5_sym = resolve_mt5_symbol(symbol)
    tf = mt5_timeframe(timeframe)
    rates = mt5.copy_rates_from_pos(mt5_sym, tf, 0, n_bars + 20)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"MT5 无数据: {mt5_sym} ({timeframe})")

    # 【改动点】V3.0 收线确认：剔除当前未收盘 bar（bar 开盘 + 周期 > 服务器时间）。
    # MT5 周期常量即分钟数（M1=1, H1=60, D1=1440, W1=10080）。
    if close_confirm:
        try:
            server_time = int(mt5.symbol_info(mt5_sym).time)
            tf_seconds = int(tf) * 60
            closed_rates = [
                r for r in rates if int(r["time"]) + tf_seconds <= server_time
            ]
            if closed_rates:
                rates = closed_rates
        except Exception:
            pass  # 时钟/信息异常时保持原样，不阻断取数

    bars: list[KlineBar] = []
    for r in rates:
        bar = KlineBar(
            seq=0,
            ts_open=int(r["time"]) * 1000,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r["tick_volume"]),
            closed=True,
        )
        bars.append(normalize_kline_bar(bar))

    bars = bars[-n_bars:]
    bars.reverse()  # 新 -> 旧
    for i, b in enumerate(bars):
        object.__setattr__(b, "seq", i + 1)
    return bars


def compute_indicators(
    bars: list[KlineBar],
    *,
    rsi_period: int = 14,
    bollinger_period: int = 20,
    bollinger_std: float = 2.0,
    ema_period: int = 20,
    atr_period: int = 14,
) -> IndicatorBundle:
    """计算 EMA/ATR/RSI/布林带/VWAP（周期可配置）。

    输入 bars 为新→旧（seq=1 为最新），指标计算内部按旧→新预热，
    输出与输入同序（索引 0 = 最新 bar）。
    """
    n = len(bars)
    if n == 0:
        return IndicatorBundle()

    # 输入新→旧 → 反转成旧→新用于计算
    closes = [b.close for b in reversed(bars)]
    highs = [b.high for b in reversed(bars)]
    lows = [b.low for b in reversed(bars)]
    volumes = [b.volume for b in reversed(bars)]

    ema = ema_full(closes, ema_period)
    atr = atr_full(highs, lows, closes, atr_period)
    rsi = rsi_full(closes, rsi_period)
    bb_u, bb_m, bb_l = bollinger_full(closes, bollinger_period, bollinger_std)
    vwap = vwap_full(highs, lows, closes, volumes)

    # 计算结果是旧→新，反转回新→旧以对齐 bars
    return IndicatorBundle(
        ema20=tuple(reversed(ema)),
        atr14=tuple(reversed(atr)),
        rsi14=tuple(reversed(rsi)),
        bb_upper=tuple(reversed(bb_u)),
        bb_middle=tuple(reversed(bb_m)),
        bb_lower=tuple(reversed(bb_l)),
        vwap=tuple(reversed(vwap)),
    )


def _split_ticks_by_bar(
    ticks: list[Any],
    bars: list[KlineBar],
) -> list[list[Any]]:
    """把 tick 按时间归属到各 bar（bars 新→旧）。

    【改动点】V1.3.2 性能优化：原实现为 O(ticks×bars) 线性扫描，
    短周期大窗口（如 1m×2880 根）会退化到数亿次比较导致加载超时；
    改为时间正序窗口 + 二分定位，复杂度 O(ticks×log(bars))。
    """
    buckets: list[list[Any]] = [[] for _ in bars]
    if not ticks:
        return buckets

    # bar 时间窗口（新→旧）：ts_open 为开盘时刻
    windows: list[tuple[int, int]] = []
    for i, b in enumerate(bars):
        start = b.ts_open
        end = bars[i - 1].ts_open if i > 0 else b.ts_open + 3600_000 * 10
        windows.append((start, end))
    # 反转为时间正序（旧→新），供二分查找
    windows.reverse()
    starts = [w[0] for w in windows]

    for t in ticks:
        t_ms = t.time if t.time else 0
        if t_ms <= 0:
            continue
        # 二分定位最后一个 start <= t_ms 的窗口（时间正序索引 j）
        j = bisect.bisect_right(starts, t_ms) - 1
        if j >= 0 and t_ms < windows[j][1]:
            # 正序窗口 j 对应新→旧 bars 中的索引 len(bars)-1-j
            buckets[len(bars) - 1 - j].append(t)
    return buckets


def enrich_frame_with_orderflow(
    frame: KlineFrame,
    *,
    fetch_ticks: bool = True,
    va_pct: float = 0.682,
) -> KlineFrame:
    """为 frame 附加订单流：Delta/累积Delta/POC/VA/VWAP Delta/足迹。

    威科夫2.0 价值区域默认 68.2%（±1σ）。
    """
    bars = frame.bars
    n = len(bars)
    if n == 0:
        return frame

    deltas: list[float] = []
    poc_list: list[float] = []
    vah_list: list[float] = []
    val_list: list[float] = []
    bv_list: list[float] = []
    sv_list: list[float] = []
    vd_list: list[float] = []
    fp_list: list[Any] = []

    if fetch_ticks:
        try:
            import MetaTrader5 as mt5

            from wkf.data.mt5_tick_bridge import fetch_ticks_for_range

            if not ensure_mt5_initialized(mt5):
                return frame
            try:
                newest_ts = bars[0].ts_open
                oldest_ts = bars[-1].ts_open
                # 用「最新 bar 开盘 + 周期」构造上限（服务器时钟时间戳 → datetime），
                # 与 tick.time_msc 处于同一时钟基准。不能直接用 datetime.now()——
                # 真实 UTC 比服务器时钟慢约 3 小时，会导致最新 bar 的 tick 拉不到
                # （footprint[0]=None / delta[0]=0）。
                period_ms = (bars[0].ts_open - bars[1].ts_open) if n > 1 else 900_000
                dt_to = datetime.datetime.fromtimestamp((newest_ts + period_ms) / 1000)
                dt_from = datetime.datetime.fromtimestamp(oldest_ts / 1000)
                ticks = fetch_ticks_for_range(frame.symbol, dt_from, dt_to)
                buckets = _split_ticks_by_bar(ticks or [], bars)
            finally:
                mt5.shutdown()

            tick_size = get_tick_size(frame.symbol)
            for i, bucket in enumerate(buckets):
                if not bucket:
                    deltas.append(0.0)
                    poc_list.append(float("nan"))
                    vah_list.append(float("nan"))
                    val_list.append(float("nan"))
                    bv_list.append(float("nan"))
                    sv_list.append(float("nan"))
                    vd_list.append(float("nan"))
                    fp_list.append(None)
                    continue

                buy_vols = [t.volume for t in bucket if t.side == "buy"]
                sell_vols = [t.volume for t in bucket if t.side == "sell"]
                deltas.append(sum(buy_vols) - sum(sell_vols))

                vp = compute_volume_profile(bucket, tick_size=tick_size, va_pct=va_pct)
                if vp:
                    poc_list.append(vp.poc_price)
                    vah_list.append(vp.vah)
                    val_list.append(vp.val)
                else:
                    poc_list.append(float("nan"))
                    vah_list.append(float("nan"))
                    val_list.append(float("nan"))

                r = vwap_delta(
                    [t.mid_price for t in bucket],
                    [t.volume for t in bucket],
                    [t.side for t in bucket],
                )
                if r:
                    bv, sv, delta, _, _ = r
                    bv_list.append(bv)
                    sv_list.append(sv)
                    vd_list.append(delta)
                else:
                    bv_list.append(float("nan"))
                    sv_list.append(float("nan"))
                    vd_list.append(float("nan"))

                fp = build_footprint(bucket, tick_size=tick_size)
                fp_list.append(fp)
        except Exception:
            return frame
    else:
        deltas = [0.0] * n
        poc_list = [float("nan")] * n
        vah_list = [float("nan")] * n
        val_list = [float("nan")] * n
        bv_list = [float("nan")] * n
        sv_list = [float("nan")] * n
        vd_list = [float("nan")] * n
        fp_list = [None] * n

    cum = compute_cumulative_delta(deltas)  # 新->旧累积（从新端开始累加）

    of = OrderFlowBundle(
        delta=tuple(deltas),
        cumulative_delta=tuple(cum),
        poc_price=tuple(poc_list),
        vah=tuple(vah_list),
        val=tuple(val_list),
        buy_vwap=tuple(bv_list),
        sell_vwap=tuple(sv_list),
        vwap_delta=tuple(vd_list),
        footprint=tuple(fp_list),
    )
    return KlineFrame(
        symbol=frame.symbol,
        timeframe=frame.timeframe,
        bars=frame.bars,
        indicators=frame.indicators,
        snapshot_ts_local_ms=frame.snapshot_ts_local_ms,
        orderflow=of,
    )

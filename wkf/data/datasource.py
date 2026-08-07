"""统一数据源抽象基类（需求三：可选数据源拓展）。

【改动点】需求三.1：在 data 层搭建统一数据源抽象基类。
 - 定义 DataSource ABC：fetch_bars（拉K线）/ get_tick_size / has_ticks（是否支持Tick）
 - MT5 数据源（MT5Source 适配既有 mt5_source 模块）
 - yfinance 数据源（YfinanceSource，可选依赖，未安装时返回明确错误）
 - 提供 get_data_source() 工厂：按 settings.general.data_source 选择。
【涉及文件】wkf/data/datasource.py（新增）
【验证方式】python -m unittest discover tests；data_source="mt5" 时行为与旧版完全一致；
            data_source="yfinance" 且未安装 yfinance 时返回"未安装 yfinance"错误。
"""
from __future__ import annotations

import datetime
from abc import ABC, abstractmethod

from wkf.data.base import KlineBar

# 数据源模式常量
DS_MT5 = "mt5"
DS_YFINANCE = "yfinance"


class DataSource(ABC):
    """统一行情数据源抽象基类。"""

    name: str = "base"

    @abstractmethod
    def fetch_bars(
        self,
        symbol: str,
        timeframe: str = "15m",
        n_bars: int = 100,
    ) -> list[KlineBar]:
        """拉取 K 线，返回新→旧顺序的 KlineBar 列表。"""

    @abstractmethod
    def get_tick_size(self, symbol: str) -> float:
        """返回品种价格最小变动单位。"""

    @property
    @abstractmethod
    def has_ticks(self) -> bool:
        """是否支持 Tick 级数据（订单流/足迹图依赖）。"""

    def available_symbols(self) -> list[str]:
        """本数据源支持的品种列表。"""
        return []


class MT5Source(DataSource):
    """MT5 数据源：适配既有 wkf.data.mt5_source 实现（完整功能）。"""

    name = DS_MT5

    def fetch_bars(self, symbol: str, timeframe: str = "15m", n_bars: int = 100) -> list[KlineBar]:
        from wkf.data.mt5_source import fetch_mt5_bars

        return fetch_mt5_bars(symbol, timeframe, n_bars)

    def get_tick_size(self, symbol: str) -> float:
        from wkf.data.mt5_source import get_tick_size as _mt5_tick

        return _mt5_tick(symbol)

    @property
    def has_ticks(self) -> bool:
        return True

    def available_symbols(self) -> list[str]:
        return ["NQ1!", "ES1!", "GC1!"]


class YfinanceSource(DataSource):
    """yfinance 数据源（可选依赖，非强制安装）。

    支持 BTC-USD / 美股指数（^GSPC 等）。无 Tick 数据：
      · fetch_bars 基于 1 分钟 OHLCV 重采样到目标周期；
      · has_ticks=False → GUI 自动隐藏订单流面板并弹窗提示；
      · 上层指标与威科夫结构分析逻辑无需改动（仍走 KlineBar/KlineFrame）。
    """

    name = DS_YFINANCE

    def __init__(self) -> None:
        self._mod = None  # 惰性导入 yfinance（未安装则为 None）

    def _require(self):
        """惰性导入 yfinance；未安装抛出带说明的异常。"""
        if self._mod is None:
            try:
                import yfinance as yf  # type: ignore
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "未安装 yfinance 可选依赖。如需启用通用行情数据源，"
                    "请手动执行: pip install yfinance"
                ) from exc
            self._mod = yf
        return self._mod

    # 周期（内部键）→ yfinance interval
    _TF_INTERVAL = {
        "1m": "1m", "3m": "5m", "5m": "5m", "10m": "15m", "15m": "15m",
        "30m": "30m", "1h": "60m", "2h": "1h", "4h": "1h",
        "1d": "1d", "1w": "1wk",
    }
    # 周期（内部键）→ 重采样分钟数
    _TF_MINUTES = {
        "1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30,
        "1h": 60, "2h": 120, "4h": 240, "1d": 1440, "1w": 10080,
    }
    # 常用品种（yfinance ticker）
    _SYMBOLS = ["BTC-USD", "^GSPC", "^NDX", "^DJI"]

    def fetch_bars(self, symbol: str, timeframe: str = "15m", n_bars: int = 100) -> list[KlineBar]:
        """基于 yfinance 历史分钟线拉取并重采样。

        说明：yfinance 免费接口对 1m 数据仅保留最近 7 天；更早周期自动降级
        到 5m/15m/30m/60m/1d/1wk 原始间隔，并在重采样后截取最近 n_bars 根。
        """
        yf = self._require()
        interval = self._TF_INTERVAL.get(timeframe, "15m")
        # 需要的历史时长（分钟），放宽系数保证重采样根数充足
        period_min = self._TF_MINUTES.get(timeframe, 15) * max(n_bars, 100) * 1.5
        period = self._period_for(period_min)

        df = yf.download(symbol, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            raise RuntimeError(f"yfinance 无数据: {symbol} ({timeframe})")

        # 多级列展开（auto_adjust 后列可能为 MultiIndex）
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)

        o = df["Open"].astype(float).tolist()
        h = df["High"].astype(float).tolist()
        l = df["Low"].astype(float).tolist()
        c = df["Close"].astype(float).tolist()
        v = df["Volume"].astype(float).tolist()

        target_min = self._TF_MINUTES.get(timeframe, 15)
        if interval != timeframe and timeframe != "1d" and timeframe != "1w":
            o, h, l, c, v = self._resample(o, h, l, c, v, target_min // self._TF_MINUTES.get(interval, 1))

        # 转 KlineBar（新→旧）
        ts_list = self._timestamps(df, interval)
        bars: list[KlineBar] = []
        n = min(len(c), n_bars)
        for i in range(len(c) - n, len(c)):
            bars.append(
                KlineBar(
                    seq=0,
                    ts_open=int(ts_list[i]),
                    open=float(o[i]),
                    high=float(h[i]),
                    low=float(l[i]),
                    close=float(c[i]),
                    volume=float(v[i]),
                    closed=True,
                )
            )
        bars.reverse()
        for i, b in enumerate(bars):
            object.__setattr__(b, "seq", i + 1)
        return bars

    def _period_for(self, minutes: float) -> str:
        days = int(minutes / 1440) + 1
        if days <= 7:
            return "7d"
        if days <= 30:
            return "1mo"
        if days <= 90:
            return "3mo"
        if days <= 180:
            return "6mo"
        return "1y"

    def _timestamps(self, df, interval: str) -> list[int]:
        idx = df.index.tolist()
        if interval in ("1d", "1wk"):
            out = []
            for ts in idx:
                if isinstance(ts, datetime.datetime):
                    out.append(int(ts.replace(tzinfo=None).timestamp() * 1000))
                else:
                    out.append(int(ts.timestamp() * 1000))
            return out
        out = []
        for ts in idx:
            if hasattr(ts, "timestamp"):
                out.append(int(ts.timestamp() * 1000))
            else:
                out.append(int(datetime.datetime.fromisoformat(str(ts)).timestamp() * 1000))
        return out

    def _resample(self, o, h, l, c, v, factor: int) -> tuple[list, list, list, list, list]:
        """简单聚合重采样（factor=每根合并根数）。K 线数据量小，O(n) 足够。"""
        if factor <= 1:
            return o, h, l, c, v
        ro, rh, rl, rc, rv = [], [], [], [], []
        i = 0
        while i < len(c):
            chunk = c[i: i + factor]
            if not chunk:
                break
            ro.append(o[i])
            rh.append(max(h[i: i + factor]))
            rl.append(min(l[i: i + factor]))
            rc.append(chunk[-1])
            rv.append(sum(v[i: i + factor]))
            i += factor
        return ro, rh, rl, rc, rv

    def get_tick_size(self, symbol: str) -> float:
        # yfinance 无 Tick 级精度信息，按报价数量级估算
        if symbol in ("BTC-USD",):
            return 1.0
        if symbol in ("^GSPC", "^NDX", "^DJI"):
            return 0.01
        return 0.01

    @property
    def has_ticks(self) -> bool:
        return False

    def available_symbols(self) -> list[str]:
        return list(self._SYMBOLS)


def get_data_source(mode: str | None = None) -> DataSource:
    """按配置返回数据源实例。

    mode: "mt5"（默认）/ "yfinance"。None 时读取 settings.general.data_source。
    """
    if mode is None:
        try:
            from wkf.config.settings import load_settings

            mode = load_settings().general.data_source
        except Exception:
            mode = DS_MT5
    if mode == DS_YFINANCE:
        return YfinanceSource()
    return MT5Source()

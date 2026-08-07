"""K线磁盘缓存：重复访问同一品种周期直接读取缓存，跳过 MT5 接口请求。

【改动点】需求2-3：新增 K 线磁盘缓存（cache_manager.py）。
 - 缓存文件：cache/kline_{symbol}_{timeframe}.json（含拉取时间戳）
 - TTL：默认 300 秒；超过有效期自动失效回源
 - 序列化 KlineBar 字段：seq/ts_open/open/high/low/close/volume
【涉及文件】wkf/data/cache_manager.py（新增，对应假设文件 cache_manager.py）
【验证方式】首次拉取后再次访问同品种周期：磁盘命中跳过接口请求，切换耗时显著下降
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from wkf.data.base import KlineBar

# 缓存目录：项目根 /cache/
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"
# 缓存有效期（秒）
CACHE_TTL_S = 300


def _safe_name(symbol: str, timeframe: str) -> str:
    """文件名安全化（symbol 可能含 ! 等字符）。"""
    return f"{symbol.replace('!', '_').replace('/', '_')}_{timeframe}"


def disk_cache_put(symbol: str, timeframe: str, bars: list[KlineBar]) -> bool:
    """写入磁盘缓存（K线 JSON）。失败静默返回 False。"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "ts": int(time.time()),
            "bars": [
                {
                    "seq": b.seq,
                    "t": b.ts_open,
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume,
                }
                for b in bars
            ],
        }
        path = CACHE_DIR / f"kline_{_safe_name(symbol, timeframe)}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return True
    except Exception:
        return False


def disk_cache_get(symbol: str, timeframe: str, max_age_s: int = CACHE_TTL_S) -> list[KlineBar] | None:
    """读取磁盘缓存：未命中/过期返回 None。"""
    try:
        path = CACHE_DIR / f"kline_{_safe_name(symbol, timeframe)}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - int(data.get("ts", 0)) > max_age_s:
            return None
        bars = []
        for item in data.get("bars", []):
            bars.append(
                KlineBar(
                    seq=int(item["seq"]),
                    ts_open=int(item["t"]),
                    open=float(item["o"]),
                    high=float(item["h"]),
                    low=float(item["l"]),
                    close=float(item["c"]),
                    volume=float(item["v"]),
                )
            )
        return bars if bars else None
    except Exception:
        return None

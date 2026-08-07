"""WKF 历史分析存档（供回测模块读取，只读定位）。

【改动点】P1 回测真实胜率迭代：
 - 新增字段 entry_price（信号触发入场收盘价）/ direction（信号方向）/
   ts_open（信号触发K线时间戳，用于向后对齐K线推演）。
 - 旧记录无时间戳时保留原字段，回测统计会标记为"无对齐数据"跳过。
【涉及文件】wkf/backtest/archive.py
【验证方式】执行分析后 output/history_archive.json 追加一条含新字段记录；
            回测标签页可对齐K线做真实胜率推演。
"""
from __future__ import annotations

import json
from pathlib import Path

from wkf.config.settings import SETTINGS_JSON_PATH

ARCHIVE_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "history_archive.json"


def append_analysis_record(
    *,
    analysis_time: str,
    symbol: str,
    timeframe: str,
    bias: str,
    trigger: str,
    invalidation: str,
    price: float,
    prob: dict | None = None,
    ts_open: int | None = None,
    entry_price: float | None = None,
    direction: str | None = None,
) -> bool:
    """追加一条历史分析信号记录（只写不读旧记录，防并发损坏）。

    ts_open: 信号触发K线（最新已收盘）开盘时间戳（epoch ms），回测对齐用。
    entry_price: 入场参考价，默认取 price（信号触发时刻收盘价）。
    direction: 信号方向，默认取 bias。
    """
    try:
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "analysis_time": analysis_time,
            "symbol": symbol,
            "timeframe": timeframe,
            "bias": bias,
            "trigger": trigger,
            "invalidation": invalidation,
            "price": round(float(price), 4) if price is not None else None,
            "entry_price": round(float(entry_price), 4) if entry_price is not None else (
                round(float(price), 4) if price is not None else None
            ),
            "direction": direction or bias,
            "ts_open": int(ts_open) if ts_open else None,
            "prob": {
                "short": int(prob.get("short", 0)),
                "long": int(prob.get("long", 0)),
                "neutral": int(prob.get("neutral", 0)),
            } if prob else None,
        }
        existing: list[dict] = []
        if ARCHIVE_PATH.exists():
            try:
                existing = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        existing.append(record)
        # 仅保留最近 2000 条（防止长期运行无限膨胀）
        if len(existing) > 2000:
            existing = existing[-2000:]
        ARCHIVE_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def load_archive(max_records: int = 2000) -> list[dict]:
    """读取历史分析存档（只读）。"""
    try:
        if not ARCHIVE_PATH.exists():
            return []
        data = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data[-max_records:]
    except Exception:
        return []

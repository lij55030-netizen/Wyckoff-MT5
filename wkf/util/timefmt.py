"""时间工具。"""
from __future__ import annotations

import datetime
import time


def now_local_ms() -> int:
    return int(time.time() * 1000)


# 【改动点】强制锁定东八区（Asia/Shanghai）北京时间时间源。
# 系统默认时区可能非东八区（欧美时区），分析时间/顶部时钟必须统一使用北京时间。
# 【涉及文件】wkf/util/timefmt.py（对应假设文件 config_const.py 时区常量）
# 【验证方式】修改电脑系统时区为欧美时区，顶部时钟与决策分析时间依旧显示北京时间
_BEIJING_TZ = None


def beijing_tz():
    """返回 Asia/Shanghai 时区对象（zoneinfo；失败时退回固定 UTC+8 偏移）。"""
    global _BEIJING_TZ
    if _BEIJING_TZ is None:
        try:
            from zoneinfo import ZoneInfo

            _BEIJING_TZ = ZoneInfo("Asia/Shanghai")
        except Exception:
            _BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))
    return _BEIJING_TZ


def beijing_now() -> datetime.datetime:
    """当前北京时间（强制 Asia/Shanghai，与系统时区无关）。"""
    return datetime.datetime.now(beijing_tz())


def beijing_now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return beijing_now().strftime(fmt)

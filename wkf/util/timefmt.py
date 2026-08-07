"""时间工具。"""
from __future__ import annotations

import time


def now_local_ms() -> int:
    return int(time.time() * 1000)

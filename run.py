"""直接运行此文件启动 WKF GUI。

用法: python run.py
"""
from __future__ import annotations

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
os.chdir(_here)

from wkf.main import main

if __name__ == "__main__":
    raise SystemExit(main())

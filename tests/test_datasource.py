"""数据源抽象层单元测试（需求三：yfinance 可选数据源）。

覆盖：
  1. get_data_source 工厂：默认 mt5 / 显式 yfinance
  2. MT5Source 接口契约（fetch_bars 走既有实现、has_ticks=True）
  3. YfinanceSource 未安装依赖时的明确报错；has_ticks=False
  4. yfinance 重采样逻辑（纯函数 _resample）

【改动点】需求三：data 层统一数据源抽象基类 + yfinance 适配层。
【涉及文件】tests/test_datasource.py（新增）
【验证方式】python -m unittest discover tests -v 全绿。
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from wkf.data.datasource import (
    DS_MT5,
    DS_YFINANCE,
    MT5Source,
    YfinanceSource,
    get_data_source,
)


class TestDataSourceFactory(unittest.TestCase):
    def test_default_mt5(self) -> None:
        src = get_data_source(None)
        self.assertIsInstance(src, MT5Source)
        self.assertTrue(src.has_ticks)
        self.assertEqual(src.name, DS_MT5)

    def test_explicit_mt5(self) -> None:
        self.assertIsInstance(get_data_source("mt5"), MT5Source)

    def test_explicit_yfinance(self) -> None:
        src = get_data_source("yfinance")
        self.assertIsInstance(src, YfinanceSource)
        self.assertFalse(src.has_ticks)
        self.assertEqual(src.name, DS_YFINANCE)

    def test_yfinance_available_symbols(self) -> None:
        src = get_data_source("yfinance")
        syms = src.available_symbols()
        self.assertIn("BTC-USD", syms)


class TestMT5Source(unittest.TestCase):
    def test_tick_size(self) -> None:
        src = MT5Source()
        self.assertGreater(src.get_tick_size("GC1!"), 0)
        self.assertGreater(src.get_tick_size("BTC-USD"), 0)

    def test_available_symbols(self) -> None:
        """MT5 品种列表为动态获取（≥3 且包含可见核心品种）。"""
        syms = MT5Source().available_symbols()
        self.assertGreaterEqual(len(syms), 3)
        self.assertIn("XAUUSD", syms)
        self.assertIn("US500c", syms)
        self.assertIn("USTECHc", syms)


class TestYfinanceSource(unittest.TestCase):
    def test_require_dependency(self) -> None:
        src = YfinanceSource()
        try:
            mod = src._require()
            self.assertIsNotNone(mod)  # 已安装 → 返回模块对象
        except RuntimeError as exc:
            # 未安装 → 必须带 yfinance 安装说明
            self.assertIn("yfinance", str(exc))

    def test_resample(self) -> None:
        src = YfinanceSource()
        o = [1.0, 2.0, 3.0, 4.0]
        h = [2.0, 3.0, 4.0, 5.0]
        l = [0.5, 1.5, 2.5, 3.5]
        c = [1.5, 2.5, 3.5, 4.5]
        v = [10.0, 20.0, 30.0, 40.0]
        ro, rh, rl, rc, rv = src._resample(o, h, l, c, v, factor=2)
        self.assertEqual(rc, [2.5, 4.5])          # 每段取末根收盘
        self.assertEqual(rh, [3.0, 5.0])          # 每段取最高
        self.assertEqual(rl, [0.5, 2.5])          # 每段取最低
        self.assertEqual(rv, [30.0, 70.0])        # 每段量累加

    def test_period_for(self) -> None:
        src = YfinanceSource()
        self.assertEqual(src._period_for(1440 * 3), "7d")
        self.assertEqual(src._period_for(1440 * 40), "3mo")
        self.assertEqual(src._period_for(1440 * 400), "1y")


if __name__ == "__main__":
    unittest.main()

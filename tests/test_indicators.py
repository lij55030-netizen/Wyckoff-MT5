"""指标计算公式单元测试（tests 目录，标准库 unittest，零额外依赖）。

覆盖：RSI / EMA / ATR / 布林带 / VWAP / Delta / VolumeProfile(POC/VA) / Footprint 失衡。

【改动点】需求一.2：新建 tests/ 单元测试目录，为 indicators 指标计算公式编写自动化测试。
【涉及文件】tests/test_indicators.py（新增）
【验证方式】python -m unittest discover tests -v 全绿；后续底层指标改动可回归校验。
"""
from __future__ import annotations

import math
import unittest
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from wkf.indicators.rsi import rsi_full
from wkf.indicators.ema_atr import atr_full, ema_full
from wkf.indicators.bollinger import bollinger_full
from wkf.indicators.vwap import vwap_full, vwap_delta
from wkf.indicators.delta import compute_cumulative_delta, compute_delta
from wkf.indicators.volume_profile import compute_volume_profile
from wkf.indicators.footprint import (
    build_footprint,
    detect_stacked_imbalances,
    get_imbalances,
)


class _Tick:
    """模拟 tick（mid_price / volume / side）。"""

    __slots__ = ("mid_price", "volume", "side")

    def __init__(self, p: float, v: float = 1.0, side: str = "buy") -> None:
        self.mid_price = p
        self.volume = v
        self.side = side


class TestRSI(unittest.TestCase):
    def test_length_and_nan_prelude(self) -> None:
        closes = [float(i) for i in range(1, 31)]
        rsi = rsi_full(closes, period=14)
        self.assertEqual(len(rsi), 30)
        # 前 period 个为 NaN（预热不足，idx=period 起有值）
        for i in range(14):
            self.assertTrue(math.isnan(rsi[i]), f"idx {i} 应为 NaN")
        self.assertFalse(math.isnan(rsi[14]))

    def test_known_values(self) -> None:
        # 全部上涨 → RSI 恒 100
        closes = [100.0 + i * 1.0 for i in range(40)]
        rsi = rsi_full(closes, period=14)
        self.assertEqual(rsi[-1], 100.0)

        # 全部下跌 → RSI 恒 0
        closes = [200.0 - i * 1.0 for i in range(40)]
        rsi = rsi_full(closes, period=14)
        self.assertEqual(rsi[-1], 0.0)

    def test_bounded_0_100(self) -> None:
        closes = [float((i * 7919) % 100) for i in range(80)]
        rsi = rsi_full(closes, period=14)
        for v in rsi:
            if not math.isnan(v):
                self.assertTrue(0.0 <= v <= 100.0)


class TestEMAATR(unittest.TestCase):
    def test_ema_constant_series(self) -> None:
        closes = [50.0] * 30
        ema = ema_full(closes, period=20)
        self.assertEqual(ema[-1], 50.0)

    def test_atr_constant_range(self) -> None:
        highs = [10.0] * 30
        lows = [9.0] * 30
        closes = [9.5] * 30
        atr = atr_full(highs, lows, closes, period=14)
        self.assertEqual(atr[-1], 1.0)  # high-low 恒定 1.0

    def test_atr_length(self) -> None:
        highs = [10.0 + i * 0.1 for i in range(30)]
        lows = [9.0 + i * 0.1 for i in range(30)]
        closes = [9.5 + i * 0.1 for i in range(30)]
        atr = atr_full(highs, lows, closes, period=14)
        self.assertEqual(len(atr), 30)
        for i in range(14):
            self.assertTrue(math.isnan(atr[i]))


class TestBollinger(unittest.TestCase):
    def test_constant_series_zero_width(self) -> None:
        closes = [42.0] * 30
        u, m, l = bollinger_full(closes, period=20, num_std=2.0)
        self.assertEqual(m[-1], 42.0)
        self.assertEqual(u[-1], 42.0)
        self.assertEqual(l[-1], 42.0)

    def test_order_upper_geq_middle_geq_lower(self) -> None:
        closes = [float((i * 97) % 60 + 40) for i in range(50)]
        u, m, l = bollinger_full(closes, period=20, num_std=2.0)
        for i in range(len(closes)):
            if not (math.isnan(u[i]) or math.isnan(m[i]) or math.isnan(l[i])):
                self.assertTrue(u[i] >= m[i] >= l[i], f"idx {i}")


class TestVWAP(unittest.TestCase):
    def test_vwap_cumulative(self) -> None:
        highs = [10.0, 12.0, 14.0]
        lows = [8.0, 10.0, 12.0]
        closes = [9.0, 11.0, 13.0]
        vols = [2.0, 2.0, 2.0]
        vwap = vwap_full(highs, lows, closes, vols)
        # 第0根: tp=(10+8+9)/3=9, vwap=9
        self.assertAlmostEqual(vwap[0], 9.0, places=6)
        # 第1根: tp=(12+10+11)/3=11 → (9*2+11*2)/4=10
        self.assertAlmostEqual(vwap[1], 10.0, places=6)

    def test_vwap_delta_sides(self) -> None:
        prices = [100.0, 101.0, 102.0]
        vols = [1.0, 2.0, 3.0]
        sides = ["buy", "sell", "buy"]
        r = vwap_delta(prices, vols, sides)
        self.assertIsNotNone(r)
        buy_vwap, sell_vwap, delta, buy_vol, sell_vol = r
        self.assertAlmostEqual(buy_vwap, (100 * 1 + 102 * 3) / 4.0, places=6)
        self.assertAlmostEqual(sell_vwap, 101.0, places=6)
        self.assertAlmostEqual(delta, 1 + 3 - 2, places=6)
        self.assertAlmostEqual(buy_vol, 4.0)
        self.assertAlmostEqual(sell_vol, 2.0)


class TestDelta(unittest.TestCase):
    def test_delta_and_cumulative(self) -> None:
        self.assertEqual(compute_delta([5.0, 3.0], [2.0, 4.0]), 2.0)
        cum = compute_cumulative_delta([10.0, -4.0, 6.0])
        self.assertEqual(cum, [10.0, 6.0, 12.0])


class TestVolumeProfile(unittest.TestCase):
    def test_poc_vah_val(self) -> None:
        # 构造多点分布，确保 VA 扩展后 vah > val
        ticks = [
            _Tick(100.0, 5.0),
            _Tick(100.0, 5.0),   # POC（量最大）
            _Tick(100.25, 2.0),
            _Tick(99.75, 2.0),
            _Tick(99.50, 2.0),
            _Tick(100.50, 2.0),
            _Tick(99.25, 2.0),
        ]
        vp = compute_volume_profile(ticks, tick_size=0.25, va_pct=0.682)
        self.assertIsNotNone(vp)
        self.assertEqual(vp.poc_price, 100.0)
        # 从 POC 向两侧扩展，VA 应包含 POC
        self.assertTrue(vp.val <= vp.poc_price <= vp.vah)
        self.assertGreater(vp.vah, vp.val)

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(compute_volume_profile([]))


class TestFootprint(unittest.TestCase):
    def test_build_footprint_delta(self) -> None:
        ticks = [
            _Tick(100.0, 2.0, "buy"),
            _Tick(100.0, 1.0, "sell"),
            _Tick(100.25, 3.0, "buy"),
        ]
        fp = build_footprint(ticks, tick_size=0.25)
        self.assertIsNotNone(fp)
        self.assertEqual(fp.delta, 4.0)  # (2+3) - 1
        self.assertEqual(fp.total_volume, 6.0)

    def test_imbalances(self) -> None:
        ticks = [
            _Tick(100.0, 4.0, "buy"),
            _Tick(100.0, 1.0, "sell"),   # 4x 失衡 buy
        ]
        fp = build_footprint(ticks, tick_size=0.25)
        imb = get_imbalances(fp, thresholds=(2.0, 3.0, 4.0))
        self.assertTrue(any(i["side"] == "buy" and i["level"] == 3 for i in imb))

    def test_stacked_imbalances(self) -> None:
        ticks = [
            _Tick(100.0, 4.0, "buy"), _Tick(100.0, 1.0, "sell"),
            _Tick(100.25, 4.0, "buy"), _Tick(100.25, 1.0, "sell"),
        ]
        fp = build_footprint(ticks, tick_size=0.25)
        imb = get_imbalances(fp)
        stacks = detect_stacked_imbalances(imb, tick_size=0.25, min_stack=2)
        self.assertGreaterEqual(len(stacks), 1)


if __name__ == "__main__":
    unittest.main()

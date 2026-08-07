"""威科夫三层核心判定 + 关键价位（VAH/VAL/VPOC/VWAP）单元测试。

覆盖：
  1. value_area: compute_value_area / build_profile_from_ohlcv / price_position
  2. background: analyze_background（趋势/区间/吸筹/派发/背景不明）
  3. orderflow_verify: verify_orderflow（失衡/堆叠/衰竭/吸收/反转阶段）
  4. analyzer: analyze 三层集成（bias/trigger/invalidation 组合）

【改动点】需求一.2：为威科夫三层核心判定逻辑与 VAH/VAL/VPOC/VWAP 关键价位
计算编写自动化测试用例，后续底层代码修改可做回归校验。
【涉及文件】tests/test_wyckoff.py（新增）
【验证方式】python -m unittest discover tests -v 全绿。
"""
from __future__ import annotations

import math
import unittest
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from wkf.data.base import IndicatorBundle, KlineBar, KlineFrame
from wkf.wyckoff.background import analyze_background
from wkf.wyckoff.value_area import (
    ValueAreaResult,
    build_profile_from_ohlcv,
    compute_value_area,
)
from wkf.wyckoff.orderflow_verify import verify_orderflow


def _bars(highs, lows, closes, volumes=None) -> list[KlineBar]:
    n = len(closes)
    vols = volumes or [100.0] * n
    # bars 新→旧：输入按旧→新给出，这里反转
    out: list[KlineBar] = []
    for i in range(n):
        out.append(
            KlineBar(
                seq=n - i,
                ts_open=1_700_000_000_000 - i * 60_000,
                open=closes[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=vols[i],
                closed=True,
            )
        )
    out.reverse()
    return out


def _frame(symbol: str = "GC1!", n: int = 60) -> KlineFrame:
    """构造 n 根平稳震荡K线（新→旧）的 frame（无订单流，走 OHLCV 近似）。"""
    import random

    rnd = random.Random(42)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] + rnd.uniform(-0.5, 0.5))
    # 旧→新（compute_indicators 内部会再反转）
    highs = [c + 0.4 for c in closes]
    lows = [c - 0.4 for c in closes]
    bars = _bars(highs[::-1], lows[::-1], closes[::-1])
    ind = IndicatorBundle(
        ema20=tuple([100.0] * n),
        atr14=tuple([0.5] * n),
        rsi14=tuple([50.0] * n),
        bb_upper=tuple([101.0] * n),
        bb_middle=tuple([100.0] * n),
        bb_lower=tuple([99.0] * n),
        vwap=tuple([100.0] * n),
    )
    return KlineFrame(symbol=symbol, timeframe="15m", bars=tuple(bars), indicators=ind)


class TestValueArea(unittest.TestCase):
    def test_compute_value_area_basic(self) -> None:
        prices = [100.0, 100.5, 101.0, 101.5, 102.0]
        vols = [10.0, 20.0, 40.0, 20.0, 10.0]  # VPOC=101.0
        va = compute_value_area(prices, vols, vwap=101.2, va_pct=0.682)
        self.assertIsNotNone(va)
        self.assertEqual(va.vpoc, 101.0)
        self.assertLessEqual(va.val, va.vah)
        self.assertAlmostEqual(va.vwap, 101.2, places=6)

    def test_midpoint_and_width(self) -> None:
        va = ValueAreaResult(vah=102.0, val=100.0, vpoc=101.0, vwap=None, va_width=2.0)
        self.assertEqual(va.midpoint, 101.0)
        self.assertAlmostEqual(va.va_width, 2.0, places=6)

    def test_price_position(self) -> None:
        va = ValueAreaResult(vah=102.0, val=100.0, vpoc=101.0, vwap=None)
        self.assertEqual(va.price_position(103.0), "above_va")
        self.assertEqual(va.price_position(99.0), "below_va")
        self.assertEqual(va.price_position(101.0), "inside_va")

    def test_compute_value_area_invalid(self) -> None:
        self.assertIsNone(compute_value_area([], []))
        self.assertIsNone(compute_value_area([1.0, 2.0], [3.0]))

    def test_build_profile_from_ohlcv(self) -> None:
        highs = [101.0, 102.0]
        lows = [99.0, 100.0]
        closes = [100.0, 101.0]
        vols = [100.0, 200.0]
        prices, volumes = build_profile_from_ohlcv(highs, lows, closes, vols, tick_size=0.5)
        self.assertTrue(len(prices) > 0)
        self.assertEqual(len(prices), len(volumes))
        self.assertEqual(sum(volumes), sum(vols))  # 成交量守恒


class TestBackground(unittest.TestCase):
    def _run(self, highs_old_to_new, lows_old_to_new, closes_old_to_new, **kw):
        # analyze_background 期望新→旧
        return analyze_background(
            highs_old_to_new[::-1], lows_old_to_new[::-1], closes_old_to_new[::-1], **kw
        )

    @staticmethod
    def _swing_series(direction: int, n: int = 40) -> tuple[list[float], list[float], list[float]]:
        """正弦波 + 线性趋势构造规整峰谷：direction=1 上升(HH+HL)，-1 下降(LH+LL)。

        _find_swings(left=2,right=2) 需要每个峰/谷在左右各2根内为极值；
        正弦周期取 10 根（峰谷间距 5 根），必然满足枢轴条件。
        """
        import math

        amp = 1.5
        trend_per_bar = 0.5 * direction
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        for i in range(n):
            mid = 100.0 + trend_per_bar * i + amp * math.sin(2 * math.pi * i / 10.0)
            highs.append(mid + 0.5)
            lows.append(mid - 0.5)
            closes.append(mid)
        return highs, lows, closes

    def test_trend_up(self) -> None:
        highs, lows, closes = self._swing_series(+1)
        bg = self._run(highs, lows, closes, swing_window=40)
        self.assertEqual(bg.regime, "trend_up", msg=str(bg.reasoning))
        self.assertGreaterEqual(bg.hh_hl_count, 2)

    def test_trend_down(self) -> None:
        highs, lows, closes = self._swing_series(-1)
        bg = self._run(highs, lows, closes, swing_window=40)
        self.assertEqual(bg.regime, "trend_down", msg=str(bg.reasoning))
        self.assertGreaterEqual(bg.lh_ll_count, 2)

    def test_range_neutral(self) -> None:
        base = 100.0
        n = 30
        highs = [base + (1.0 if i % 4 == 0 else 0.5) for i in range(n)]
        lows = [base - (1.0 if i % 4 == 0 else 0.5) for i in range(n)]
        closes = [base] * n
        bg = self._run(highs, lows, closes, swing_window=40)
        self.assertEqual(bg.regime, "range")

    def test_insufficient_data_unknown(self) -> None:
        highs = [100.0, 101.0]
        lows = [99.0, 100.0]
        closes = [100.0, 100.5]
        bg = analyze_background(highs[::-1], lows[::-1], closes[::-1])
        self.assertEqual(bg.regime, "unknown")


class TestOrderFlowVerify(unittest.TestCase):
    class _FP:
        """极简 footprint 桩。"""

        def __init__(self, levels, total_volume=100.0):
            self.price_levels = levels
            self.total_volume = total_volume

    def test_no_footprint_delta_side(self) -> None:
        res = verify_orderflow(bars_delta=[5.0], cumulative_delta=10.0, footprint=None, tick_size=0.25)
        self.assertEqual(res.active_side, "buy")
        self.assertEqual(res.delta, 5.0)

    def test_imbalance_buy_level(self) -> None:
        fp = self._FP({100.0: {"bid": 4.0, "ask": 1.0}})  # 4x buy
        res = verify_orderflow(
            bars_delta=[1.0], cumulative_delta=1.0, footprint=fp, tick_size=0.25
        )
        self.assertEqual(res.active_side, "buy")
        self.assertTrue(any(i["side"] == "buy" and i["level"] == 3 for i in res.imbalances))

    def test_stacked_imbalances(self) -> None:
        fp = self._FP({
            100.0: {"bid": 4.0, "ask": 1.0},
            100.25: {"bid": 4.0, "ask": 1.0},
        })
        res = verify_orderflow(
            bars_delta=[2.0], cumulative_delta=2.0, footprint=fp, tick_size=0.25
        )
        self.assertGreaterEqual(len(res.stacked_imbalances), 1)

    def test_exhaustion_detected(self) -> None:
        # 上一根强 delta + 本根反转且幅度接近 → 衰竭
        fp = self._FP({100.0: {"bid": 1.0, "ask": 1.0}}, total_volume=10.0)
        res = verify_orderflow(
            bars_delta=[-8.0, 10.0], cumulative_delta=2.0, footprint=fp, tick_size=0.25
        )
        self.assertTrue(res.exhaustion)

    def _absorption_bars(self, cur_rng=0.5, cur_vol=300.0, cur_close=100.8, cur_open=100.6):
        """构造吸收判定用 K 线（新→旧）：当前放量+窄幅，前两根正常量幅。"""
        return [
            KlineBar(seq=1, ts_open=3, open=cur_open, high=100.9,
                     low=round(100.9 - cur_rng, 2), close=cur_close,
                     volume=cur_vol, closed=True),
            KlineBar(seq=2, ts_open=2, open=100.2, high=101.0, low=99.8,
                     close=100.6, volume=110.0, closed=True),
            KlineBar(seq=3, ts_open=1, open=99.8, high=100.5, low=99.5,
                     close=100.2, volume=100.0, closed=True),
        ]

    def test_absorption_positive(self) -> None:
        """吸收结构正向：放量 + 窄幅 + 阳线但 Delta 负（背离）→ absorption=True。"""
        bars = self._absorption_bars()
        res = verify_orderflow(
            bars_delta=[-5.0, 10.0], cumulative_delta=5.0,
            footprint=None, tick_size=0.25, bars=bars,
        )
        self.assertTrue(res.absorption)
        self.assertEqual(res.reversal_stage, "absorption")
        self.assertTrue(any("吸收结构" in r for r in res.reasoning))

    def test_absorption_negative_no_divergence(self) -> None:
        """反向：放量+窄幅但 Delta 与 K 线同向 → 非吸收。"""
        bars = self._absorption_bars()
        res = verify_orderflow(
            bars_delta=[5.0, -10.0], cumulative_delta=-5.0,
            footprint=None, tick_size=0.25, bars=bars,
        )
        self.assertFalse(res.absorption)
        self.assertNotEqual(res.reversal_stage, "absorption")

    def test_absorption_negative_no_volume(self) -> None:
        """反向：窄幅+背离但未放量（不足前两根 1.3 倍）→ 非吸收。"""
        bars = self._absorption_bars(cur_vol=120.0)
        res = verify_orderflow(
            bars_delta=[-5.0, 10.0], cumulative_delta=5.0,
            footprint=None, tick_size=0.25, bars=bars,
        )
        self.assertFalse(res.absorption)

    def test_absorption_negative_wide_range(self) -> None:
        """反向：放量+背离但幅度未压缩（宽区间）→ 非吸收。"""
        bars = self._absorption_bars(cur_rng=1.2)
        res = verify_orderflow(
            bars_delta=[-5.0, 10.0], cumulative_delta=5.0,
            footprint=None, tick_size=0.25, bars=bars,
        )
        self.assertFalse(res.absorption)


class TestAnalyzerIntegration(unittest.TestCase):
    def test_analyze_returns_wa(self) -> None:
        from wkf.wyckoff.analyzer import analyze

        frame = _frame(n=60)
        wa = analyze(frame, va_pct=0.682, swing_window=40, footprint_threshold=2.0)
        self.assertIsNotNone(wa)
        self.assertEqual(wa.symbol, "GC1!")
        self.assertIn(wa.bias, ("long", "short", "neutral"))
        self.assertTrue(wa.trigger)
        self.assertTrue(wa.invalidation)
        # 关键价位字段可用性
        if wa.value_area is not None:
            self.assertGreater(wa.value_area.vah, 0)
            self.assertGreater(wa.value_area.val, 0)
            self.assertGreater(wa.value_area.vpoc, 0)

    def test_to_dict_and_render(self) -> None:
        from wkf.wyckoff.analyzer import analyze

        frame = _frame(n=60)
        wa = analyze(frame)
        d = wa.to_dict()
        self.assertEqual(d["symbol"], "GC1!")
        self.assertIn("background", d)
        self.assertIn("value_area", d)
        self.assertIn("trigger", d)
        text = wa.render_text()
        self.assertIn("WKF 威科夫分析", text)


if __name__ == "__main__":
    unittest.main()

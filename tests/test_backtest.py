"""回测模块单元测试（P1 真实胜率推演，只读统计）。

【改动点】P1 迭代：新增真实胜率/盈亏比/最大连亏/净值曲线/明细导出测试，
推演逻辑用注入 bars_map 的样本K线，结果与手算一致。
【涉及文件】tests/test_backtest.py
【验证方式】python -m unittest discover tests -v 全绿。
"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from wkf.backtest.archive import append_analysis_record, load_archive
from wkf.backtest.statistics import (
    compute_backtest,
    export_trades,
    render_summary_text,
    simulate_trade,
)
from wkf.data.base import KlineBar


def _mk_bars(
    ts_opens: list[int],
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[KlineBar]:
    """构造新→旧 K 线列表（输入顺序即新→旧，seq 从 1 起）。"""
    n = len(ts_opens)
    bars: list[KlineBar] = []
    for i, ts in enumerate(ts_opens):
        c = closes[i]
        h = highs[i] if highs else c + 1.0
        l = lows[i] if lows else c - 1.0
        bars.append(
            KlineBar(
                seq=n - i, ts_open=ts, open=c, high=h, low=l,
                close=c, volume=100.0, closed=True,
            )
        )
    return bars


class TestArchive(unittest.TestCase):
    def test_append_and_load(self) -> None:
        # 使用临时存档路径（不污染真实 output/）
        from wkf.backtest import archive as _arch

        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        tmp.close()
        orig = _arch.ARCHIVE_PATH
        _arch.ARCHIVE_PATH = Path(tmp.name)
        try:
            ok = append_analysis_record(
                analysis_time="2026-08-08 12:00:00",
                symbol="GC1!", timeframe="5m", bias="long",
                trigger="回踩 VA 上沿 4338.00 做多", invalidation="跌破 4330.00",
                price=4335.5, prob={"short": 20, "long": 70, "neutral": 10},
                ts_open=1_700_000_000_000,
            )
            self.assertTrue(ok)
            recs = load_archive()
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0]["symbol"], "GC1!")
            self.assertEqual(recs[0]["bias"], "long")
            self.assertEqual(recs[0]["prob"]["long"], 70)
            # P1 新字段：入场价/方向/时间戳
            self.assertEqual(recs[0]["entry_price"], 4335.5)
            self.assertEqual(recs[0]["direction"], "long")
            self.assertEqual(recs[0]["ts_open"], 1_700_000_000_000)
        finally:
            _arch.ARCHIVE_PATH = orig
            Path(tmp.name).unlink(missing_ok=True)


class TestSimulateTrade(unittest.TestCase):
    def test_long_win_on_breakout(self) -> None:
        """多头：后续K线突破入场价 → win，平仓价=突破K线收盘。"""
        bars = _mk_bars(
            ts_opens=[1000, 900, 800],
            closes=[100.0, 100.8, 100.2],
            highs=[100.5, 101.2, 100.4],
            lows=[99.8, 99.9, 99.7],
        )
        tr = simulate_trade(
            {"symbol": "GC1!", "timeframe": "5m", "bias": "long",
             "price": 100.0, "ts_open": 1000, "analysis_time": "t1"},
            bars, lookahead=10, stop_pct=0.005,
        )
        self.assertIsNotNone(tr)
        self.assertEqual(tr.outcome, "win")
        self.assertEqual(tr.exit_reason, "突破入场价")
        self.assertAlmostEqual(tr.pnl, 0.8, places=4)
        self.assertAlmostEqual(tr.max_favorable, 1.2, places=4)

    def test_long_stop_loss(self) -> None:
        """多头：后续K线触及预设止损（-0.5%）→ loss。"""
        bars = _mk_bars(
            ts_opens=[1000, 900, 800],
            closes=[100.0, 99.0, 99.8],
            highs=[100.5, 99.4, 100.1],
            lows=[99.8, 98.8, 99.0],
        )
        tr = simulate_trade(
            {"symbol": "GC1!", "timeframe": "5m", "bias": "long",
             "price": 100.0, "ts_open": 1000, "analysis_time": "t1"},
            bars, lookahead=10, stop_pct=0.005,
        )
        self.assertEqual(tr.outcome, "loss")
        self.assertEqual(tr.exit_reason, "触及止损")
        self.assertAlmostEqual(tr.pnl, -0.5, places=4)
        self.assertAlmostEqual(tr.stop_price, 99.5, places=4)

    def test_short_win(self) -> None:
        """空头：后续K线跌破入场价 → win。"""
        bars = _mk_bars(
            ts_opens=[1000, 900, 800],
            closes=[100.0, 99.2, 99.9],
            highs=[100.5, 100.2, 100.3],
            lows=[99.8, 98.5, 99.6],
        )
        tr = simulate_trade(
            {"symbol": "GC1!", "timeframe": "5m", "bias": "short",
             "price": 100.0, "ts_open": 1000, "analysis_time": "t1"},
            bars, lookahead=10, stop_pct=0.005,
        )
        self.assertEqual(tr.outcome, "win")
        self.assertAlmostEqual(tr.pnl, 0.8, places=4)

    def test_skip_when_no_ts(self) -> None:
        """旧记录缺 ts_open → 无法对齐推演，返回 None。"""
        bars = _mk_bars([1000], [100.0])
        tr = simulate_trade(
            {"symbol": "GC1!", "timeframe": "5m", "bias": "long", "price": 100.0},
            bars, lookahead=10, stop_pct=0.005,
        )
        self.assertIsNone(tr)


class TestBacktestStatistics(unittest.TestCase):
    def test_empty(self) -> None:
        s = compute_backtest([])
        self.assertEqual(s.total_records, 0)
        self.assertEqual(s.win_rate, 0.0)
        self.assertEqual(s.equity_curve, [])

    def test_statistics_with_bars_map(self) -> None:
        """三笔信号（赢/亏/赢）→ 胜率 66.67%、盈亏比 1.6、连亏 1、净值正确。"""
        bars = _mk_bars(
            ts_opens=[1000, 900, 800, 700, 600, 500],
            closes=[100.0, 100.8, 99.2, 99.8, 100.2, 99.9],
            highs=[100.5, 101.2, 100.2, 100.1, 100.4, 100.3],
            lows=[99.8, 99.9, 98.5, 99.0, 99.7, 99.6],
        )
        records = [
            {"symbol": "GC1!", "timeframe": "5m", "bias": "long", "price": 100.0,
             "ts_open": 1000, "analysis_time": "2026-08-08 10:00:00"},
            {"symbol": "GC1!", "timeframe": "5m", "bias": "long", "price": 100.0,
             "ts_open": 800, "analysis_time": "2026-08-08 10:05:00"},
            {"symbol": "GC1!", "timeframe": "5m", "bias": "short", "price": 100.0,
             "ts_open": 900, "analysis_time": "2026-08-08 10:10:00"},
        ]
        s = compute_backtest(
            records, lookahead=10, stop_pct=0.005,
            bars_map={("GC1!", "5m"): bars},
        )
        self.assertEqual(s.total_records, 3)
        self.assertEqual(s.evaluated_trades, 3)
        self.assertEqual(s.wins, 2)
        self.assertEqual(s.losses, 1)
        self.assertEqual(s.skipped, 0)
        self.assertAlmostEqual(s.win_rate, 66.67, places=2)
        self.assertAlmostEqual(s.avg_win, 0.8, places=4)
        self.assertAlmostEqual(s.avg_loss, -0.5, places=4)
        self.assertAlmostEqual(s.profit_factor, 1.6, places=2)
        self.assertEqual(s.max_consecutive_losses, 1)
        self.assertEqual(s.equity_curve, [0.8, 0.3, 1.1])
        self.assertAlmostEqual(s.total_pnl, 1.1, places=4)
        self.assertEqual(s.by_direction["long"], 2)
        self.assertEqual(s.by_direction["short"], 1)

    def test_old_records_skipped(self) -> None:
        """无 ts_open 的旧记录全部跳过，不计入胜率。"""
        s = compute_backtest(
            [
                {"symbol": "GC1!", "timeframe": "5m", "bias": "long",
                 "price": 100.0, "analysis_time": "t1"},
                {"symbol": "GC1!", "timeframe": "5m", "bias": "neutral",
                 "price": 100.0, "ts_open": 1000, "analysis_time": "t2"},
            ],
            bars_map={("GC1!", "5m"): _mk_bars([1000], [100.0])},
        )
        self.assertEqual(s.skipped, 2)
        self.assertEqual(s.evaluated_trades, 0)

    def test_render_text(self) -> None:
        s = compute_backtest([])
        txt = render_summary_text(s)
        self.assertIn("真实交易胜率", txt)
        self.assertIn("存档信号总数: 0", txt)

    def test_export_trades(self) -> None:
        """逐笔明细导出 CSV：表头 + N 行数据。"""
        bars = _mk_bars(
            ts_opens=[1000, 900],
            closes=[100.0, 100.8],
            highs=[100.5, 101.2],
            lows=[99.8, 99.9],
        )
        tr = simulate_trade(
            {"symbol": "GC1!", "timeframe": "5m", "bias": "long",
             "price": 100.0, "ts_open": 1000, "analysis_time": "t1"},
            bars, lookahead=10, stop_pct=0.005,
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
            tmp_path = tmp.name
        try:
            n = export_trades([tr], tmp_path)
            self.assertEqual(n, 1)
            with open(tmp_path, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "GC1!")
            self.assertEqual(rows[0]["outcome"], "win")
            self.assertEqual(rows[0]["exit_reason"], "突破入场价")
        finally:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

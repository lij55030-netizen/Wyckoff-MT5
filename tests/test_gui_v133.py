"""V1.3.3 迭代单元测试：时间戳体系 + YFinance 数据源 UI 切换。

覆盖：
  1. 决策面板头部固定「决策生成时间：YYYY-MM-DD HH:mm:ss」；
  2. 历史分析列表每条记录前置时间标签；
  3. 数据快照/诊断报告内备注当前数据源来源；
  4. 数据源下拉切换：更新设置、清空图表缓存、重建品种列表、底部状态栏更新。
【涉及文件】tests/test_gui_v133.py（新增）
【验证方式】QT_QPA_PLATFORM=offscreen python -m unittest tests.test_gui_v133 -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import wkf.config.settings as settings_mod  # noqa: E402
from wkf.data.base import IndicatorBundle, KlineBar, KlineFrame  # noqa: E402
from wkf.gui.main_window import MainWindow  # noqa: E402
from wkf.gui.widgets.decision_panel import DecisionPanel  # noqa: E402
from wkf.gui.widgets.diagnosis_panel import DiagnosisPanel  # noqa: E402
from wkf.gui.widgets.history_panel import HistoryPanel  # noqa: E402
from wkf.gui.widgets.snapshot_panel import SnapshotPanel  # noqa: E402
from wkf.gui.chart_widget import WkfChart  # noqa: E402
from wkf.wyckoff.analyzer import WyckoffAnalysis  # noqa: E402
from wkf.wyckoff.background import BackgroundResult  # noqa: E402


def _mk_frame(symbol: str = "GC1!", timeframe: str = "5m", n: int = 5) -> KlineFrame:
    bars: list[KlineBar] = []
    for i in range(n):
        bars.append(
            KlineBar(
                seq=n - i, ts_open=1_700_000_000_000 - i * 300_000,
                open=100.0 + i, high=101.0 + i, low=99.0 + i,
                close=100.5 + i, volume=100.0, closed=True,
            )
        )
    bars.reverse()
    ind = IndicatorBundle(
        ema20=tuple([100.0] * n), atr14=tuple([0.5] * n),
        rsi14=tuple([50.0] * n), bb_upper=tuple([101.0] * n),
        bb_middle=tuple([100.0] * n), bb_lower=tuple([99.0] * n),
        vwap=tuple([100.0] * n),
    )
    return KlineFrame(symbol=symbol, timeframe=timeframe, bars=tuple(bars), indicators=ind)


def _mk_wa() -> WyckoffAnalysis:
    return WyckoffAnalysis(
        symbol="GC1!", timeframe="5m", price=100.0,
        background=BackgroundResult("range", "neutral", 0, 0),
        value_area=None, orderflow=None, bias="neutral",
        trigger="等待：当前无明确入场信号", invalidation="价格行为否定本判断时放弃计划",
    )


class TestTimeStamps(unittest.TestCase):
    """时间戳体系：决策/历史/快照/诊断统一 YYYY-MM-DD HH:mm:ss 追加文本。"""

    def test_decision_panel_header_time(self) -> None:
        panel = DecisionPanel()
        html = panel._build_html(_mk_wa(), analysis_time="2026-08-08 10:00:00")
        self.assertIn("决策生成时间：", html)
        self.assertIn("2026-08-08 10:00:00", html)

    def test_decision_panel_time_fallback_when_empty(self) -> None:
        """仅获取数据（未提交分析）时 analysis_time 为空 → 自动取当前时间兜底。"""
        panel = DecisionPanel()
        html = panel._build_html(_mk_wa(), analysis_time="")
        self.assertIn("决策生成时间：", html)
        self.assertNotIn("决策生成时间：　", html)  # 时间值非空

    def test_history_line_time_prefix(self) -> None:
        panel = HistoryPanel()
        line = panel.append_history(
            "NQ1!", "15m", "long", time_str="2026-08-08 10:00:00", count=3
        )
        self.assertTrue(line.startswith("2026-08-08 10:00:00"), line)
        self.assertIn("NQ1!", line)

    def test_snapshot_notes_data_source(self) -> None:
        panel = SnapshotPanel()
        text = panel._build_text(_mk_frame(), _mk_wa(), data_source="YFinance公开数据源")
        self.assertIn("数据源:", text)
        self.assertIn("YFinance公开数据源", text)

    def test_diagnosis_first_line_time_and_source(self) -> None:
        panel = DiagnosisPanel()
        text = panel._build_text(
            _mk_wa(), generated_time="2026-08-08 10:00:00",
            data_source="MT5实盘数据源",
        )
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("🔍 诊断生成时间：2026-08-08 10:00:00"), lines[0])
        self.assertIn("MT5实盘数据源", lines[1])


class TestIndicatorHide(unittest.TestCase):
    """纯K线模式：隐藏 EMA/布林带/VWAP/VA/POC/Delta/RSI，仅保留蜡烛。"""

    def test_settings_default_true(self) -> None:
        from wkf.config.settings import GeneralSettings

        self.assertTrue(GeneralSettings().show_indicators)

    def test_indicator_dialog_has_switch(self) -> None:
        from wkf.config.settings import load_settings
        from wkf.gui.settings_dialogs import IndicatorDialog

        s = load_settings()
        dlg = IndicatorDialog(s)
        self.assertTrue(hasattr(dlg, "_show_indicators"))
        # 勾选状态应与当前配置一致（用户可能已自定义为纯K线）
        self.assertEqual(
            dlg._show_indicators.isChecked(), s.general.show_indicators
        )

    def test_pure_kline_hides_indicators(self) -> None:
        frame = _mk_frame(n=6)
        chart = WkfChart()
        # 显示指标模式：蜡烛(2n) + EMA/BB×3/VWAP 指标线
        chart.show_indicators = True
        chart.set_frame(frame)
        full_items = len(chart._items)
        self.assertGreater(full_items, 2 * len(frame.bars), "显示模式应含指标层")
        # 纯K线模式：仅蜡烛
        chart.show_indicators = False
        chart.set_frame(frame)
        self.assertEqual(len(chart._items), 2 * len(frame.bars), "纯K线只保留蜡烛")
        # RSI 副图已移除（V3.0），主图自动填满
        self.assertFalse(hasattr(chart, "_rsi_plot"), "RSI 副图组件应已移除")


class TestCrosshairMouseTracking(unittest.TestCase):
    """十字光标修复：viewport 鼠标追踪开启 + 移动事件后价格标签可见。"""

    def test_viewport_mouse_tracking_enabled(self) -> None:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        chart = WkfChart()
        self.assertTrue(chart._plot.viewport().hasMouseTracking())
        self.assertFalse(hasattr(chart, "_rsi_plot"), "RSI 副图组件应已移除")

    def test_crosshair_label_shows_price_on_move(self) -> None:
        """十字光标：十字线可见，数值标签显示光标位置价格。"""
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        chart = WkfChart()
        chart.resize(900, 600)
        chart.show()
        app.processEvents()
        chart.set_frame(_mk_frame(n=60))
        chart.set_crosshair_enabled(True)

        vp = chart._plot.viewport()
        local = QPointF(vp.width() / 2, vp.height() / 2)
        global_p = QPointF(vp.mapToGlobal(local.toPoint()))
        ev = QMouseEvent(
            QEvent.Type.MouseMove, local, global_p,
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        app.sendEvent(vp, ev)
        app.processEvents()
        self.assertTrue(chart._ch_vline.isVisible(), "十字线竖线应显示")
        self.assertTrue(chart._ch_hline.isVisible(), "十字线横线应显示")
        self.assertTrue(chart._ch_label.isVisible(), "十字光标价格标签应显示")
        self.assertIn("价格", chart._ch_label.toPlainText())


class TestDataSourceSwitch(unittest.TestCase):
    """YFinance 数据源 UI：切换清缓存 → 重建品种 → 状态栏更新。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        import wkf.orchestrator.runner as runner

        cls._orig_fetch = runner.fetch_frame_cached
        runner.fetch_frame_cached = lambda *a, **k: (None, None, "", False)
        cls._orig_first_run = MainWindow._first_run_setup
        cls._orig_check_mode = MainWindow._check_data_source_mode
        MainWindow._first_run_setup = lambda self: None
        MainWindow._check_data_source_mode = lambda self: None

    @classmethod
    def tearDownClass(cls) -> None:
        import wkf.orchestrator.runner as runner

        runner.fetch_frame_cached = cls._orig_fetch
        MainWindow._first_run_setup = cls._orig_first_run
        MainWindow._check_data_source_mode = cls._orig_check_mode

    def setUp(self) -> None:
        self._save_patcher = mock.patch.object(
            settings_mod, "save_settings", return_value=None
        )
        self._save_patcher.start()
        self.win = MainWindow()
        loop = QEventLoop()
        self.win._fetch_done.connect(lambda *_: loop.quit())
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        QApplication.processEvents()

    def tearDown(self) -> None:
        self.win.close()
        self.win.deleteLater()
        QApplication.processEvents()
        self._save_patcher.stop()

    def test_switch_to_yfinance(self) -> None:
        win = self.win
        win._frame_cache[("GC1!", "5m")] = (1.0, object(), None)
        fake_src = mock.Mock()
        fake_src.available_symbols.return_value = ["BTC-USD", "^GSPC"]
        with mock.patch(
            "wkf.data.datasource.get_data_source", return_value=fake_src
        ):
            win._ds_combo.setCurrentIndex(
                win._ds_combo.findData("yfinance")
            )
            QApplication.processEvents()
        self.assertEqual(win._settings.general.data_source, "yfinance")
        self.assertEqual(win._frame_cache, {}, "切换后应清空图表缓存")
        self.assertEqual(win._symbols, ["BTC-USD", "^GSPC"], "品种列表应切换到 yfinance 品种")
        self.assertIn(
            "YFinance公开数据源", win.statusBar().currentMessage(),
            "底部状态栏应展示当前数据源",
        )

    def test_switch_back_to_mt5(self) -> None:
        win = self.win
        # 先真实切到 yfinance，再切回 mt5（与 GUI 实际操作一致）
        with mock.patch(
            "wkf.data.datasource.get_data_source",
            return_value=mock.Mock(available_symbols=mock.Mock(return_value=["BTC-USD"])),
        ):
            win._ds_combo.setCurrentIndex(win._ds_combo.findData("yfinance"))
            QApplication.processEvents()
        self.assertEqual(win._settings.general.data_source, "yfinance")
        with mock.patch(
            "wkf.data.datasource.get_data_source",
            return_value=mock.Mock(available_symbols=mock.Mock(return_value=[])),
        ):
            win._ds_combo.setCurrentIndex(win._ds_combo.findData("mt5"))
            QApplication.processEvents()
        self.assertEqual(win._settings.general.data_source, "mt5")
        self.assertIn("MT5实盘数据源", win.statusBar().currentMessage())


if __name__ == "__main__":
    unittest.main()

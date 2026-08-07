"""GUI 异步加载迭代单元测试（核心优化1-4）。

覆盖：
  1. _prepare_switch 前置清理：清空图表 items、挂起 Tick 定时器、清空表格；
  2. 全局加载锁：_loading=True 时 _on_fetch_data 直接忽略，不启动新线程；
  3. 防抖节流：300ms 内连续切换只创建一次加载线程；
  4. 完成后恢复：_on_fetch_done 重启 Tick 定时器并恢复图表交互。
【涉及文件】tests/test_gui_switch.py（新增）
【验证方式】QT_QPA_PLATFORM=offscreen python -m unittest tests.test_gui_switch -v
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
from wkf.gui import main_window as mw_mod  # noqa: E402
from wkf.gui.main_window import MainWindow, TF_MINUTES, WINDOW_HOURS  # noqa: E402


class TestAsyncLoadSwitch(unittest.TestCase):
    """品种/周期异步切换：前置清理、加载锁、防抖、恢复。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        # 屏蔽真实数据拉取与弹窗/引导，保证测试确定性
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
        # 防止切换记忆落盘污染真实 settings.json
        self._save_patcher = mock.patch.object(
            settings_mod, "save_settings", return_value=None
        )
        self._save_patcher.start()
        self.win = MainWindow()
        self._wait_fetch()  # 等初始加载完成

    def tearDown(self) -> None:
        self.win.close()
        self.win.deleteLater()
        QApplication.processEvents()
        self._save_patcher.stop()

    def _wait_fetch(self, timeout_ms: int = 3000) -> None:
        loop = QEventLoop()
        self.win._fetch_done.connect(lambda *_: loop.quit())
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        QApplication.processEvents()

    def test_prepare_switch_cleans_up(self) -> None:
        """前置清理：图表 items 清空、Tick 定时器挂起、表格清空、状态提示。"""
        win = self.win
        win._tick_timer.start(2000)  # 模拟运行中的 Tick 轮询
        win._data_table.setRowCount(5)  # 模拟旧表格数据

        win._prepare_switch("NQ1!", "5m", is_symbol_change=True)

        self.assertEqual(len(win._chart._items), 0, "主图数据层应清空")
        self.assertFalse(win._tick_timer.isActive(), "Tick 定时器应挂起")
        self.assertEqual(win._data_table.rowCount(), 0, "K线表格应清空")
        self.assertIn("品种数据加载中", win._kline_status.text())
        self.assertTrue(win._chart._suspended, "图表交互应挂起")
        self.assertTrue(win._chart._frame is None, "旧数据帧应失效")

    def test_prepare_switch_timeframe_message(self) -> None:
        """周期切换使用「周期重构渲染中」提示文案。"""
        win = self.win
        win._prepare_switch("GC1!", "15m", is_symbol_change=False)
        self.assertIn("周期重构渲染中", win._kline_status.text())

    def test_loading_lock_ignores_duplicate_fetch(self) -> None:
        """全局加载锁：加载中 _on_fetch_data 直接忽略，不启动新线程。"""
        win = self.win
        win._loading = True
        seq_before = win._fetch_seq
        win._on_fetch_data()
        self.assertEqual(win._fetch_seq, seq_before, "加载中不应递增请求序号")
        win._loading = False

    def test_debounce_only_last_request(self) -> None:
        """防抖节流：300ms 内连续切换只创建一次加载线程。"""
        win = self.win
        win._prepare_switch("GC1!", "5m", is_symbol_change=True)  # 清掉初始状态
        with mock.patch.object(mw_mod, "_FetchThread") as mock_thread:
            # 快速连续切换（防抖窗口内）
            win._sym_combo.setCurrentText("NQ1!")
            win._tf_combo.setCurrentIndex(win._tf_combo.findData("15m"))
            win._sym_combo.setCurrentText("ES1!")
            win._tf_combo.setCurrentIndex(win._tf_combo.findData("30m"))
            win._sym_combo.setCurrentText("GC1!")
            win._tf_combo.setCurrentIndex(win._tf_combo.findData("5m"))
            self.assertTrue(win._debounce_timer.isActive(), "防抖定时器应激活")
            QApplication.processEvents()
            # 等防抖触发（300ms）+ 缓冲
            loop = QEventLoop()
            QTimer.singleShot(600, loop.quit)
            loop.exec()
            QApplication.processEvents()
        self.assertEqual(
            mock_thread.call_count, 1,
            f"快速连切应只发一次请求，实际 {mock_thread.call_count} 次",
        )

    def test_fetch_done_restores_features(self) -> None:
        """完成后恢复：加载锁释放、Tick 定时器重启、图表交互恢复。"""
        win = self.win
        win._loading = True
        win._tick_timer.stop()
        win._chart.suspend_interactions()
        seq = win._fetch_seq

        win._on_fetch_done(None, None, "", seq)

        self.assertFalse(win._loading)
        self.assertTrue(win._tick_timer.isActive(), "MT5 模式完成后应重启 Tick 轮询")
        self.assertFalse(win._chart._suspended, "图表交互应恢复")

    def test_loading_switch_records_pending(self) -> None:
        """加载中切换：不排队，仅记录最后一次意图，完成后自动补发。"""
        win = self.win
        win._prepare_switch("GC1!", "5m", is_symbol_change=True)
        win._loading = True
        win._sym_combo.setCurrentText("NQ1!")  # 触发 _on_selector_changed
        QApplication.processEvents()
        self.assertEqual(win._pending_switch, ("NQ1!", win._current_tf()))
        # 模拟加载完成 → pending 补发
        win._loading = False
        win._fetch_seq += 1
        win._on_fetch_done(None, None, "", win._fetch_seq)
        self.assertIsNone(win._pending_switch)


if __name__ == "__main__":
    unittest.main()

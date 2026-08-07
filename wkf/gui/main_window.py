"""WKF 主窗口：图表 + 控制 + 分析结果面板。"""
from __future__ import annotations

import datetime
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QMetaObject, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from wkf.config.settings import load_settings
from wkf.data.base import KlineFrame
from wkf.gui.chart_widget import WkfChart
from wkf.gui.settings_dialogs import AIModelDialog, FeishuDialog, IndicatorDialog
from wkf.orchestrator.runner import (
    fetch_frame_only,
    get_latest_bar_ts,
    run_analysis,
)

SYMBOLS = ["NQ1!", "ES1!", "GC1!"]
TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]
TF_MINUTES = {"5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WKF · 威科夫交易智能体")
        self.resize(1200, 760)

        self._settings = load_settings()

        # ── 菜单栏 ─────────────────────────────────────────────────────────
        menubar = self.menuBar()

        settings_menu = menubar.addMenu("⚙ 设置")
        settings_menu.addAction("🤖 AI 模型设置", self._open_ai_dialog)
        settings_menu.addAction("📮 飞书发送消息通知设置", self._open_feishu_dialog)
        settings_menu.addAction("📐 其他设置（指标参数）", self._open_indicator_dialog)

        about_menu = menubar.addMenu("ℹ 关于")
        about_menu.addAction("关于 WKF", self._show_about)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ── 控制栏 ─────────────────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("品种:"))
        self._sym_combo = QComboBox()
        self._sym_combo.addItems(SYMBOLS)
        ctrl.addWidget(self._sym_combo)

        ctrl.addWidget(QLabel("周期:"))
        self._tf_combo = QComboBox()
        self._tf_combo.addItems(TIMEFRAMES)
        self._tf_combo.setCurrentText("15m")
        ctrl.addWidget(self._tf_combo)

        self._fetch_btn = QPushButton("🔄 获取数据")
        self._fetch_btn.clicked.connect(self._on_fetch_data)
        ctrl.addWidget(self._fetch_btn)

        self._analyze_btn = QPushButton("▶ 分析")
        self._analyze_btn.clicked.connect(self._on_analyze)
        ctrl.addWidget(self._analyze_btn)

        self._auto_check = QCheckBox("⏱ 等待新K线收盘后自动分析")
        self._auto_check.setToolTip(
            "开启后自动轮询 MT5，检测到新 K 线收盘即自动提交完整分析（含 AI）"
        )
        self._auto_check.toggled.connect(self._on_auto_toggle)
        ctrl.addWidget(self._auto_check)

        self._kline_status = QLabel("K线: --")
        self._kline_status.setStyleSheet("color:#8b949e;font-size:12px")
        ctrl.addWidget(self._kline_status)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        # ── 图表 + 结果 ────────────────────────────────────────────────────
        split = QSplitter(Qt.Orientation.Vertical)
        self._chart = WkfChart()
        split.addWidget(self._chart)

        self._result = QPlainTextEdit()
        self._result.setReadOnly(True)
        self._result.setMaximumBlockCount(2000)
        split.addWidget(self._result)
        split.setSizes([500, 220])
        root.addWidget(split, stretch=1)

        # ── 自动分析状态 ───────────────────────────────────────────────────
        self._auto_active = False
        self._last_bar_ts = 0
        self._analysis_busy = False
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_check_kline)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_kline_status)
        self._status_timer.start(5000)

        # 启动后立即拉一次数据 + 状态
        self._on_fetch_data()

    def _open_ai_dialog(self) -> None:
        dlg = AIModelDialog(self._settings, self)
        if dlg.exec() and self._ui_alive():
            self._settings = load_settings()

    def _open_feishu_dialog(self) -> None:
        dlg = FeishuDialog(self._settings, self)
        if dlg.exec() and self._ui_alive():
            self._settings = load_settings()

    def _open_indicator_dialog(self) -> None:
        dlg = IndicatorDialog(self._settings, self)
        if dlg.exec() and self._ui_alive():
            self._settings = load_settings()

    def _ui_alive(self) -> bool:
        return self.isVisible() and self.isEnabled()

    def _show_about(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.about(
            self,
            "关于 WKF",
            "<h3>WKF · 威科夫交易智能体</h3>"
            "<p>三层威科夫量化分析：背景判定 → 价值区域 → 订单流验证</p>"
            "<p>支持 MT5 多周期（5m/10m/15m/30m/1h）× 多品种（NQ/ES/XAU）</p>"
            "<p>AI 增强诊断（DeepSeek）+ 飞书指令机器人 + 新K线自动分析</p>"
            "<p>仅供学习研究，不构成投资建议。</p>",
        )

    # ── 获取数据（不跑 AI，快速刷新图表）─────────────────────────────────
    def _on_fetch_data(self) -> None:
        symbol = self._sym_combo.currentText()
        timeframe = self._tf_combo.currentText()
        self._fetch_btn.setEnabled(False)
        self._result.setPlainText(f"⏳ 获取 {symbol} {timeframe} 数据...")

        def _work() -> None:
            frame, wa, err = fetch_frame_only(
                symbol, timeframe, settings=self._settings
            )

            def _update() -> None:
                self._fetch_btn.setEnabled(True)
                if err:
                    self._result.setPlainText(f"❌ 获取失败: {err}")
                    return
                if frame is not None:
                    self._chart.set_frame(frame)
                # 记录最新 bar 时间戳（自动分析基准）
                if frame is not None and frame.bars:
                    self._last_bar_ts = frame.bars[0].ts_open
                if wa is not None:
                    self._result.setPlainText(
                        "✅ 数据已更新（未跑 AI）\n\n" + wa.render_text()
                    )

            QMetaObject.invokeMethod(self, _update, Qt.ConnectionType.QueuedConnection)

        threading.Thread(target=_work, name="wkf-fetch", daemon=True).start()

    def _on_analyze(self) -> None:
        symbol = self._sym_combo.currentText()
        timeframe = self._tf_combo.currentText()
        self._analyze_btn.setEnabled(False)
        self._result.setPlainText(f"⏳ 正在分析 {symbol} {timeframe} ...")

        def _work() -> None:
            res = run_analysis(symbol, timeframe, settings=self._settings, with_ai=True)
            report = res.to_report()

            def _update() -> None:
                self._analyze_btn.setEnabled(True)
                self._result.setPlainText(report)
                if res.frame is not None:
                    self._chart.set_frame(res.frame)
                    self._last_bar_ts = res.frame.bars[0].ts_open
                self._analysis_busy = False

            QMetaObject.invokeMethod(self, _update, Qt.ConnectionType.QueuedConnection)

        self._analysis_busy = True
        threading.Thread(target=_work, name="wkf-analysis", daemon=True).start()

    # ── 自动分析：等待新 K 线收盘后自动提交 ───────────────────────────────
    def _on_auto_toggle(self, checked: bool) -> None:
        self._auto_active = checked
        if checked:
            # 开启时记录当前 bar 作为基准，避免立即重复分析
            symbol = self._sym_combo.currentText()
            timeframe = self._tf_combo.currentText()
            ts = get_latest_bar_ts(symbol, timeframe)
            if ts > 0:
                self._last_bar_ts = ts
            self._auto_timer.start(3000)  # 每 3 秒轮询
            self._kline_status.setText("⏱ 自动分析已开启，等待新K线收盘...")
        else:
            self._auto_timer.stop()
            self._kline_status.setText("K线: --")

    def _auto_check_kline(self) -> None:
        """轮询 MT5：检测到新 K 线收盘 → 自动提交分析。"""
        if self._analysis_busy:
            return
        symbol = self._sym_combo.currentText()
        timeframe = self._tf_combo.currentText()
        ts = get_latest_bar_ts(symbol, timeframe)
        if ts <= 0:
            return
        if self._last_bar_ts > 0 and ts != self._last_bar_ts:
            # 新 K 线收盘！
            self._last_bar_ts = ts
            self._kline_status.setText(f"🆕 新K线收盘 ({timeframe})，自动分析中...")
            self._on_analyze()
        else:
            # 更新剩余时间显示
            self._update_kline_status()

    def _update_kline_status(self) -> None:
        if self._analysis_busy:
            return
        symbol = self._sym_combo.currentText()
        timeframe = self._tf_combo.currentText()
        ts = get_latest_bar_ts(symbol, timeframe)
        if ts <= 0:
            return
        minutes = TF_MINUTES.get(timeframe, 15)
        close_at = ts + minutes * 60 * 1000
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        remain_s = max(0, (close_at - now_ms) // 1000)
        remain = f"{remain_s // 60}分{remain_s % 60}秒"
        if self._auto_active:
            self._kline_status.setText(
                f"⏱ 自动分析中 · 当前K线 {remain} 后收盘"
            )
        else:
            self._kline_status.setText(
                f"K线: {datetime.datetime.fromtimestamp(ts / 1000).strftime('%H:%M')} 收盘 · 下一根 {remain} 后"
            )


def main() -> int:
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("WKF")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

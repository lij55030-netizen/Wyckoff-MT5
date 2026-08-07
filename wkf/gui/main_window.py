"""WKF 主窗口：图表 + 控制 + 分析结果面板。"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
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
from wkf.orchestrator.runner import run_analysis

SYMBOLS = ["NQ1!", "ES1!", "GC1!"]
TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]


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

        self._analyze_btn = QPushButton("▶ 分析")
        self._analyze_btn.clicked.connect(self._on_analyze)
        ctrl.addWidget(self._analyze_btn)
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
            "<p>AI 增强诊断（DeepSeek）+ 飞书指令机器人</p>"
            "<p>仅供学习研究，不构成投资建议。</p>",
        )

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

            from PyQt6.QtCore import QMetaObject, Qt as _Qt

            QMetaObject.invokeMethod(self, _update, _Qt.ConnectionType.QueuedConnection)

        threading.Thread(target=_work, name="wkf-analysis", daemon=True).start()


def main() -> int:
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("WKF")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

"""WKF 主窗口：图表 + 控制 + 分析结果面板（数据/快照/诊断/决策/问AI）。"""
from __future__ import annotations

import datetime
import html
import math
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wkf.config.settings import load_settings
from wkf.data.base import KlineFrame
from wkf.gui.chart_widget import WkfChart
from wkf.gui.settings_dialogs import AIModelDialog, FeishuDialog, IndicatorDialog
from wkf.data.mt5_source import resolve_mt5_symbol
from wkf.orchestrator.runner import (
    AnalysisResult,
    fetch_frame_only,
    get_latest_bar_ts,
    run_analysis,
)

SYMBOLS = ["NQ1!", "ES1!", "GC1!"]
TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]
TF_MINUTES = {"5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}
# 图表默认时间级别：48 小时窗口（切换品种/周期后始终保持该窗口）
WINDOW_HOURS = 48


class _KlineTableWidget(QWidget):
    """数据标签页容器：顶部状态行 + K线明细表格（UI 展示优化版）。

    仅做前端展示渲染，不涉及任何行情数据/指标计算/业务逻辑。
    提供 toPlainText() 兼容方法，保持原纯文本表格的外部读取语义。
    """

    _HEADERS = ["#", "时间", "开", "高", "低", "收", "涨跌", "量", "RSI", "VWAP", "Δ"]
    _WIDTHS = [40, 108, 62, 62, 62, 62, 52, 70, 66, 84, 58]  # 固定列宽

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#8b949e;font-size:12px;")
        layout.addWidget(self.status_label)
        self.table = QTableWidget()
        self.table.setColumnCount(len(self._HEADERS))
        self.table.setHorizontalHeaderLabels(self._HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)  # 斑马线
        self.table.setShowGrid(False)
        # 表头加深底色 + 斑马线浅底色 + 全局配色（绿涨红跌）
        self.table.setStyleSheet(
            "QTableWidget{background-color:#0f1419;color:#e6edf3;"
            "alternate-background-color:#161d26;font-size:12px;border:1px solid #2a3442;}"
            "QTableWidget::item{padding:2px 6px;}"
            "QHeaderView::section{background-color:#1e2632;color:#8b949e;"
            "border:1px solid #2a3442;padding:4px 8px;font-weight:bold;font-size:12px;}"
        )
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)  # 固定列宽
        for i, w in enumerate(self._WIDTHS):
            self.table.setColumnWidth(i, w)
        layout.addWidget(self.table)

    def toPlainText(self) -> str:
        """兼容方法：返回表格文本（供测试/外部读取，保持原文本表格语义）。"""
        lines = [self.status_label.text()]
        lines.append("序号 | 时间 | 开盘 | 最高 | 最低 | 收盘 | 涨跌 | 成交量 | RSI | VWAP | Δ")
        for r in range(self.table.rowCount()):
            row = [
                self.table.item(r, c).text() if self.table.item(r, c) else ""
                for c in range(self.table.columnCount())
            ]
            lines.append(" | ".join(row))
        return "\n".join(lines)


class _AiChatWidget(QWidget):
    """问AI标签页：上层对话展示区 + 底部输入框/发送按钮（深色样式）。

    仅负责 UI 展示与输入；提问逻辑由 MainWindow._on_ai_send 处理。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # 上层：对话展示区（只读富文本）
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet(
            "QTextEdit{background-color:#0f1419;color:#e6edf3;"
            "border:1px solid #2a3442;border-radius:6px;font-size:13px;}"
        )
        layout.addWidget(self.view, stretch=1)

        # 底部：输入框 + 发送按钮（适配深色样式）
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入问题，回车发送（基于当前分析结果提问）...")
        self.input.setStyleSheet(
            "QLineEdit{background-color:#1e2632;color:#e6edf3;"
            "border:1px solid #2a3442;border-radius:6px;padding:7px 10px;font-size:13px;}"
            "QLineEdit:focus{border-color:#3b82f6;}"
        )
        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet(
            "QPushButton{background-color:#3b82f6;color:#fff;border:none;"
            "border-radius:6px;padding:7px 18px;font-size:13px;font-weight:bold;}"
            "QPushButton:hover{background-color:#2563eb;}"
            "QPushButton:disabled{background-color:#334155;}"
        )
        input_row.addWidget(self.input, stretch=1)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

    def append_user(self, text: str) -> None:
        self.view.append(
            f"<p style='margin:4px 0'><b style='color:#3b82f6'>你：</b>"
            f"<span style='color:#e6edf3'>{html.escape(text)}</span></p>"
        )

    def append_ai(self, body_html: str) -> None:
        self.view.append(
            f"<p style='margin:4px 0'><b style='color:#a78bfa'>AI：</b>{body_html}</p>"
        )

    def append_error(self, text: str) -> None:
        self.view.append(
            f"<p style='margin:4px 0'><b style='color:#ef4444'>⚠ {html.escape(text)}</b></p>"
        )

    def update_last_ai(self, body_html: str) -> None:
        """把最后一条 AI 消息替换为正式回复（"思考中…"占位原地更新）。"""
        from PyQt6.QtGui import QTextCursor

        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        cursor.insertHtml(
            f"<p style='margin:4px 0'><b style='color:#a78bfa'>AI：</b>{body_html}</p>"
        )
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def show_analysis(self, plain_text: str) -> None:
        """分析完成后：清空对话区并展示本次分析摘要（作为首条上下文）。"""
        self.view.clear()
        self.view.setPlainText(plain_text)

    def append_log(self, title: str, body_plain: str) -> None:
        """追加一条分析日志（提交分析联动：完整推理过程 + Token 消耗）。"""
        body_html = html.escape(body_plain).replace("\n", "<br>")
        self.view.append(
            f"<p style='margin:8px 0 2px;border-top:1px solid #2a3442;padding-top:6px'>"
            f"<b style='color:#f59e0b'>📋 {html.escape(title)}</b></p>"
            f"<div style='color:#e6edf3'>{body_html}</div>"
        )
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def toPlainText(self) -> str:
        return self.view.toPlainText()


class MainWindow(QMainWindow):
    # 工作线程 → UI 线程信号（PyQt6 线程安全回调）
    _fetch_done = pyqtSignal(object, object, str)  # frame, wyckoff, err
    _analysis_done = pyqtSignal(object)  # AnalysisResult
    _ai_reply = pyqtSignal(str)  # 问AI对话回复（工作线程 → UI 线程）
    _tick_updated = pyqtSignal(float)  # 最新成交价 tick 到达（工作线程 → UI 线程）

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WKF · 威科夫交易智能体")
        self.resize(1280, 800)

        self._settings = load_settings()
        self._fetch_done.connect(self._on_fetch_done)
        self._analysis_done.connect(self._on_analysis_done)


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

        # 品种/周期变更 → 自动刷新图表（带 300ms 防抖，快速连续切换只发最后一次请求）
        # 关键修复：之前下拉框未连接任何信号，切换品种后图表从不刷新
        self._sym_combo.currentIndexChanged.connect(self._on_selector_changed)
        self._tf_combo.currentIndexChanged.connect(self._on_selector_changed)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._on_fetch_data)

        self._fetch_btn = QPushButton("🔄 获取数据")
        self._fetch_btn.clicked.connect(self._on_fetch_data)
        ctrl.addWidget(self._fetch_btn)

        self._analyze_btn = QPushButton("📝 提交分析")
        self._analyze_btn.clicked.connect(self._on_analyze)
        ctrl.addWidget(self._analyze_btn)

        self._auto_check = QCheckBox("♾ 持续跟踪分析")
        self._auto_check.setToolTip(
            "开启后自动轮询 MT5，检测到新 K 线收盘即自动重新提交完整分析（含 AI），"
            "持续跟踪最新行情；每次结果自动加入左侧历史记录"
        )
        self._auto_check.toggled.connect(self._on_auto_toggle)
        ctrl.addWidget(self._auto_check)

        # 十字光标工具：可点击开关，激活后十字线跟随鼠标吸附最近K线显示 OHLC+时间戳
        self._crosshair_btn = QPushButton("➕ 十字光标")
        self._crosshair_btn.setCheckable(True)  # 可点击开关：点击激活/再点关闭
        self._crosshair_btn.setToolTip(
            "开启/关闭十字线光标：激活后鼠标在图表区移动自动吸附最近K线，"
            "显示该K线的开/高/低/收与时间戳；离开图表区域自动隐藏"
        )
        self._crosshair_btn.toggled.connect(self._on_crosshair_toggle)
        ctrl.addWidget(self._crosshair_btn)

        self._kline_status = QLabel("K线: --")
        self._kline_status.setStyleSheet("color:#8b949e;font-size:12px")
        ctrl.addWidget(self._kline_status)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        # ── 图表 + 分析结果面板（历史 + 标签页）────────────────────────────
        split = QSplitter(Qt.Orientation.Vertical)
        self._chart = WkfChart()
        split.addWidget(self._chart)

        # 结果区：左侧历史记录列表 + 右侧标签页（数据/快照/诊断/决策/问AI）
        result_split = QSplitter(Qt.Orientation.Horizontal)

        history_panel = QWidget()
        hist_layout = QVBoxLayout(history_panel)
        hist_layout.setContentsMargins(0, 0, 0, 0)
        hist_layout.addWidget(QLabel("📋 分析历史"))
        self._history_list = QPlainTextEdit()
        self._history_list.setReadOnly(True)
        self._history_list.setMaximumBlockCount(500)
        self._history_list.setFixedWidth(170)
        hist_layout.addWidget(self._history_list)
        result_split.addWidget(history_panel)

        # 5 个标签页
        tabs = QTabWidget()
        # 数据标签页：状态行 + K线明细表格（UI 展示优化，_KlineTableWidget 自带 toPlainText 兼容）
        self._tab_data = _KlineTableWidget()
        self._table_status = self._tab_data.status_label
        self._data_table = self._tab_data.table
        tabs.addTab(self._tab_data, "📊 数据")

        self._tab_snapshot = QPlainTextEdit()
        self._tab_snapshot.setReadOnly(True)
        self._tab_snapshot.setMaximumBlockCount(2000)
        tabs.addTab(self._tab_snapshot, "📸 快照")

        self._tab_diagnosis = QPlainTextEdit()
        self._tab_diagnosis.setReadOnly(True)
        self._tab_diagnosis.setMaximumBlockCount(2000)
        tabs.addTab(self._tab_diagnosis, "🔍 诊断")

        self._tab_decision = QTextEdit()  # 决策页：富文本（红色粗体核心结论）
        self._tab_decision.setReadOnly(True)
        self._tab_decision.setStyleSheet(
            "QTextEdit{background-color:#0f1419;color:#e6edf3;border:none;font-size:13px;}"
        )
        tabs.addTab(self._tab_decision, "🎯 决策")

        # 问AI页：对话容器（上层展示区 + 底部输入框/发送按钮，回车发送）
        self._tab_ai = _AiChatWidget()
        self._tab_ai.input.returnPressed.connect(self._on_ai_send)
        self._tab_ai.send_btn.clicked.connect(self._on_ai_send)
        tabs.addTab(self._tab_ai, "🤖 问AI")

        result_split.addWidget(tabs)
        result_split.setSizes([170, 630])

        split.addWidget(result_split)
        split.setSizes([500, 220])
        root.addWidget(split, stretch=1)

        # 兼容旧引用
        self._result = self._tab_diagnosis

        # ── 自动分析状态 ───────────────────────────────────────────────────
        self._auto_active = False
        self._last_bar_ts = 0
        self._analysis_busy = False
        self._history_count = 0
        self._has_ai_result = False
        # 问AI对话状态
        self._ai_busy = False
        self._ai_reply.connect(self._on_ai_reply)
        # 最近一次分析结果（供问AI追问上下文）
        self._last_frame = None
        self._last_wa = None
        self._last_res = None
        # 请求令牌：记录最近一次 fetch/analyze 请求对应的品种+周期，
        # 响应返回时若用户已切换，则丢弃过期结果，防止旧品种数据覆盖新图表
        self._fetch_req = ("", "")
        # K线收盘倒计时：1 秒定时器秒级实时刷新；MT5 时间戳每 5 秒校准一次（避免高频连接）
        # 服务器时钟偏移：MT5 bar/tick 时间基于服务器时钟（实测比真实 UTC 快 3 小时），
        # 与 time.time()（真实 UTC）不同基准，须测量偏移后对齐，否则倒计时偏差数小时
        self._server_offset_ms = 0
        self._status_ts = 0
        self._status_ts_fetched_at = 0.0
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_check_kline)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_kline_status)
        self._status_timer.start(1000)  # 1 秒定时器：秒级实时倒计时

        # ── 实时价格标注：每 2 秒后台轮询 MT5 最新 tick 价，更新图表红线 ──
        self._tick_updated.connect(self._on_tick_updated)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._poll_tick)
        self._tick_timer.start(2000)

        # 启动后立即拉一次数据 + 状态
        self._on_fetch_data()

    def closeEvent(self, event) -> None:
        """关闭窗口：停止定时器与后台线程，避免进程残留。"""
        self._tick_timer.stop()
        self._status_timer.stop()
        self._auto_timer.stop()
        super().closeEvent(event)

    # ── 48 小时时间级别：按周期换算需要拉取的K线根数 ─────────────────────
    def _window_bar_count(self, timeframe: str) -> int:
        """返回 48 小时窗口对应的K线根数（含用户自定义根数下限）。"""
        minutes = TF_MINUTES.get(timeframe, 15)
        base = WINDOW_HOURS * 60 // minutes  # 48h 对应根数
        # 若用户在「其他设置」调大了K线数量则尊重用户配置（显示更多）
        return max(base, getattr(self._settings.general, "analysis_bar_count", 48))

    # ── 十字光标工具：按钮开关（独立功能，不干扰拖拽/缩放/点击）───────────
    def _on_crosshair_toggle(self, checked: bool) -> None:
        """十字光标按钮点击：激活/关闭，带按钮视觉反馈。"""
        self._chart.set_crosshair_enabled(checked)
        if checked:
            # 激活状态：按钮高亮 + 文字变关闭提示
            self._crosshair_btn.setText("⛔ 关闭光标")
            self._crosshair_btn.setStyleSheet(
                "QPushButton{background-color:#1e3a5f;color:#e6edf3;"
                "border:1px solid #3b82f6;border-radius:4px;padding:4px 10px;}"
            )
        else:
            # 关闭状态：恢复默认样式（默认隐藏，不加载任何光标状态）
            self._crosshair_btn.setText("➕ 十字光标")
            self._crosshair_btn.setStyleSheet("")
        self._kline_status.setText(f"十字光标: {'已开启' if checked else '已关闭'}")

    # ── 实时价格标注：后台轮询 MT5 tick，更新图表红线 ─────────────────────
    def _poll_tick(self) -> None:
        """每 2 秒触发：后台线程取当前品种最新 tick 价（不阻塞 UI）。"""
        if not self._chart._frame:  # 图表尚未加载数据则跳过，减少空转
            return
        symbol = self._sym_combo.currentText()
        timeframe = self._tf_combo.currentText()
        sym, tf = symbol, timeframe

        def _work() -> None:
            try:
                import MetaTrader5 as mt5

                if not mt5.initialize():
                    return
                try:
                    mt5_sym = resolve_mt5_symbol(sym)
                    tick = mt5.symbol_info_tick(mt5_sym)
                    if tick is None:
                        return
                    # 最新成交价：优先 last（真实成交价），无 last 用买卖中间价
                    price = tick.last if tick.last > 0 else (tick.bid + tick.ask) / 2.0
                    if price > 0:
                        self._tick_updated.emit(price)
                finally:
                    mt5.shutdown()
            except Exception:
                return  # 网络/数据瞬时异常静默跳过，下一轮重试

        threading.Thread(target=_work, name="wkf-tick", daemon=True).start()

    def _on_tick_updated(self, price: float) -> None:
        """最新成交价到达（主线程）：更新图表红线与标签。"""
        self._chart.set_last_price(price)

    def _on_selector_changed(self) -> None:
        """品种/周期变更：显示加载状态并防抖触发刷新。"""
        sym = self._sym_combo.currentText()
        tf = self._tf_combo.currentText()
        self._has_ai_result = False  # 新品种数据，旧 AI 结果作废
        self._kline_status.setText(f"⏳ 切换中，加载 {sym} {tf} ...")
        self._set_table_status(f"⏳ 正在加载 {sym} {tf}（48小时窗口）...")
        self._data_table.setRowCount(0)
        self._debounce_timer.start()

    def _append_history(self, symbol: str, timeframe: str, bias: str, report: str) -> None:
        """把一次分析结果加入历史记录面板（方向文案汉化：long→多头等）。"""
        import datetime

        bias_zh = {"long": "多头", "short": "空头", "neutral": "中性"}.get(bias, bias)
        self._history_count += 1
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{self._history_count}] {ts} {symbol} {timeframe}"
        if bias_zh:
            line += f" → {bias_zh}"
        self._history_list.appendPlainText(line)
        self._history_list.verticalScrollBar().setValue(
            self._history_list.verticalScrollBar().maximum()
        )

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
        self._fetch_req = (symbol, timeframe)  # 记录请求令牌
        self._fetch_btn.setEnabled(False)
        bar_count = self._window_bar_count(timeframe)
        self._set_table_status(
            f"⏳ 获取 {symbol} {timeframe} 数据（{WINDOW_HOURS}h 窗口，{bar_count} 根）..."
        )

        def _work() -> None:
            frame, wa, err = fetch_frame_only(
                symbol, timeframe, bar_count=bar_count, settings=self._settings
            )
            self._fetch_done.emit(frame, wa, err)

        threading.Thread(target=_work, name="wkf-fetch", daemon=True).start()

    def _on_fetch_done(self, frame, wa, err: str) -> None:
        """获取数据完成（主线程）。"""
        self._fetch_btn.setEnabled(True)
        # 防竞态：用户已切换品种/周期则丢弃过期响应
        if self._fetch_req != (self._sym_combo.currentText(), self._tf_combo.currentText()):
            return
        if err:
            self._set_table_status(f"❌ 获取失败: {err}")
            self._data_table.setRowCount(0)
            self._kline_status.setText(f"❌ 获取失败: {err[:60]}")
            return
        if frame is not None:
            self._chart.set_frame(frame)
            self._last_bar_ts = frame.bars[0].ts_open
        # 仅当尚无 AI 分析结果时才填充各页，避免覆盖已完成的 AI 诊断
        if frame is not None and not getattr(self, "_has_ai_result", False):
            self._populate_tabs(frame, wa, None)
            hours = WINDOW_HOURS
            self._set_table_status(
                f"✅ 分析数据已更新（{frame.symbol} {frame.timeframe} · {hours}h 窗口 · {len(frame.bars)} 根K线）"
            )
        if frame is not None:
            latest_ts = datetime.datetime.fromtimestamp(frame.bars[0].ts_open / 1000).strftime("%H:%M")
            self._kline_status.setText(f"K线: {latest_ts} 收盘 · {WINDOW_HOURS}h 窗口 · {len(frame.bars)} 根")

    def _on_analyze(self) -> None:
        symbol = self._sym_combo.currentText()
        timeframe = self._tf_combo.currentText()
        self._fetch_req = (symbol, timeframe)  # 分析同样更新令牌
        self._analyze_btn.setEnabled(False)
        bar_count = self._window_bar_count(timeframe)
        self._set_table_status(f"⏳ 正在分析 {symbol} {timeframe}（{WINDOW_HOURS}h 窗口）...")
        self._data_table.setRowCount(0)

        def _work() -> None:
            res = run_analysis(
                symbol, timeframe, bar_count=bar_count,
                settings=self._settings, with_ai=True,
            )
            self._analysis_done.emit(res)

        self._analysis_busy = True
        threading.Thread(target=_work, name="wkf-analysis", daemon=True).start()

    def _on_analysis_done(self, res: AnalysisResult) -> None:
        """分析完成（主线程）。"""
        self._analyze_btn.setEnabled(True)
        self._analysis_busy = False
        # 防竞态：分析期间用户切了品种/周期 → 丢弃过期结果
        if self._fetch_req != (self._sym_combo.currentText(), self._tf_combo.currentText()):
            return
        self._has_ai_result = True
        if res.error:
            self._set_table_status(f"❌ 分析失败: {res.error}")
            self._data_table.setRowCount(0)
            return
        if res.frame is not None:
            self._chart.set_frame(res.frame)
            self._last_bar_ts = res.frame.bars[0].ts_open
        # 保存最近分析结果（供问AI标签页追问上下文）
        self._last_frame = res.frame
        self._last_wa = res.wyckoff
        self._last_res = res
        # 填充 5 个标签页
        self._populate_tabs(res.frame, res.wyckoff, res)
        # 历史记录
        bias = res.wyckoff.bias if res.wyckoff is not None else ""
        self._append_history(res.symbol, res.timeframe, bias, res.to_report())

    # ── K线明细表格：UI 展示优化（仅前端渲染，不改任何数据/业务逻辑）─────
    def _set_table_status(self, text: str) -> None:
        """数据标签页顶部状态行。"""
        self._table_status.setText(text)

    def _populate_data_table(self, frame) -> None:
        """填充 K 线明细表格（最近 20 根，字段与原表格完全一致）。

        展示规则（配色沿用项目绿涨红跌）：
          · 涨跌列: 阳线 ↑绿 / 阴线 ↓红（移除文字）
          · 成交量: 对比近 20 根均值, ≥1.2x 放量🔺 / ≤0.8x 缩量🔻 / 常态⚫
          · RSI 列: >70 超买⚠️ / 30~70 常态●灰 / <30 超卖🔵
          · Δ 列: 正数 ↑绿 / 负数 ↓红 / 0 值 —灰
          · 收盘/VWAP/RSI 数值加粗高亮
        """
        if frame is None or not frame.bars:
            self._data_table.setRowCount(0)
            return
        ind = frame.indicators
        of = frame.orderflow
        bars = frame.bars[:20]  # 与旧表格一致: 最近 20 根
        vols = [b.volume for b in bars]
        mean_vol = sum(vols) / len(vols) if vols else 0.0

        n = len(bars)
        self._data_table.setRowCount(n)
        for i, b in enumerate(bars):
            yang = b.close >= b.open
            ts = datetime.datetime.fromtimestamp(b.ts_open / 1000).strftime("%m-%d %H:%M")
            rsi = ind.rsi14[i] if i < len(ind.rsi14) and not math.isnan(ind.rsi14[i]) else None
            vwap = ind.vwap[i] if i < len(ind.vwap) and not math.isnan(ind.vwap[i]) else None
            delta = of.delta[i] if of and i < len(of.delta) and not math.isnan(of.delta[i]) else None

            # 涨跌图标（阳↑绿 / 阴↓红）
            trend_txt = "↑" if yang else "↓"
            trend_color = "#22c55e" if yang else "#ef4444"
            # 成交量图标（对比近 20 根均值）
            ratio = b.volume / mean_vol if mean_vol else 1.0
            vol_icon = "🔺" if ratio >= 1.2 else ("🔻" if ratio <= 0.8 else "⚫")
            # RSI 状态图标
            if rsi is None:
                rsi_icon = "—"
            elif rsi > 70:
                rsi_icon = "⚠️"
            elif rsi < 30:
                rsi_icon = "🔵"
            else:
                rsi_icon = "●"
            # Δ 差值
            if delta is None:
                d_txt, d_color = "—", "#8b949e"
            elif delta > 0:
                d_txt, d_color = f"↑{int(delta):+d}", "#22c55e"
            elif delta < 0:
                d_txt, d_color = f"↓{int(delta):+d}", "#ef4444"
            else:
                d_txt, d_color = "—", "#8b949e"

            vals = [
                (str(b.seq), "#8b949e", False),            # 序号
                (ts, None, False),                          # 时间(左对齐)
                (f"{b.open:.2f}", None, False),             # 开
                (f"{b.high:.2f}", None, False),             # 高
                (f"{b.low:.2f}", None, False),              # 低
                (f"{b.close:.2f}", None, True),             # 收(加粗)
                (trend_txt, trend_color, False),            # 涨跌
                (f"{vol_icon}{int(b.volume)}", None, False),  # 量(图标+数值)
                (f"{rsi:.1f} {rsi_icon}" if rsi is not None else f"— {rsi_icon}", None, True),  # RSI(加粗)
                (f"{vwap:.2f}" if vwap is not None else "—", None, True),  # VWAP(加粗)
                (d_txt, d_color, False),                    # Δ
            ]
            for col, (text, color, bold) in enumerate(vals):
                item = QTableWidgetItem(text)
                if col == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if color:
                    item.setForeground(QColor(color))
                if bold:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self._data_table.setItem(i, col, item)

    def toPlainText(self) -> str:
        """兼容方法：返回表格文本（供测试/外部读取，保持原文本表格语义）。"""
        lines = [self._table_status.text()]
        lines.append("序号 | 时间 | 开盘 | 最高 | 最低 | 收盘 | 涨跌 | 成交量 | RSI | VWAP | Δ")
        for r in range(self._data_table.rowCount()):
            row = [
                self._data_table.item(r, c).text() if self._data_table.item(r, c) else ""
                for c in range(self._data_table.columnCount())
            ]
            lines.append(" | ".join(row))
        return "\n".join(lines)

    # ── 标签页内容渲染 ────────────────────────────────────────────────────
    def _populate_tabs(self, frame, wa, res) -> None:
        self._populate_data_table(frame)
        self._tab_snapshot.setPlainText(self._render_snapshot_tab(frame, wa))
        self._tab_diagnosis.setPlainText(self._render_diagnosis_tab(frame, wa))
        self._tab_decision.setHtml(self._render_decision_tab(wa))  # 富文本（红色粗体结论）
        # 提交分析联动：在问AI面板自动追加一条完整分析日志（推理步骤 + Token 消耗）
        title = f"{frame.symbol} {frame.timeframe} 分析日志"
        self._tab_ai.append_log(title, self._render_ai_tab(res, wa))

    def _render_data_tab(self, frame) -> str:
        """数据标签页：分析了哪些数据（K线明细表，保留原实现供兼容）。"""
        if frame is None or not frame.bars:
            return "无数据"
        lines = [
            f"=== 分析数据（{frame.symbol} {frame.timeframe}，共 {len(frame.bars)} 根K线）===",
            "",
            "序号 | 时间 | 开盘 | 最高 | 最低 | 收盘 | 阳阴 | 量 | RSI | VWAP | Δ",
            "-----|------|------|------|------|------|------|----|-----|------|-----",
        ]
        ind = frame.indicators
        of = frame.orderflow
        for i in range(min(20, len(frame.bars))):
            b = frame.bars[i]
            import datetime as _dt

            ts = _dt.datetime.fromtimestamp(b.ts_open / 1000).strftime("%m-%d %H:%M")
            yang = "阳" if b.close > b.open else "阴"
            rsi = ind.rsi14[i] if i < len(ind.rsi14) and not math.isnan(ind.rsi14[i]) else "-"
            vwap = ind.vwap[i] if i < len(ind.vwap) and not math.isnan(ind.vwap[i]) else "-"
            d = of.delta[i] if of and i < len(of.delta) and not math.isnan(of.delta[i]) else "-"
            rsi_s = f"{rsi:.1f}" if isinstance(rsi, float) else "-"
            vwap_s = f"{vwap:.2f}" if isinstance(vwap, float) else "-"
            d_s = f"{d:+.0f}" if isinstance(d, float) else "-"
            lines.append(
                f"{b.seq:<4} | {ts} | {b.open:.2f} | {b.high:.2f} | {b.low:.2f} | "
                f"{b.close:.2f} | {yang} | {b.volume:.0f} | {rsi_s} | {vwap_s} | {d_s}"
            )
        return "\n".join(lines)

    def _render_snapshot_tab(self, frame, wa) -> str:
        """快照标签页：当前行情快照。"""
        if frame is None or not frame.bars:
            return "无数据"
        latest = frame.bars[0]
        ind = frame.indicators
        of = frame.orderflow
        lines = [
            f"=== 行情快照（{frame.symbol} {frame.timeframe}）===",
            "",
            f"最新价:   {latest.close:.2f}",
            f"K线区间: {latest.low:.2f} - {latest.high:.2f}",
            f"成交量:   {latest.volume:.0f}",
            "",
            "── 技术指标 ──",
            f"RSI14:   {ind.rsi14[0]:.1f}" if not math.isnan(ind.rsi14[0]) else "RSI14:  -",
            f"EMA20:   {ind.ema20[0]:.2f}" if not math.isnan(ind.ema20[0]) else "EMA20:  -",
            f"ATR14:   {ind.atr14[0]:.2f}" if not math.isnan(ind.atr14[0]) else "ATR14:  -",
            f"BB:      [{ind.bb_lower[0]:.2f}, {ind.bb_upper[0]:.2f}]",
            f"VWAP:    {ind.vwap[0]:.2f}" if not math.isnan(ind.vwap[0]) else "VWAP:   -",
        ]
        if of is not None:
            lines += [
                "",
                "── 订单流 ──",
                f"Delta:   {of.delta[0]:+.0f}" if not math.isnan(of.delta[0]) else "Delta:  -",
                f"累积Δ:   {of.cumulative_delta[0]:+.0f}",
                f"POC:     {of.poc_price[0]:.2f}",
                f"VA:      [{of.val[0]:.2f}, {of.vah[0]:.2f}]",
            ]
        return "\n".join(lines)

    def _render_diagnosis_tab(self, frame, wa) -> str:
        """诊断标签页：为什么这么分析（威科夫三层推理）。"""
        if wa is None:
            return "未分析"
        lines = [wa.render_text()]
        return "\n".join(lines)

    def _compute_probabilities(self, wa) -> dict:
        """行情概率测算（确定性规则，完全基于 wa 现有盘面字段，可复现、不虚构）。

        依据：
          ① 趋势结构：regime + HH+HL / LH+LL 摆动计数
          ② 订单流状态：active_side（买/卖方主导）+ reversal_stage
          ③ VWAP 位置：现价高于/低于 VWAP（决定多空承压方向）
        输出：空头/多头/震荡观望 三个概率（和为 100%）。
        """
        long_p, short_p, neutral_p = 33.0, 33.0, 34.0  # 中性基线

        bg = wa.background
        # ① 趋势结构
        if bg.regime == "trend_up":
            long_p += 15 + min(bg.hh_hl_count, 5) * 3
            short_p -= 8
        elif bg.regime == "trend_down":
            short_p += 15 + min(bg.lh_ll_count, 5) * 3
            long_p -= 8
        elif bg.regime == "range":
            neutral_p += 20
            long_p -= 8
            short_p -= 8

        # ② 订单流状态
        if wa.orderflow is not None:
            of = wa.orderflow
            if of.active_side == "buy":
                long_p += 8
            elif of.active_side == "sell":
                short_p += 8
            if of.reversal_stage == "absorption":
                # 吸收阶段：多空趋于平衡，增加震荡权重
                neutral_p += 5
                long_p -= 2
                short_p -= 3

        # ③ VWAP 位置（价格承压/支撑方向）
        if wa.value_area is not None and wa.value_area.vwap is not None and wa.price is not None:
            if wa.price > wa.value_area.vwap:
                long_p += 6
            elif wa.price < wa.value_area.vwap:
                short_p += 6

        # 归一化到 100%（截断负值后按比例缩放）
        long_p = max(0.0, long_p)
        short_p = max(0.0, short_p)
        neutral_p = max(0.0, neutral_p)
        total = long_p + short_p + neutral_p
        if total <= 0:
            return {"short": 33, "long": 33, "neutral": 34}
        long_pct = round(long_p / total * 100)
        short_pct = round(short_p / total * 100)
        neutral_pct = 100 - long_pct - short_pct  # 保证三项合计恒为 100
        return {"short": short_pct, "long": long_pct, "neutral": neutral_pct}

    def _render_decision_tab(self, wa) -> str:
        """决策标签页（文案规范化重写）：行情倾向/入场触发/失效阈值/订单流结构/备注。

        严格写实：全部内容仅基于 wa 中已计算出的盘面数据陈述，不做行情预判与夸大推演；
        核心结论（行情倾向）使用红色粗体标注。
        """
        if wa is None:
            return "未分析"
        bias_zh = {"long": "多头", "short": "空头", "neutral": "中性"}.get(wa.bias, wa.bias)
        regime_zh = {
            "trend_up": "上升趋势", "trend_down": "下降趋势",
            "range": "区间震荡", "unknown": "结构不明",
        }.get(wa.background.regime, wa.background.regime)
        bg = wa.background

        p = []
        p.append("<div style='font-size:13px;line-height:1.8'>")
        p.append("<p style='margin:2px 0 8px'><b style='color:#8b949e'>交易决策（基于当前盘面数据，严格写实）</b></p>")

        # ① 行情倾向 —— 核心结论：红色粗体
        p.append("<p style='margin:6px 0 2px'><b style='color:#e6edf3'>① 行情倾向</b></p>")
        p.append(
            f"<p style='margin:2px 0'><b><span style='color:#ef4444;font-size:15px'>{bias_zh}</span></b>"
            f"　<span style='color:#8b949e'>背景：{regime_zh}（HH+HL {bg.hh_hl_count} 组 / LH+LL {bg.lh_ll_count} 组）</span></p>"
        )

        # ② 入场触发条件
        p.append("<p style='margin:8px 0 2px'><b style='color:#e6edf3'>② 入场触发条件</b></p>")
        p.append(f"<p style='margin:2px 0;color:#e6edf3'>{html.escape(wa.trigger)}</p>")

        # ③ 失效硬阈值
        p.append("<p style='margin:8px 0 2px'><b style='color:#e6edf3'>③ 失效硬阈值</b></p>")
        p.append(f"<p style='margin:2px 0;color:#e6edf3'>{html.escape(wa.invalidation)}</p>")

        # ④ 订单流结构
        p.append("<p style='margin:8px 0 2px'><b style='color:#e6edf3'>④ 订单流结构</b></p>")
        if wa.orderflow is not None:
            of = wa.orderflow
            p.append(
                f"<p style='margin:2px 0;color:#e6edf3'>活跃方：{of.active_side}　|　反转阶段：{of.reversal_stage}"
                f"　|　失衡 {len(of.imbalances)} 处　|　堆叠 {len(of.stacked_imbalances)} 组</p>"
            )
        else:
            p.append("<p style='margin:2px 0;color:#8b949e'>无订单流数据（Tick 数据不足）</p>")

        # 备注
        if wa.notes:
            p.append("<p style='margin:8px 0 2px'><b style='color:#e6edf3'>⑤ 备注</b></p>")
            for n in wa.notes:
                p.append(f"<p style='margin:2px 0;color:#8b949e'>· {html.escape(n)}</p>")

        # ── 底部：行情概率总结（基于本页盘面结论的确定性测算，红色加粗）────
        prob = self._compute_probabilities(wa)
        p.append(
            "<p style='margin:10px 0 2px;border-top:1px solid #2a3442;padding-top:8px'>"
            "<b style='color:#ef4444;font-size:14px'>"
            f"当前盘面综合研判：空头行情概率 {prob['short']}%，多头行情概率 {prob['long']}%，震荡观望概率 {prob['neutral']}%"
            "</b></p>"
        )

        p.append("</div>")
        return "".join(p)

    def _render_ai_tab(self, res, wa) -> str:
        """问AI标签页：AI 分析结论 + 概率 + 思考过程 + Token 统计。

        未运行 AI（如仅获取数据）时，展示威科夫三层推理作为分析日志内容。
        """
        if res is None or res.ai_diagnosis is None:
            if wa is not None:
                return "（本次未运行 AI 诊断）\n\n" + wa.render_text()
            return "尚未运行 AI 诊断。点击「📝 提交分析」以获取 AI 增强分析。"
        ai = res.ai_diagnosis
        lines = [
            "=== AI 分析（DeepSeek）===",
            "",
            f"方向: {ai.get('direction', '?')}",
            f"置信度: {ai.get('diagnosis_confidence', '?')}%（概率）",
            f"周期: {ai.get('cycle_position', '?')}",
            "",
            "── 关键信号（为什么这么分析）──",
        ]
        for s in (ai.get("key_signals") or []):
            lines.append(f"· {s}")
        if ai.get("wyckoff_check"):
            wk = ai["wyckoff_check"]
            agree = "一致 ✅" if wk.get("regime_agree") else "分歧 ⚠️"
            lines += ["", f"与程序诊断: {agree}", wk.get("note", "")]
        plan = ai.get("trade_plan") or {}
        if plan:
            lines += [
                "",
                "── 交易计划 ──",
                f"倾向: {plan.get('bias', '?')}",
                f"触发: {plan.get('trigger', '?')}",
                f"失效: {plan.get('invalidation', '?')}",
                f"止损参考: {plan.get('stop_reference', '?')}",
                f"目标参考: {plan.get('target_reference', '?')}",
            ]
        if ai.get("risk_warning"):
            lines += ["", f"⚠️ 风险: {ai['risk_warning']}"]

        # ── Token / 上下文占用统计 ─────────────────────────────────────────
        usage = res.usage or {}
        reasoning = (res.ai_reasoning or "").strip()
        completion_text = (res.ai_raw or "").strip()
        reasoning_chars = len(reasoning)
        completion_chars = len(completion_text)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        reasoning_tokens = usage.get("reasoning_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        ctx_window = getattr(self._settings.provider, "context_window", 2000000)
        ctx_pct = total_tokens / ctx_window * 100 if ctx_window else 0

        lines += [
            "",
            "── ⚙ 消耗统计 ──",
            f"思考字数: {reasoning_chars:,} 字" + (f"（思考 Token {reasoning_tokens:,}）" if reasoning_tokens else ""),
            f"回复字数: {completion_chars:,} 字（{completion_tokens:,} tokens）",
            f"上下文占用: {total_tokens:,} / {ctx_window:,} tokens（{ctx_pct:.2f}%）",
            f"耗时: {res.latency_ms / 1000:.1f}s",
        ]

        # ── 思考过程（DeepSeek reasoning_content）──────────────────────────
        if reasoning:
            lines += [
                "",
                "── 🧠 思考过程 ──",
                reasoning,
            ]
        return "\n".join(lines)

    # ── 问AI：对话提问（基于当前分析结果）───────────────────────────────
    def _build_ai_context(self) -> str:
        """组装追问上下文：最近K线摘要 + 威科夫结论（均来自真实分析数据）。"""
        parts = []
        if self._last_frame is not None:
            f = self._last_frame
            b = f.bars[0]
            parts.append(
                f"品种 {f.symbol} {f.timeframe}，最新收盘 {b.close:.2f}（高 {b.high:.2f} / 低 {b.low:.2f}），"
                f"成交量 {b.volume:.0f}，共 {len(f.bars)} 根K线。"
            )
            parts.append("最近5根K线（新→旧）：")
            for i in range(min(5, len(f.bars))):
                bar = f.bars[i]
                ts = datetime.datetime.fromtimestamp(bar.ts_open / 1000).strftime("%m-%d %H:%M")
                parts.append(f"  {ts} O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} C={bar.close:.2f} V={bar.volume:.0f}")
        if self._last_wa is not None:
            parts.append("")
            parts.append("威科夫分析结论：")
            parts.append(self._last_wa.render_text())
        if not parts:
            parts.append("（尚未运行分析，仅凭用户问题回答）")
        return "\n".join(parts)

    def _on_ai_send(self) -> None:
        """用户发送提问：工作线程调用 DeepSeek，回复经信号回主线程展示。"""
        q = self._tab_ai.input.text().strip()
        if not q or self._ai_busy:
            return
        self._tab_ai.input.clear()
        self._tab_ai.append_user(q)
        self._tab_ai.append_ai("<span style='color:#8b949e'>思考中…</span>")
        self._ai_busy = True
        self._tab_ai.send_btn.setEnabled(False)

        ctx = self._build_ai_context()

        def _work() -> None:
            try:
                from wkf.ai.deepseek_client import DeepSeekClient

                settings = self._settings
                if not settings.provider.api_key:
                    reply = "未配置 AI 模型 API Key（设置 → AI 模型设置），无法回答。"
                else:
                    client = DeepSeekClient(settings.provider)
                    messages = [
                        {
                            "role": "system",
                            "content": (
                                "你是 WKF 威科夫交易分析助手。基于给定的真实K线与威科夫分析结果回答用户问题；"
                                "回答严谨、只陈述数据事实，不做行情预判与夸大推演；"
                                "数据不足时如实说明；结尾固定附上「以上仅是王先生的分析，仅做参考，不可以作为价值投资。」"
                            ),
                        },
                        {"role": "user", "content": f"{ctx}\n\n【用户问题】\n{q}"},
                    ]
                    reply = client.chat(messages, thinking=False)
                    reply = reply.content or "（模型无输出）"
                    if "价值投资" not in reply:
                        reply += "\n\n以上仅是王先生的分析，仅做参考，不可以作为价值投资。"
            except Exception as exc:  # noqa: BLE001
                reply = f"❌ AI 调用失败：{exc}"
            self._ai_reply.emit(reply)

        threading.Thread(target=_work, name="wkf-ai-chat", daemon=True).start()

    def _on_ai_reply(self, reply: str) -> None:
        """AI 回复到达（主线程）：原地更新"思考中"占位为正式回复。"""
        self._ai_busy = False
        self._tab_ai.send_btn.setEnabled(True)
        self._tab_ai.update_last_ai(
            f"<span style='color:#e6edf3'>{html.escape(reply).replace(chr(10), '<br>')}</span>"
        )

    # ── 自动分析：持续跟踪，等待新 K 线收盘后自动重新分析 ─────────────────
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
            self._kline_status.setText("♾ 持续跟踪已开启，等待新K线收盘...")
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
            self._kline_status.setText(f"🆕 新K线收盘 ({timeframe})，持续跟踪分析中...")
            self._on_analyze()
        else:
            # 更新剩余时间显示
            self._update_kline_status()

    def _measure_server_offset(self) -> int:
        """测量 MT5 服务器时钟与真实 UTC 的偏移（毫秒）。

        MT5 返回的 bar time / tick time_msc 均基于服务器时钟（本机实测快 3 小时，
        对应 GTC 服务器 GMT+3），而 time.time() 是真实 UTC——两者基准不同，
        直接相减会导致倒计时偏差数小时。取最新 tick 的 time_msc 与本地 UTC 之差作为偏移。
        """
        try:
            import MetaTrader5 as mt5
            from wkf.data.mt5_source import resolve_mt5_symbol

            if not mt5.initialize():
                return 0
            sym = resolve_mt5_symbol(self._sym_combo.currentText())
            now = int(time.time())
            # 范围覆盖服务器时钟（真实 UTC + 数小时），取最新 tick
            tks = mt5.copy_ticks_range(sym, now - 120, now + 4 * 3600, mt5.COPY_TICKS_ALL)
            if tks is not None and len(tks) > 0:
                return int(tks[-1]["time_msc"] - now * 1000)
        except Exception:
            pass
        return 0

    def _update_kline_status(self) -> None:
        """K线收盘倒计时：1 秒定时器秒级实时刷新（修复原 5 秒刷新的滞后问题）。

        实现：MT5 最新K线时间戳每 5 秒校准一次（避免每秒高频连接），
        其余每秒用本地时间精确递减剩余收盘时间；
        K线完结（时间戳变化）时自动以新K线起点重置倒计时。

        关键修复：K线时间戳基于 MT5 服务器时钟（与本地 UTC 有数小时时区偏移），
        必须先用服务器偏移对齐"当前时刻"，否则剩余时间偏差数小时
        （如 10 分钟K线显示成 185 分钟）。
        """
        if self._analysis_busy:
            return
        symbol = self._sym_combo.currentText()
        timeframe = self._tf_combo.currentText()
        now_mono = time.monotonic()

        # 首次测量服务器时钟偏移（缓存；服务器时区固定，一次即可）
        if self._server_offset_ms == 0:
            self._server_offset_ms = self._measure_server_offset()

        # 每 5 秒校准一次最新K线时间戳
        if now_mono - self._status_ts_fetched_at >= 5.0:
            ts = get_latest_bar_ts(symbol, timeframe)
            if ts > 0:
                if self._status_ts > 0 and ts != self._status_ts:
                    # K线已完结 → 新K线起点自动重置倒计时
                    self._status_ts = ts
                    if not self._auto_active and self._last_bar_ts > 0:
                        self._last_bar_ts = ts
                self._status_ts = ts
                self._status_ts_fetched_at = now_mono

        ts = self._status_ts
        if ts <= 0:
            return
        minutes = TF_MINUTES.get(timeframe, 15)
        period_ms = minutes * 60 * 1000  # 单根K线周期（如 10m = 600 秒）
        # 服务器时钟基准下的"当前时刻" = 真实 UTC + 服务器偏移
        server_now_ms = int(time.time() * 1000) + self._server_offset_ms
        remain_s = max(0, int((ts + period_ms - server_now_ms) // 1000))
        remain = f"{remain_s // 60}分{remain_s % 60}秒"
        if self._auto_active:
            self._kline_status.setText(f"♾ 持续跟踪中 · 当前K线 {remain} 后收盘")
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

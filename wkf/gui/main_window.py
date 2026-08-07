"""WKF 主窗口：全局初始化、页面调度、信号绑定（业务逻辑委托子控件）。

【改动点】需求一.1：架构重构——主窗口渐进式拆分。
 - K线图表组件：wkf/gui/chart_widget.py（既有）
 - 顶部控制组件：wkf/gui/widgets/top_bar.py（新增）
 - K线明细表格：wkf/gui/widgets/kline_table.py（新增）
 - 快照面板：wkf/gui/widgets/snapshot_panel.py（新增）
 - 诊断面板：wkf/gui/widgets/diagnosis_panel.py（新增）
 - 决策面板：wkf/gui/widgets/decision_panel.py（新增）
 - 历史记录面板：wkf/gui/widgets/history_panel.py（新增）
 - AI对话面板：wkf/gui/widgets/ai_chat.py（新增）
 本文件仅保留：窗口初始化、子控件组装、信号绑定、线程/定时器调度、
 数据获取与分析的编排（不承载任何面板渲染与指标计算）。
【涉及文件】wkf/gui/main_window.py（重构）
【验证方式】python -m unittest discover tests；tools/test_v130/v131/v24/switch 全量回归。
"""
from __future__ import annotations

import datetime
import html
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wkf.config.settings import load_settings
from wkf.data.base import KlineFrame
from wkf.data.mt5_source import resolve_mt5_symbol
from wkf.gui.chart_widget import WkfChart
from wkf.gui.settings_dialogs import AIModelDialog, FeishuDialog, IndicatorDialog
from wkf.gui.widgets.ai_chat import AiChatWidget
from wkf.gui.widgets.backtest_panel import BacktestPanel
from wkf.gui.widgets.decision_panel import DecisionPanel, compute_probabilities
from wkf.gui.widgets.diagnosis_panel import DiagnosisPanel
from wkf.gui.widgets.history_panel import HistoryPanel
from wkf.gui.widgets.kline_table import KlineTableWidget
from wkf.gui.widgets.snapshot_panel import SnapshotPanel
from wkf.gui.widgets.top_bar import TopControlBar
from wkf.util.timefmt import beijing_now_str
from wkf.orchestrator.runner import (
    AnalysisResult,
    fetch_frame_only,
    get_latest_bar_ts,
    run_analysis,
)

SYMBOLS = ["NQ1!", "ES1!", "GC1!"]
# 【改动点】周期下拉选项扩容 + 固定排序（短线→长线）。
# 显示文本（中文）与内部键（供接口/存储使用）分离：下拉显示"1分"等，
# itemData 存内部键（1m/3m/.../1w），下游全部使用内部键，互不干扰。
# 【验证方式】打开周期下拉，顺序严格为 1分→3分→5分→10分→15分→30分→60分→120分→240分→日线→周线
TIMEFRAME_ITEMS = [
    ("1分", "1m"), ("3分", "3m"), ("5分", "5m"), ("10分", "10m"),
    ("15分", "15m"), ("30分", "30m"), ("60分", "1h"),
    ("120分", "2h"), ("240分", "4h"), ("日线", "1d"), ("周线", "1w"),
]
TIMEFRAMES = [key for _, key in TIMEFRAME_ITEMS]  # 内部键列表（兼容既有代码）
# 【改动点】周期→分钟映射：日线=1440分钟、周线=10080分钟（用于接口请求参数转换）
TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "1d": 1440, "1w": 10080,
}
# 图表默认时间级别：48 小时窗口（切换品种/周期后始终保持该窗口；日线/周线单独指定根数）
WINDOW_HOURS = 48
# 【改动点】④K线内存缓存有效期（秒）：短周期重复切换命中缓存直接渲染，无需重请求
CACHE_TTL_S = 60

# 兼容旧引用（架构重构：子控件类已迁至 wkf.gui.widgets，保留别名避免破坏旧导入）
_KlineTableWidget = KlineTableWidget
_AiChatWidget = AiChatWidget


class _FetchThread(QThread):
    """行情数据异步加载线程（核心优化1）。

    MT5/yfinance 历史K线拉取、Footprint 计算、订单流解析全部在子线程完成，
    计算结束后经 done 信号一次性回传主线程渲染；子线程绝不操作画布控件。
    """

    done = pyqtSignal(object, object, str, int)  # frame, wa, err, request_id

    def __init__(self, symbol: str, timeframe: str, bar_count: int,
                 settings, request_id: int, parent=None) -> None:
        super().__init__(parent)
        self._symbol = symbol
        self._timeframe = timeframe
        self._bar_count = bar_count
        self._settings = settings
        self._request_id = request_id

    def run(self) -> None:
        try:
            from wkf.orchestrator.runner import fetch_frame_cached

            frame, wa, err, _from_cache = fetch_frame_cached(
                self._symbol, self._timeframe,
                bar_count=self._bar_count, settings=self._settings,
                use_disk_cache=True,
            )
            self.done.emit(frame, wa, err, self._request_id)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, None, str(exc), self._request_id)


class MainWindow(QMainWindow):
    # 工作线程 → UI 线程信号（PyQt6 线程安全回调）
    _fetch_done = pyqtSignal(object, object, str, int)  # frame, wyckoff, err, request_id
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

        # ── 顶部控制组件（品种/周期/按钮/状态/北京时钟）───────────────────
        self._top = TopControlBar()
        self._sym_combo = self._top._sym_combo
        self._tf_combo = self._top._tf_combo
        self._fetch_btn = self._top._fetch_btn
        self._analyze_btn = self._top._analyze_btn
        self._auto_check = self._top._auto_check
        self._crosshair_btn = self._top._crosshair_btn
        self._ds_combo = self._top._ds_combo
        self._kline_status = self._top._kline_status
        self._clock_label = self._top._clock_label

        # 【改动点】需求三：数据源模式 → 品种列表。
        # MT5 模式：NQ1!/ES1!/GC1!；yfinance 模式：BTC-USD/^GSPC/^NDX/^DJI。
        # 切换数据源后重启生效（品种下拉内容随模式变化）。
        self._symbols = list(SYMBOLS)
        try:
            if getattr(self._settings.general, "data_source", "mt5") == "yfinance":
                from wkf.data.datasource import get_data_source

                src = get_data_source("yfinance")
                self._symbols = src.available_symbols() or self._symbols
        except Exception:
            pass
        self._sym_combo.addItems(self._symbols)
        # 数据源下拉：按当前配置选中（MT5 / YFinance）
        ds_idx = self._ds_combo.findData(
            getattr(self._settings.general, "data_source", "mt5")
        )
        self._ds_combo.setCurrentIndex(ds_idx if ds_idx >= 0 else 0)
        # 周期下拉：显示中文文本(1分…日线/周线)，itemData 存内部键
        for label, key in TIMEFRAME_ITEMS:
            self._tf_combo.addItem(label, key)
        # 默认配置恢复：读取 settings 中的 last_symbol/last_timeframe，
        # 默认品种 XAU/USD(GC1!)、默认周期 5 分钟。
        init_sym = getattr(self._settings.general, "last_symbol", "GC1!") or "GC1!"
        init_tf = getattr(self._settings.general, "last_timeframe", "5m") or "5m"
        if init_sym in self._symbols:
            self._sym_combo.setCurrentText(init_sym)
        idx = self._tf_combo.findData(init_tf)
        self._tf_combo.setCurrentIndex(idx if idx >= 0 else 0)
        root.addWidget(self._top)

        # 品种/周期变更 → 自动刷新图表（带 300ms 防抖，快速连续切换只发最后一次请求）
        self._sym_combo.currentIndexChanged.connect(self._on_selector_changed)
        self._tf_combo.currentIndexChanged.connect(self._on_selector_changed)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._on_fetch_data)
        self._fetch_btn.clicked.connect(self._on_fetch_data)
        self._analyze_btn.clicked.connect(self._on_analyze)
        self._auto_check.toggled.connect(self._on_auto_toggle)
        self._crosshair_btn.toggled.connect(self._on_crosshair_toggle)
        self._ds_combo.currentIndexChanged.connect(self._on_data_source_changed)

        # ── 图表 + 分析结果面板（历史 + 标签页）────────────────────────────
        split = QSplitter(Qt.Orientation.Vertical)
        self._chart = WkfChart()
        split.addWidget(self._chart)

        # 【改动点】V1.3.3 图表交互：空格键重置图表为完整视图。
        from PyQt6.QtGui import QKeySequence, QShortcut

        self._reset_view_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._reset_view_shortcut.activated.connect(self._chart.reset_view)

        # 【改动点】V1.3.3：底部状态栏实时展示当前激活数据源名称。
        self.statusBar().showMessage(f"行情数据源：{self._data_source_label()}", 0)

        # 结果区：左侧历史记录面板 + 右侧标签页（数据/快照/诊断/决策/问AI）
        result_split = QSplitter(Qt.Orientation.Horizontal)

        self._history_panel = HistoryPanel()
        self._history_list = self._history_panel._history_list
        result_split.addWidget(self._history_panel)

        # 5 个标签页
        tabs = QTabWidget()
        # 数据标签页：K线明细表格（UI 展示优化，自带 toPlainText 兼容）
        self._tab_data = KlineTableWidget()
        self._table_status = self._tab_data.status_label
        self._data_table = self._tab_data.table
        tabs.addTab(self._tab_data, "📊 数据")

        # 快照标签页：保存按钮 + 正文 + 底部生成时间
        self._tab_snapshot = SnapshotPanel()
        self._snapshot_save_btn = self._tab_snapshot.save_btn
        self._tab_snapshot_text = self._tab_snapshot.text_view
        self._snapshot_time_label = self._tab_snapshot.time_label
        self._snapshot_save_btn.clicked.connect(self._save_snapshot)
        tabs.addTab(self._tab_snapshot, "📸 快照")

        # 诊断标签页：顶部诊断生成时间 + 威科夫三层推理
        self._tab_diagnosis_panel = DiagnosisPanel()
        self._tab_diagnosis = self._tab_diagnosis_panel.text_view
        tabs.addTab(self._tab_diagnosis_panel, "🔍 诊断")

        # 决策标签页：富文本四段决策 + 概率总结（红色粗体）
        self._tab_decision_panel = DecisionPanel()
        self._tab_decision = self._tab_decision_panel.view
        tabs.addTab(self._tab_decision_panel, "🎯 决策")

        # 问AI页：对话容器（上层展示区 + 底部输入框/发送按钮，回车发送）
        self._tab_ai = AiChatWidget()
        self._tab_ai.input.returnPressed.connect(self._on_ai_send)
        self._tab_ai.send_btn.clicked.connect(self._on_ai_send)
        tabs.addTab(self._tab_ai, "🤖 问AI")

        # 【改动点】需求四：新增回测标签页（只读信号复盘统计，表格展示）
        # 【涉及文件】wkf/gui/main_window.py + wkf/gui/widgets/backtest_panel.py
        # 【验证方式】打开回测标签页可见统计表；分析完成后自动刷新
        self._tab_backtest = BacktestPanel()
        self._tab_backtest.refresh_btn.clicked.connect(self._tab_backtest.refresh)
        tabs.addTab(self._tab_backtest, "📈 回测")
        self._tab_backtest.refresh()

        # 【改动点】Tab 栏右侧新增静态邮箱标签（禁止下拉菜单，控件选型为 QLabel；
        #           开启文本可选中复制）。位于「问AI」标签右侧。
        self._contact_label = QLabel("　技术对接：lij55030@gmail.com")
        self._contact_label.setStyleSheet(
            "color:#8b949e;font-size:12px;padding:0 8px;background:transparent;"
        )
        self._contact_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        tabs.setCornerWidget(self._contact_label, Qt.Corner.TopRightCorner)

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
        # 【改动点】异步加载迭代：全局加载锁 + 请求序号 + 当前工作线程引用。
        #  - _loading=True 时忽略新的切换触发（不排队，仅记录 pending 最后意图）；
        #  - _fetch_seq 递增序号用于丢弃过期响应（与 _fetch_req 令牌双重校验）。
        self._loading = False
        self._switching = False  # 切换防抖窗口内（尚未进入加载）也锁定状态栏提示
        self._fetch_seq = 0
        self._fetch_thread: _FetchThread | None = None
        self._pending_switch: tuple | None = None
        self._crosshair_suspended = False
        self._history_count = 0
        self._has_ai_result = False
        self._analysis_time = ""  # 本次分析时间（年月日时分秒），决策面板/历史/飞书统一使用
        # 【改动点】④K线内存缓存字典：key=(品种,周期) value=(monotonic, frame, wyckoff)
        self._frame_cache: dict[tuple, tuple] = {}
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
        # K线收盘倒计时：1 秒定时器秒级实时刷新；MT5 时间戳每 5 秒校准一次
        self._server_offset_ms = 0
        self._status_ts = 0
        self._status_ts_fetched_at = 0.0
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_check_kline)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_kline_status)
        self._status_timer.start(1000)  # 1 秒定时器：秒级实时倒计时
        # 【改动点】顶部北京时钟：独立 1 秒定时器刷新（不受倒计时 early-return 影响）
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

        # ── 实时价格标注：每 2 秒后台轮询 MT5 最新 tick 价，更新图表红线 ──
        self._tick_updated.connect(self._on_tick_updated)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._poll_tick)
        self._tick_timer.start(2000)

        # 启动后立即拉一次数据 + 状态
        self._on_fetch_data()
        # 首次启动引导：自动创建目录 + 弹窗引导基础配置（AI Key / 飞书 Webhook）
        self._first_run_setup()
        # 【改动点】数据源模式检查（需求三）：yfinance 模式无 Tick 数据 →
        # 弹窗提示 + 隐藏订单流面板（决策面板订单流区块由渲染层自动省略）。
        # 【涉及文件】wkf/gui/main_window.py + wkf/data/datasource.py
        # 【验证方式】settings 切到 yfinance 启动：弹窗提示"无Tick数据"；
        #            决策面板不再出现订单流结构区块。
        self._check_data_source_mode()

    # ── 首次启动引导 ──────────────────────────────────────────────────────
    def _first_run_setup(self) -> None:
        """首次启动：自动创建所需文件夹（output 报告/推送日志等）；弹窗引导基础配置。"""
        try:
            from wkf.config.settings import SETTINGS_JSON_PATH, save_settings

            out_dir = SETTINGS_JSON_PATH.parent.parent / "output"
            out_dir.mkdir(parents=True, exist_ok=True)  # 分析报告 / push_log.txt 输出目录
        except Exception:
            pass

        if not getattr(self._settings.general, "first_run", False):
            return
        try:
            self._settings.general.first_run = False
            save_settings(self._settings, SETTINGS_JSON_PATH)
        except Exception:
            pass

        missing: list[str] = []
        if not (self._settings.provider.api_key or "").strip():
            missing.append("🤖 AI 模型 API Key")
        if self._settings.feishu.notify_enabled and not (self._settings.feishu.webhook_url or "").strip():
            missing.append("📮 飞书 Webhook 地址")
        if missing:
            QTimer.singleShot(1200, lambda: self._show_first_run_guide(missing))

    def _show_first_run_guide(self, missing: list) -> None:
        if not self.isVisible():
            return
        from PyQt6.QtWidgets import QMessageBox

        ret = QMessageBox.question(
            self,
            "WKF 首次使用引导",
            "欢迎使用 WKF 威科夫交易智能体！\n\n"
            "检测到以下基础配置尚未完成：\n"
            + "\n".join(f"  · {m}" for m in missing)
            + "\n\n是否现在打开设置面板进行配置？\n"
            "（未配置 AI Key 将自动切换纯规则模式，飞书推送将暂停）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        joined = "".join(missing)
        if "AI" in joined:
            self._open_ai_dialog()
        elif "飞书" in joined:
            self._open_feishu_dialog()

    def closeEvent(self, event) -> None:
        """关闭窗口：停止定时器与后台线程，避免进程残留。"""
        self._tick_timer.stop()
        self._status_timer.stop()
        self._auto_timer.stop()
        if self._fetch_thread is not None and self._fetch_thread.isRunning():
            self._fetch_thread.wait(2000)
        super().closeEvent(event)

    # ── 48 小时时间级别：按周期换算需要拉取的K线根数 ─────────────────────
    def _window_bar_count(self, timeframe: str) -> int:
        """返回 48 小时窗口对应的K线根数（含用户自定义根数下限）。

        【改动点】日线/周线不再套用 48 小时换算（会退化为 2 根/0 根），
        单独指定根数：日线 60 根、周线 30 根；其余周期保持 48 小时窗口。
        【验证方式】选择日线图表约 60 根、周线约 30 根，5分=576 根（48h）。
        """
        if timeframe == "1d":
            return 60
        if timeframe == "1w":
            return 30
        minutes = TF_MINUTES.get(timeframe, 15)
        base = WINDOW_HOURS * 60 // minutes  # 48h 对应根数
        # 若用户在「其他设置」调大了K线数量则尊重用户配置（显示更多）
        return max(base, getattr(self._settings.general, "analysis_bar_count", 48))

    def _current_tf(self) -> str:
        """返回当前选中的周期内部键（下拉显示中文文本，itemData 存内部键）。"""
        return self._tf_combo.currentData() or TIMEFRAMES[0]

    # ── 十字光标工具：按钮开关（独立功能，不干扰拖拽/缩放/点击）───────────
    def _on_crosshair_toggle(self, checked: bool) -> None:
        """十字光标按钮点击：激活/关闭，带按钮视觉反馈。"""
        self._chart.set_crosshair_enabled(checked)
        if checked:
            self._crosshair_btn.setText("⛔ 关闭光标")
            self._crosshair_btn.setStyleSheet(
                "QPushButton{background-color:#1e3a5f;color:#e6edf3;"
                "border:1px solid #3b82f6;border-radius:4px;padding:4px 10px;}"
            )
        else:
            self._crosshair_btn.setText("➕ 十字光标")
            self._crosshair_btn.setStyleSheet("")

    # ── 实时价格标注：后台轮询 MT5 tick，更新图表红线 ─────────────────────
    def _poll_tick(self) -> None:
        """每 2 秒触发：后台线程取当前品种最新 tick 价（不阻塞 UI）。"""
        if not self._chart._frame:  # 图表尚未加载数据则跳过，减少空转
            return
        symbol = self._sym_combo.currentText()
        timeframe = self._current_tf()
        sym, tf = symbol, timeframe

        def _work() -> None:
            try:
                import MetaTrader5 as mt5
                from wkf.data.mt5_source import ensure_mt5_initialized

                if not ensure_mt5_initialized(mt5):
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

    # ── 数据源模式检查（需求三：yfinance 可选数据源）──────────────────────
    def _check_data_source_mode(self) -> None:
        """yfinance 模式：无 Tick 数据 → 弹窗提示 + 订单流相关功能自动隐藏。"""
        try:
            mode = getattr(self._settings.general, "data_source", "mt5")
            if mode != "yfinance":
                return
            from PyQt6.QtWidgets import QMessageBox

            QTimer.singleShot(
                800,
                lambda: QMessageBox.information(
                    self,
                    "数据源：yfinance 模式",
                    "当前数据源为 yfinance（通用行情）。\n\n"
                    "· 支持 BTC-USD、美股指数（^GSPC/^NDX/^DJI）等品种\n"
                    "· 无 Tick 数据 → 订单流/足迹图/实时价格线已自动隐藏\n"
                    "· 上层指标与威科夫结构分析逻辑不受影响\n\n"
                    "如需恢复订单流功能，请在「⚙ 设置 → 其他设置 → 行情数据源」切回 MT5。",
                ),
            )
        except Exception:
            pass

    # ── 行情数据源切换（V1.3.3：前端控件暴露，复用 datasource.py 工厂）──
    def _data_source_label(self) -> str:
        """当前激活数据源的中文名称（底部状态栏/诊断/快照共用）。"""
        mode = getattr(self._settings.general, "data_source", "mt5")
        return "MT5实盘数据源" if mode != "yfinance" else "YFinance公开数据源"

    def _rebuild_symbols(self, mode: str) -> None:
        """按数据源模式重建品种下拉（blockSignals 防止触发切换递归）。"""
        new_symbols = list(SYMBOLS)
        if mode == "yfinance":
            try:
                from wkf.data.datasource import get_data_source

                src = get_data_source("yfinance")
                new_symbols = src.available_symbols() or new_symbols
            except Exception:
                pass
        self._symbols = new_symbols
        self._sym_combo.blockSignals(True)
        self._sym_combo.clear()
        self._sym_combo.addItems(self._symbols)
        self._sym_combo.blockSignals(False)

    def _on_data_source_changed(self, _idx: int) -> None:
        """行情数据源切换触发逻辑：
        更新设置 → 清空图表缓存 → 异步拉取对应数据源K线 → 刷新图表。
        底层复用 wkf.data.datasource 工厂（runner 取数已按 settings 走工厂）。
        """
        mode = self._ds_combo.currentData() or "mt5"
        if mode == getattr(self._settings.general, "data_source", "mt5"):
            return
        self._settings.general.data_source = mode
        try:
            from wkf.config.settings import save_settings, SETTINGS_JSON_PATH

            save_settings(self._settings, SETTINGS_JSON_PATH)
        except Exception:
            pass
        # 1. 清空图表缓存（内存帧缓存；磁盘 K 线缓存按品种/周期键隔离，无需删除）
        self._frame_cache.clear()
        self._last_frame = None
        self._last_wa = None
        self._has_ai_result = False
        # 2. 重建品种列表（yfinance：BTC/美股指数；MT5：NQ/ES/XAU）
        self._rebuild_symbols(mode)
        # 3. 底部状态栏实时展示当前激活数据源
        self.statusBar().showMessage(f"行情数据源：{self._data_source_label()}", 0)
        # 4. 清空旧图表 + 触发异步加载（走统一加载链路，QThread 拉取）
        sym = self._sym_combo.currentText()
        tf = self._current_tf()
        self._prepare_switch(sym, tf, is_symbol_change=True)
        self._debounce_timer.start()

    # ── 品种/周期切换：记忆持久化 + 防抖刷新 ──────────────────────────────
    def _on_selector_changed(self) -> None:
        """品种/周期变更：记忆持久化 + 全局加载锁 + 前置清理 + 防抖刷新。

        【改动点】异步加载迭代（V1.3.2）：
          · 全局加载锁：数据加载中（_loading=True）直接忽略新切换触发，
            不排队不重复加载，仅记录最后一次意图（_pending_switch），
            加载完成后自动补发，避免多任务堆积；
          · 切换第一时间执行前置资源清理（_prepare_switch）：隐藏K线画布/
            实时价格线/十字光标/指标图层，挂起Tick定时器与鼠标监听；
          · 状态栏区分「品种数据加载中」/「周期重构渲染中」。

        【历史改动点】「品种-周期」独立记忆（settings.general.per_symbol_timeframe）：
          · 品种切换：保存旧品种当前周期 → 恢复目标品种上次选用的周期（blockSignals 防递归）；
          · 周期切换：立即把新周期写入当前品种记忆并落盘；
          重启后记忆不丢失。
        【验证方式】GC1! 选 30分 → 切 NQ1! 选 5分 → 切回 GC1! 自动恢复 30分；
                    关闭软件重启，品种与周期记忆保留。
        """
        g = self._settings.general
        prev_sym = g.last_symbol
        prev_tf = g.last_timeframe
        sym = self._sym_combo.currentText()
        tf = self._current_tf()

        if sym != prev_sym:
            # 品种切换：保存旧品种周期记忆，恢复目标品种上次选用的周期
            if prev_sym and prev_tf and prev_sym in self._symbols:
                g.per_symbol_timeframe[prev_sym] = prev_tf
            saved = g.per_symbol_timeframe.get(sym)
            if saved and saved != tf:
                self._tf_combo.blockSignals(True)
                idx = self._tf_combo.findData(saved)
                if idx >= 0:
                    self._tf_combo.setCurrentIndex(idx)
                self._tf_combo.blockSignals(False)
                tf = saved
        else:
            # 周期切换：立即把新周期写入当前品种记忆
            g.per_symbol_timeframe[sym] = tf

        if sym != prev_sym or tf != prev_tf:
            g.last_symbol = sym
            g.last_timeframe = tf
            try:
                from wkf.config.settings import save_settings, SETTINGS_JSON_PATH

                save_settings(self._settings, SETTINGS_JSON_PATH)
            except Exception:
                pass

        self._has_ai_result = False  # 新品种数据，旧 AI 结果作废

        # 全局加载锁：加载中忽略新切换（不排队），仅记录最后一次意图
        if self._loading:
            self._pending_switch = (sym, tf)
            return

        # 切换动作第一时间：前置资源清理 + 挂起附属功能 + 状态提示
        self._prepare_switch(sym, tf, is_symbol_change=(sym != prev_sym))
        self._switching = True
        self._debounce_timer.start()

    def _prepare_switch(self, symbol: str, timeframe: str, *, is_symbol_change: bool) -> None:
        """切换前置资源清理提速（第一时间执行）。

        1. 清空历史K线绘图 Item、VA/POC 指标图层（overlay 覆盖层独立保留，Z 层级不变）；
        2. 销毁旧实时价格线/标签，重置十字光标绘制状态；
        3. 临时挂起 Tick 价格定时器与鼠标光标监听；
        4. 清空 K 线明细表格缓存，避免新旧数据叠加渲染。
        """
        # 1. 清空主图与 RSI 数据层（overlay 层独立保留）
        self._chart.clear_items()
        self._chart.clear_rsi()
        # 2. 重置视图状态与旧数据帧（新数据强制 autoRange；十字线吸附基准一并失效）
        self._chart.reset_view_state(symbol)
        # 3. 隐藏实时价格线/十字光标 + 挂起鼠标监听（加载完成后恢复）
        self._chart.suspend_interactions()
        self._crosshair_suspended = True
        # 4. 临时挂起 Tick 价格定时器（2 秒轮询），完成后重启
        self._tick_timer.stop()
        # 5. 清空 K 线明细表格缓存
        self._data_table.setRowCount(0)
        # 6. 状态栏加载提示：品种加载 / 周期重构区分文案
        if is_symbol_change:
            self._kline_status.setText(f"⏳ 品种数据加载中...（{symbol} {timeframe}）")
            self._set_table_status(
                f"⏳ 品种数据加载中...（{symbol} {timeframe}，{WINDOW_HOURS}h 窗口）"
            )
        else:
            self._kline_status.setText(f"⏳ 周期重构渲染中...（{symbol} {timeframe}）")
            self._set_table_status(
                f"⏳ 周期重构渲染中...（{symbol} {timeframe}，{WINDOW_HOURS}h 窗口）"
            )

    # ── 历史记录 ──────────────────────────────────────────────────────────
    def _append_history(self, symbol: str, timeframe: str, bias: str, report: str,
                        time_str: str | None = None) -> None:
        """把一次分析结果加入历史记录面板（方向文案汉化：long→多头等）。"""
        self._history_count += 1
        self._history_panel.append_history(
            symbol, timeframe, bias, time_str=time_str, count=self._history_count
        )

    # ── 设置对话框 ────────────────────────────────────────────────────────
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
            "<p>支持 MT5 多周期（1分~周线）× 多品种（NQ/ES/XAU）</p>"
            "<p>AI 增强诊断（DeepSeek）+ 飞书指令机器人 + 新K线自动分析</p>"
            "<p>仅供学习研究，不构成投资建议。</p>",
        )

    # ── 获取数据（不跑 AI，快速刷新图表）─────────────────────────────────
    def _on_fetch_data(self) -> None:
        """异步加载行情数据（核心优化1/2）。

        拉取 + Footprint + 订单流解析全部在 _FetchThread 子线程完成，
        完成后经 _fetch_done 信号一次性回主线程渲染；防抖定时器 + 全局加载锁
        双重保证快速连续切换只执行最后一次有效请求，不产生堆积。
        """
        # 全局加载锁：加载中直接忽略新触发（防抖已合并 300ms 内的连切）
        if self._loading:
            return
        symbol = self._sym_combo.currentText()
        timeframe = self._current_tf()
        self._fetch_req = (symbol, timeframe)  # 记录请求令牌
        self._fetch_seq += 1
        req_id = self._fetch_seq
        self._loading = True
        self._fetch_btn.setEnabled(False)
        bar_count = self._window_bar_count(timeframe)
        self._set_table_status(
            f"⏳ 数据加载中...（{symbol} {timeframe}，{WINDOW_HOURS}h 窗口，{bar_count} 根）"
        )

        # 【改动点】④K线内存缓存：同一(品种,周期) 60 秒内重复切换命中缓存，
        # 直接渲染无需重新拉取（MT5 拉取为耗时主因）。首次拉取仍走网络。
        key = (symbol, timeframe)
        hit = self._frame_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_S:
            frame, wa = hit[1], hit[2]
            self._fetch_done.emit(frame, wa, "", req_id)
            return

        def _on_worker_done(frame, wa, err: str, rid: int) -> None:
            # 线程结束：释放引用，确保可回收
            if self._fetch_thread is not None:
                self._fetch_thread.deleteLater()
                self._fetch_thread = None
            if rid == req_id and frame is not None and not err:
                self._frame_cache[key] = (time.monotonic(), frame, wa)
            self._fetch_done.emit(frame, wa, err, rid)

        self._fetch_thread = _FetchThread(
            symbol, timeframe, bar_count, self._settings, req_id, parent=self,
        )
        self._fetch_thread.done.connect(_on_worker_done)
        self._fetch_thread.start()

    def _on_fetch_done(self, frame, wa, err: str, req_id: int) -> None:
        """获取数据完成（主线程）：一次性渲染 + 恢复附属功能。"""
        self._fetch_btn.setEnabled(True)
        self._loading = False
        self._switching = False
        # 防竞态：请求序号不匹配 → 丢弃过期响应（快速连切只保留最后一次）
        if req_id != self._fetch_seq:
            return
        # 核心优化4：重载完成后恢复附属功能
        mode = getattr(self._settings.general, "data_source", "mt5")
        if mode != "yfinance":  # yfinance 无 Tick，不重启价格轮询
            self._tick_timer.start(2000)
        self._chart.resume_interactions()
        self._crosshair_suspended = False

        # 加载期间被忽略的最后一次切换：补发（走新一轮防抖，不并发排队）
        if self._pending_switch and self._pending_switch != (
            self._sym_combo.currentText(), self._current_tf()
        ):
            sym, tf = self._pending_switch
            self._pending_switch = None
            if sym in self._symbols:
                self._sym_combo.setCurrentText(sym)
            idx = self._tf_combo.findData(tf)
            if idx >= 0:
                self._tf_combo.setCurrentIndex(idx)
            return  # _on_selector_changed 会启动新一轮防抖加载
        self._pending_switch = None

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

    # ── 提交分析 ──────────────────────────────────────────────────────────
    def _on_analyze(self) -> None:
        # 全局加载锁：数据加载中拒绝分析，避免与分析/渲染竞态
        if self._loading:
            self._set_table_status("⏳ 数据加载中，请稍候再提交分析")
            return
        symbol = self._sym_combo.currentText()
        timeframe = self._current_tf()
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
        if self._fetch_req != (self._sym_combo.currentText(), self._current_tf()):
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
        # 本次分析时间：强制北京时间（Asia/Shanghai，与顶部时钟同一时间源）
        self._analysis_time = beijing_now_str()
        # 填充 5 个标签页
        self._populate_tabs(res.frame, res.wyckoff, res)
        # 历史记录（使用同一分析时间戳）
        bias = res.wyckoff.bias if res.wyckoff is not None else ""
        self._append_history(res.symbol, res.timeframe, bias, res.to_report(), self._analysis_time)
        # 【改动点】需求四：分析完成 → 信号落盘存档 + 刷新回测标签页（只读统计）。
        # 【涉及文件】wkf/gui/main_window.py + wkf/backtest/archive.py + wkf/backtest/statistics.py
        # 【验证方式】分析后 output/history_archive.json 追加记录；回测页刷新计数+1
        try:
            if res.wyckoff is not None:
                from wkf.backtest.archive import append_analysis_record

                append_analysis_record(
                    analysis_time=self._analysis_time,
                    symbol=res.symbol,
                    timeframe=res.timeframe,
                    bias=res.wyckoff.bias,
                    trigger=res.wyckoff.trigger,
                    invalidation=res.wyckoff.invalidation,
                    price=res.wyckoff.price,
                    prob=compute_probabilities(res.wyckoff),
                    ts_open=(res.frame.bars[0].ts_open if res.frame and res.frame.bars else None),
                )
                self._tab_backtest.refresh()
        except Exception:
            pass  # 存档失败不影响主流程
        # 【改动点】高概率行情提示音：综合概率（多/空取大值）> 60% 播放单次提示音。
        if res.wyckoff is not None:
            try:
                prob = compute_probabilities(res.wyckoff)
                if max(prob.get("long", 0), prob.get("short", 0)) > 60:
                    from wkf.util.audio_player import play_alert

                    play_alert(res.symbol)
            except Exception:
                pass
        # 飞书推送：仅分析完成触发；防抖/高亮/日志均在 notifier 内处理
        self._spawn_feishu_push(res, bias)

    def _spawn_feishu_push(self, res: AnalysisResult, bias: str) -> None:
        """分析完成后后台推送飞书（带分析时间/概率/三层结论）。"""
        if res.wyckoff is None:
            return
        try:
            from wkf.notify.feishu_notifier import push_analysis_notice

            wa = res.wyckoff
            prob = compute_probabilities(wa)
            bias_zh = {"long": "多头", "short": "空头", "neutral": "中性"}.get(wa.bias, wa.bias or "")
            va = wa.value_area
            of = wa.orderflow
            va_text = f"价值区域：VA [{va.val:.2f}, {va.vah:.2f}] VPOC {va.vpoc:.2f}" if va else ""
            of_text = (
                f"订单流：Delta {of.delta:+.0f} 活跃方 "
                f"{'买方' if str(of.active_side).lower() == 'buy' else ('卖方' if str(of.active_side).lower() == 'sell' else of.active_side)}"
                f" 阶段 {'吸收' if str(of.reversal_stage).lower() == 'absorption' else of.reversal_stage}"
                if of else ""
            )
            symbol, timeframe = res.symbol, res.timeframe

            def _work() -> None:
                push_analysis_notice(
                    symbol=symbol,
                    timeframe=timeframe,
                    analysis_time=self._analysis_time,
                    prob=prob,
                    bias_zh=bias_zh,
                    price=wa.price,
                    va_text=va_text,
                    of_text=of_text,
                    settings=self._settings,
                )

            threading.Thread(target=_work, name="wkf-feishu-push", daemon=True).start()
        except Exception:
            pass  # 推送失败不影响主流程

    # ── K线明细表格状态 ───────────────────────────────────────────────────
    def _set_table_status(self, text: str) -> None:
        """数据标签页顶部状态行。"""
        self._table_status.setText(text)

    def toPlainText(self) -> str:
        """兼容方法：返回表格文本（供测试/外部读取，保持原文本表格语义）。"""
        return self._tab_data.toPlainText()

    # ── 标签页内容渲染（委托子控件）──────────────────────────────────────
    def _populate_tabs(self, frame, wa, res) -> None:
        # K线明细表格渲染样式：「其他设置」可切换新版表格UI / 旧版纯文本（一键回滚）
        style = getattr(self._settings.general, "table_style", "new")
        if style == "old":
            self._tab_data.set_plain_mode(True, self._tab_data.render_plain(frame))
        else:
            self._tab_data.set_plain_mode(False)
            self._tab_data.populate(frame)
        # 【改动点】V1.3.3：快照/诊断面板备注当前数据源来源（区分行情渠道）。
        ds_label = self._data_source_label()
        # 快照预览（底部展示生成时间，北京时间）
        self._tab_snapshot.render(
            frame, wa, generated_time=beijing_now_str(), data_source=ds_label
        )
        # 诊断面板（顶部展示诊断生成时间，北京时间）
        self._tab_diagnosis_panel.render(
            wa, generated_time=beijing_now_str(), data_source=ds_label
        )
        # 决策面板（富文本四段 + 概率总结；红色粗体结论）
        self._tab_decision_panel.render(wa, analysis_time=self._analysis_time)
        # 提交分析联动：在问AI面板自动追加一条完整分析日志（推理步骤 + Token 消耗）
        title = f"{frame.symbol} {frame.timeframe} 分析日志"
        self._tab_ai.append_log(title, self._render_ai_tab(res, wa))

    # ── 旧渲染方法（保留为兼容转发；子控件已承载渲染逻辑）────────────────
    def _render_data_tab(self, frame) -> str:
        """兼容方法：数据标签页纯文本（委托子控件）。"""
        return self._tab_data.render_plain(frame)

    def _render_snapshot_tab(self, frame, wa) -> str:
        """兼容方法：快照文本（委托子控件）。"""
        return self._tab_snapshot._build_text(frame, wa)

    def _render_diagnosis_tab(self, frame, wa) -> str:
        """兼容方法：诊断文本（委托子控件）。"""
        return self._tab_diagnosis_panel._build_text(wa, generated_time=beijing_now_str())

    def _render_decision_tab(self, wa) -> str:
        """兼容方法：决策 HTML（委托子控件）。"""
        return self._tab_decision_panel._build_html(wa, analysis_time=self._analysis_time)

    def _compute_probabilities(self, wa) -> dict:
        """兼容方法：行情概率测算（委托 decision_panel 纯函数）。"""
        return compute_probabilities(wa)

    def _save_snapshot(self) -> None:
        """保存当前行情快照为文件（文件名嵌入北京时间戳）。"""
        self._tab_snapshot.save(parent=self)

    def _populate_data_table(self, frame) -> None:
        """兼容方法：填充 K 线明细表格（委托子控件）。"""
        self._tab_data.populate(frame)

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
        """AI 回复到达（主线程）：原地更新"思考中"占位为正式回复。

        API Key 异常 / 调用失败时弹窗提示（不崩溃、不卡死 UI）。
        """
        self._ai_busy = False
        self._tab_ai.send_btn.setEnabled(True)
        is_error = reply.startswith("❌") or "未配置" in reply or "API" in reply and "失败" in reply
        self._tab_ai.update_last_ai(
            f"<span style='color:#e6edf3'>{html.escape(reply).replace(chr(10), '<br>')}</span>"
        )
        if is_error:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self, "AI 调用异常",
                f"{reply}\n\n请在「⚙ 设置 → 🤖 AI 模型设置」中检查 API Key / 接口地址是否正确。",
            )

    # ── 自动分析：持续跟踪，等待新 K 线收盘后自动重新分析 ─────────────────
    def _on_auto_toggle(self, checked: bool) -> None:
        self._auto_active = checked
        if checked:
            symbol = self._sym_combo.currentText()
            timeframe = self._current_tf()
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
        timeframe = self._current_tf()
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
        """测量 MT5 服务器时钟与真实 UTC 的偏移（毫秒）。"""
        try:
            import MetaTrader5 as mt5
            from wkf.data.mt5_source import ensure_mt5_initialized, resolve_mt5_symbol

            if not ensure_mt5_initialized(mt5):
                return 0
            sym = resolve_mt5_symbol(self._sym_combo.currentText())
            now = int(time.time())
            tks = mt5.copy_ticks_range(sym, now - 120, now + 4 * 3600, mt5.COPY_TICKS_ALL)
            if tks is not None and len(tks) > 0:
                return int(tks[-1]["time_msc"] - now * 1000)
        except Exception:
            pass
        return 0

    def _update_clock(self) -> None:
        """顶部北京时钟刷新：强制 Asia/Shanghai，HH:MM:SS，每秒更新。"""
        try:
            from wkf.util.timefmt import beijing_now

            self._clock_label.setText(f"🕐 {beijing_now().strftime('%H:%M:%S')}")
        except Exception:
            pass  # 时钟异常不影响主流程

    def _update_kline_status(self) -> None:
        """K线收盘倒计时：1 秒定时器秒级实时刷新（MT5 服务器时钟偏移对齐）。"""
        # 【改动点】V1.3.3：切换/加载中不覆盖状态栏的加载提示文案
        # （否则 1 秒定时器会用旧 K 线倒计时覆盖「品种数据加载中/周期重构渲染中」）。
        if self._loading or self._switching or self._analysis_busy:
            return
        symbol = self._sym_combo.currentText()
        timeframe = self._current_tf()
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
        period_ms = minutes * 60 * 1000  # 单根K线周期
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

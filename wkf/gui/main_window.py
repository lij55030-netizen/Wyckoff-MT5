"""WKF 主窗口：图表 + 控制 + 分析结果面板（数据/快照/诊断/决策/问AI）。"""
from __future__ import annotations

import datetime
import math
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wkf.config.settings import load_settings
from wkf.data.base import KlineFrame
from wkf.gui.chart_widget import WkfChart
from wkf.gui.settings_dialogs import AIModelDialog, FeishuDialog, IndicatorDialog
from wkf.orchestrator.runner import (
    AnalysisResult,
    fetch_frame_only,
    get_latest_bar_ts,
    run_analysis,
)

SYMBOLS = ["NQ1!", "ES1!", "GC1!"]
TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]
TF_MINUTES = {"5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}


class MainWindow(QMainWindow):
    # 工作线程 → UI 线程信号（PyQt6 线程安全回调）
    _fetch_done = pyqtSignal(object, object, str)  # frame, wyckoff, err
    _analysis_done = pyqtSignal(object)  # AnalysisResult

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
        self._tab_data = QPlainTextEdit()
        self._tab_data.setReadOnly(True)
        self._tab_data.setMaximumBlockCount(2000)
        tabs.addTab(self._tab_data, "📊 数据")

        self._tab_snapshot = QPlainTextEdit()
        self._tab_snapshot.setReadOnly(True)
        self._tab_snapshot.setMaximumBlockCount(2000)
        tabs.addTab(self._tab_snapshot, "📸 快照")

        self._tab_diagnosis = QPlainTextEdit()
        self._tab_diagnosis.setReadOnly(True)
        self._tab_diagnosis.setMaximumBlockCount(2000)
        tabs.addTab(self._tab_diagnosis, "🔍 诊断")

        self._tab_decision = QPlainTextEdit()
        self._tab_decision.setReadOnly(True)
        self._tab_decision.setMaximumBlockCount(2000)
        tabs.addTab(self._tab_decision, "🎯 决策")

        self._tab_ai = QPlainTextEdit()
        self._tab_ai.setReadOnly(True)
        self._tab_ai.setMaximumBlockCount(3000)
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
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_check_kline)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_kline_status)
        self._status_timer.start(5000)

        # 启动后立即拉一次数据 + 状态
        self._on_fetch_data()

    def _append_history(self, symbol: str, timeframe: str, bias: str, report: str) -> None:
        """把一次分析结果加入历史记录面板。"""
        import datetime

        self._history_count += 1
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{self._history_count}] {ts} {symbol} {timeframe}"
        if bias:
            line += f" → {bias}"
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
        self._fetch_btn.setEnabled(False)
        self._tab_data.setPlainText(f"⏳ 获取 {symbol} {timeframe} 数据...")

        def _work() -> None:
            frame, wa, err = fetch_frame_only(
                symbol, timeframe, settings=self._settings
            )
            self._fetch_done.emit(frame, wa, err)

        threading.Thread(target=_work, name="wkf-fetch", daemon=True).start()

    def _on_fetch_done(self, frame, wa, err: str) -> None:
        """获取数据完成（主线程）。"""
        self._fetch_btn.setEnabled(True)
        if err:
            self._tab_data.setPlainText(f"❌ 获取失败: {err}")
            return
        if frame is not None:
            self._chart.set_frame(frame)
            self._last_bar_ts = frame.bars[0].ts_open
        # 仅当尚无 AI 分析结果时才填充各页，避免覆盖已完成的 AI 诊断
        if frame is not None and not getattr(self, "_has_ai_result", False):
            self._populate_tabs(frame, wa, None)
            self._tab_data.setPlainText(
                f"✅ 数据已更新（未跑 AI，可点「📝 提交分析」）\n\n" + self._render_data_tab(frame)
            )

    def _on_analyze(self) -> None:
        symbol = self._sym_combo.currentText()
        timeframe = self._tf_combo.currentText()
        self._analyze_btn.setEnabled(False)
        self._tab_data.setPlainText(f"⏳ 正在分析 {symbol} {timeframe} ...")

        def _work() -> None:
            res = run_analysis(symbol, timeframe, settings=self._settings, with_ai=True)
            self._analysis_done.emit(res)

        self._analysis_busy = True
        threading.Thread(target=_work, name="wkf-analysis", daemon=True).start()

    def _on_analysis_done(self, res: AnalysisResult) -> None:
        """分析完成（主线程）。"""
        self._analyze_btn.setEnabled(True)
        self._analysis_busy = False
        self._has_ai_result = True
        if res.error:
            self._tab_data.setPlainText(f"❌ 分析失败: {res.error}")
            return
        if res.frame is not None:
            self._chart.set_frame(res.frame)
            self._last_bar_ts = res.frame.bars[0].ts_open
        # 填充 5 个标签页
        self._populate_tabs(res.frame, res.wyckoff, res)
        # 历史记录
        bias = res.wyckoff.bias if res.wyckoff is not None else ""
        self._append_history(res.symbol, res.timeframe, bias, res.to_report())

    # ── 标签页内容渲染 ────────────────────────────────────────────────────
    def _populate_tabs(self, frame, wa, res) -> None:
        self._tab_data.setPlainText(self._render_data_tab(frame))
        self._tab_snapshot.setPlainText(self._render_snapshot_tab(frame, wa))
        self._tab_diagnosis.setPlainText(self._render_diagnosis_tab(frame, wa))
        self._tab_decision.setPlainText(self._render_decision_tab(wa))
        self._tab_ai.setPlainText(self._render_ai_tab(res, wa))

    def _render_data_tab(self, frame) -> str:
        """数据标签页：分析了哪些数据（K线明细表）。"""
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

    def _render_decision_tab(self, wa) -> str:
        """决策标签页：结果是什么（倾向/触发/失效/概率）。"""
        if wa is None:
            return "未分析"
        bias_zh = {"long": "偏多", "short": "偏空", "neutral": "中性观望"}.get(wa.bias, wa.bias)
        lines = [
            "=== 交易决策 ===",
            "",
            f"🎯 倾向:   {bias_zh}",
            f"📈 入场触发: {wa.trigger}",
            f"🚫 失效条件: {wa.invalidation}",
        ]
        if wa.orderflow is not None:
            of = wa.orderflow
            lines += [
                "",
                "── 订单流支撑 ──",
                f"活跃方: {of.active_side} | 反转阶段: {of.reversal_stage}",
                f"失衡: {len(of.imbalances)} 处 | 堆叠: {len(of.stacked_imbalances)} 组",
            ]
        if wa.notes:
            lines += ["", "── 备注 ──", *[f"· {n}" for n in wa.notes]]
        return "\n".join(lines)

    def _render_ai_tab(self, res, wa) -> str:
        """问AI标签页：AI 分析结论 + 概率。"""
        if res is None or res.ai_diagnosis is None:
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
        if res.usage:
            lines += ["", f"── Token 用量 ──", str(res.usage)]
        return "\n".join(lines)

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
                f"♾ 持续跟踪中 · 当前K线 {remain} 后收盘"
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

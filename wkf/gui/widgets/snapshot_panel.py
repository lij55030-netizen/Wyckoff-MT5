"""快照面板（原 main_window 快照标签页拆分）。

【改动点】需求一.1：架构重构——主窗口渐进式拆分。
本文件承载「快照」标签页：保存按钮 + 预览正文 + 底部生成时间；
提供 render() 渲染快照文本、save() 保存到 output/snapshot_YYYYMMDD_HHMMSS.txt。
【涉及文件】wkf/gui/widgets/snapshot_panel.py（新增，自 main_window 抽出）
【验证方式】点「保存快照」→ output/snapshot_*.txt（文件名含北京时间戳）；
            预览底部显示快照生成时间。
"""
from __future__ import annotations

import math

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SnapshotPanel(QWidget):
    """快照标签页：保存按钮 + 预览正文 + 底部生成时间。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        self.save_btn = QPushButton("💾 保存快照")
        self.save_btn.setToolTip("将当前行情快照保存为文件（文件名含北京时间戳）")
        bar.addWidget(self.save_btn)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setMaximumBlockCount(2000)
        layout.addWidget(self.text_view)
        self.time_label = QLabel("快照生成时间：--")
        self.time_label.setStyleSheet("color:#8b949e;font-size:12px;")
        layout.addWidget(self.time_label)

    # ── 渲染 ──────────────────────────────────────────────────────────────
    def render(self, frame, wa, generated_time: str = "", data_source: str = "") -> None:
        """渲染快照预览；generated_time 为快照生成时间，data_source 为行情数据源。"""
        self.text_view.setPlainText(self._build_text(frame, wa, data_source=data_source))
        if generated_time:
            self.time_label.setText(f"快照生成时间：{generated_time}")

    def _build_text(self, frame, wa, data_source: str = "") -> str:
        """快照标签页文本：当前行情快照。"""
        if frame is None or not frame.bars:
            return "无数据"
        latest = frame.bars[0]
        ind = frame.indicators
        of = frame.orderflow
        lines = [
            f"=== 行情快照（{frame.symbol} {frame.timeframe}）===",
            "",
            # 【改动点】V1.3.3：快照内备注当前数据源来源（区分行情渠道）。
            f"数据源:   {data_source or 'MT5实盘数据源'}",
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
                # 【改动点】快照订单流区顶部固定风险提示（与决策面板同文案）
                "⚠ 订单流由 MT5 Tick 数据近似换算生成，并非交易所原始盘口订单流，仅用于威科夫结构定性研判，不建议作为高频短线交易依据。",
                f"Delta:   {of.delta[0]:+.0f}" if not math.isnan(of.delta[0]) else "Delta:  -",
                f"累积Δ:   {of.cumulative_delta[0]:+.0f}",
                f"POC:     {of.poc_price[0]:.2f}",
                f"VA:      [{of.val[0]:.2f}, {of.vah[0]:.2f}]",
            ]
        return "\n".join(lines)

    # ── 保存 ──────────────────────────────────────────────────────────────
    def save(self, parent=None) -> None:
        """保存当前行情快照为文件（文件名嵌入北京时间戳）。"""
        try:
            from wkf.config.settings import SETTINGS_JSON_PATH
            from wkf.util.timefmt import beijing_now_str

            out_dir = SETTINGS_JSON_PATH.parent.parent / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = beijing_now_str().replace("-", "").replace(":", "").replace(" ", "_")
            path = out_dir / f"snapshot_{ts}.txt"
            content = self.text_view.toPlainText()
            if not content.strip():
                content = self.time_label.text()
            path.write_text(
                f"WKF 行情快照\n生成时间：{beijing_now_str()}\n{'=' * 40}\n{content}",
                encoding="utf-8",
            )
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.information(parent, "快照已保存", f"已保存至：\n{path}")
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(parent, "保存失败", f"快照保存失败：{exc}")

    def toPlainText(self) -> str:
        return self.text_view.toPlainText()

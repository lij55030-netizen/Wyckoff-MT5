"""回测标签页（P1 真实胜率推演，只读复盘）。

【改动点】P1 迭代：废弃高概率占比伪胜率，展示真实交易胜率/整体盈亏比/
最大连续亏损/净值曲线，并支持逐笔交易明细导出 CSV 复盘核验。
仅做历史信号复盘推演，禁止修改历史分析结论、禁止实盘交易。
【涉及文件】wkf/gui/widgets/backtest_panel.py + wkf/backtest/statistics.py
【验证方式】执行若干次「提交分析」后回测页显示真实胜率/净值曲线；
            导出明细 CSV 与模拟推演结果一致。
"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wkf.backtest.archive import load_archive
from wkf.backtest.statistics import (
    compute_backtest,
    export_trades,
    render_summary_text,
)


class BacktestPanel(QWidget):
    """回测标签页：统计表格 + 摘要文本 + 推演根数选择 + 明细导出（只读）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("📈 信号回测（只读复盘）"))
        bar.addStretch(1)
        bar.addWidget(QLabel("推演K线"))
        self.lookahead_combo = QComboBox()
        self.lookahead_combo.addItems(["5", "10", "15"])
        self.lookahead_combo.setCurrentText("10")
        self.lookahead_combo.setFixedWidth(56)
        bar.addWidget(self.lookahead_combo)
        self.export_btn = QPushButton("💾 导出明细")
        self.export_btn.setEnabled(False)
        bar.addWidget(self.export_btn)
        self.refresh_btn = QPushButton("🔄 刷新统计")
        bar.addWidget(self.refresh_btn)
        layout.addLayout(bar)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["统计项", "数值", "说明", "备注"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget{background-color:#0f1419;color:#e6edf3;"
            "alternate-background-color:#161d26;font-size:13px;border:1px solid #2a3442;}"
            "QHeaderView::section{background-color:#1e2632;color:#8b949e;"
            "border:1px solid #2a3442;padding:4px 8px;font-weight:bold;font-size:13px;}"
        )
        layout.addWidget(self.table, stretch=1)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(
            "color:#8b949e;font-size:12px;font-family:Consolas,monospace;"
        )
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.summary_label)
        self._last_trades: list = []

        self.refresh_btn.clicked.connect(self.refresh)
        self.lookahead_combo.currentTextChanged.connect(lambda _: self.refresh())
        self.export_btn.clicked.connect(self._export)

    def refresh(self) -> None:
        """重新读取存档并刷新统计（只读，不改写任何数据）。"""
        records = load_archive()
        if not records:
            self.table.setRowCount(0)
            self.export_btn.setEnabled(False)
            self._last_trades = []
            self.summary_label.setText("暂无历史分析记录。执行「📝 提交分析」后自动记录，可回测统计。")
            return
        lookahead = int(self.lookahead_combo.currentText())
        s = compute_backtest(records, lookahead=lookahead)
        self._last_trades = s.trades
        self.export_btn.setEnabled(bool(s.trades))

        rows = [
            ("存档信号总数", str(s.total_records), "历史分析存档内全部信号", ""),
            (
                "可推演交易数",
                str(s.evaluated_trades),
                "成功对齐K线完成推演的多/空单",
                f"跳过 {s.skipped} 笔（旧记录缺时间戳/方向）",
            ),
            (
                "真实交易胜率",
                f"{s.win_rate}%",
                "盈利单 / (盈利+亏损) 单",
                f"赢 {s.wins} / 输 {s.losses} / 平 {s.flats}",
            ),
            (
                "整体盈亏比",
                str(s.profit_factor),
                "平均盈利 / 平均亏损绝对值",
                f"平均盈利 +{s.avg_win}% / 平均亏损 {s.avg_loss}%",
            ),
            ("最大连续亏损", f"{s.max_consecutive_losses} 笔", "按分析时间排序的连续亏损", ""),
            ("累计净值", f"{s.total_pnl:+.2f}%", "逐笔盈亏累计", ""),
            (
                "净值曲线",
                " → ".join(f"{v:+.2f}" for v in s.equity_curve[:30])
                + (" ..." if len(s.equity_curve) > 30 else ""),
                "累计盈亏%序列（最多显示30点）",
                "",
            ),
        ]
        for k, v in sorted(s.by_symbol.items()):
            rows.append((f"按品种 · {k}", str(v), "该品种推演交易数", ""))
        for k, v in sorted(s.by_timeframe.items()):
            rows.append((f"按周期 · {k}", str(v), "该周期推演交易数", ""))
        for k, v in sorted(s.by_direction.items()):
            dir_zh = {"long": "多头", "short": "空头"}.get(k, k)
            rows.append((f"按方向 · {dir_zh}", str(v), "该方向推演交易数", ""))
        if s.errors:
            rows.append(
                ("数据获取告警", str(len(s.errors)), "K线拉取失败记录数", s.errors[0][:60])
            )

        self.table.setRowCount(len(rows))
        for i, (name, value, note, remark) in enumerate(rows):
            for col, txt in enumerate((name, value, note, remark)):
                item = QTableWidgetItem(txt)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, col, item)
        self.table.resizeColumnsToContents()
        self.summary_label.setText(render_summary_text(s))

    def _export(self) -> None:
        """逐笔交易明细导出 CSV（供复盘核验）。"""
        if not self._last_trades:
            return
        default_name = f"wkf_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出逐笔交易明细", default_name, "CSV 文件 (*.csv)"
        )
        if not path:
            return
        try:
            n = export_trades(self._last_trades, path)
            self.summary_label.setText(
                f"✅ 已导出 {n} 笔交易明细至:\n{path}\n\n"
                f"{render_summary_text(compute_backtest(load_archive(), lookahead=int(self.lookahead_combo.currentText())))}"
            )
        except Exception as exc:
            self.summary_label.setText(f"导出失败: {exc}")

    def toPlainText(self) -> str:
        return self.summary_label.text()

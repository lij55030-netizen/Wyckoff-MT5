"""K线明细表格控件（原 main_window._KlineTableWidget 拆分）。

【改动点】需求一.1：架构重构——主窗口超大文件渐进式拆分。
本文件承载「数据标签页」子控件（状态行 + 表格 + 旧版纯文本回滚视图），
仅做前端展示渲染，不含任何行情数据/指标计算/业务逻辑。
【涉及文件】wkf/gui/widgets/kline_table.py（新增，自 main_window 抽出）
【验证方式】python -m unittest discover tests；tools/test_v24_features.py 表格 UI 断言 8/8；
            旧版纯文本回滚开关（设置→其他设置）仍可用。
"""
from __future__ import annotations

import datetime
import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class KlineTableWidget(QWidget):
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

        # 旧版纯文本视图（默认隐藏）：「其他设置」表格样式一键回滚开关使用
        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setMaximumBlockCount(2000)
        self._text_view.hide()
        layout.addWidget(self._text_view)

    def set_plain_mode(self, plain: bool, text: str = "") -> None:
        """表格渲染模式切换：plain=True 显示旧版纯文本表格，False 显示新版 QTableWidget。"""
        if plain:
            if text:
                self._text_view.setPlainText(text)
            self._text_view.show()
            self.table.hide()
        else:
            self._text_view.hide()
            self.table.show()

    def toPlainText(self) -> str:
        """兼容方法：返回当前可见模式下的文本（供测试/外部读取）。"""
        if self._text_view.isVisible():
            return self._text_view.toPlainText()
        lines = [self.status_label.text()]
        lines.append("序号 | 时间 | 开盘 | 最高 | 最低 | 收盘 | 涨跌 | 成交量 | RSI | VWAP | Δ")
        for r in range(self.table.rowCount()):
            row = [
                self.table.item(r, c).text() if self.table.item(r, c) else ""
                for c in range(self.table.columnCount())
            ]
            lines.append(" | ".join(row))
        return "\n".join(lines)

    # ── 表格填充（原 MainWindow._populate_data_table 迁移）─────────────────
    def populate(self, frame) -> None:
        """填充 K 线明细表格（最近 20 根，字段与原表格完全一致）。

        展示规则（配色沿用项目绿涨红跌）：
          · 涨跌列: 阳线 ↑绿 / 阴线 ↓红（移除文字）
          · 成交量: 对比近 20 根均值, ≥1.2x 放量🔺 / ≤0.8x 缩量🔻 / 常态⚫
          · RSI 列: >70 超买⚠️ / 30~70 常态●灰 / <30 超卖🔵
          · Δ 列: 正数 ↑绿 / 负数 ↓红 / 0 值 —灰
          · 收盘/VWAP/RSI 数值加粗高亮
        """
        if frame is None or not frame.bars:
            self.table.setRowCount(0)
            return
        ind = frame.indicators
        bars = frame.bars[:20]  # 与旧表格一致: 最近 20 根
        vols = [b.volume for b in bars]
        mean_vol = sum(vols) / len(vols) if vols else 0.0

        n = len(bars)
        self.table.setRowCount(n)
        for i, b in enumerate(bars):
            yang = b.close >= b.open
            ts = datetime.datetime.fromtimestamp(b.ts_open / 1000).strftime("%m-%d %H:%M")
            rsi = ind.rsi14[i] if i < len(ind.rsi14) and not math.isnan(ind.rsi14[i]) else None
            vwap = ind.vwap[i] if i < len(ind.vwap) and not math.isnan(ind.vwap[i]) else None
            # Δ 差值（修复长期空白/0 故障）：改为「当期收盘价 - 前一根收盘价」的价格差值，
            # 表格首行（最新K线）不计算填横线；随行情刷新实时重算。
            # bars 为新→旧排列，bars[i] 的前一根（时间更早）是 bars[i+1]。
            if i == 0 or i + 1 >= len(bars):
                delta = None
            else:
                delta = b.close - bars[i + 1].close

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
            # Δ 差值（价格差，2 位小数）：正数 ↑绿 / 负数 ↓红 / 0 或缺失 —灰
            if delta is None:
                d_txt, d_color = "—", "#8b949e"
            elif abs(delta) < 0.005:
                d_txt, d_color = "—", "#8b949e"
            elif delta > 0:
                d_txt, d_color = f"↑{delta:+.2f}", "#22c55e"
            else:
                d_txt, d_color = f"↓{delta:+.2f}", "#ef4444"

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
                self.table.setItem(i, col, item)

    # ── 旧版纯文本数据表格（兼容回滚视图）─────────────────────────────────
    def render_plain(self, frame) -> str:
        """数据标签页纯文本（旧版表格样式，供 set_plain_mode 回滚使用）。"""
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
            ts = datetime.datetime.fromtimestamp(b.ts_open / 1000).strftime("%m-%d %H:%M")
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

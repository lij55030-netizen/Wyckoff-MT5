"""历史记录面板（原 main_window 左侧历史列表拆分）。

【改动点】需求一.1：架构重构——主窗口渐进式拆分。
本文件承载「分析历史」面板：标题 + 只读历史列表（QPlainTextEdit），
封装 append_history（含北京时区时间戳、方向汉化、自动滚动到底部）。
【涉及文件】wkf/gui/widgets/history_panel.py（新增，自 main_window 抽出）
【验证方式】执行分析后左侧历史列表新增一行 [n] 北京时间 symbol tf → 方向；
            超过 500 条自动裁剪最旧记录。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class HistoryPanel(QWidget):
    """分析历史面板：标题 + 只读历史列表。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QLabel("📋 分析历史"))
        self._history_list = QPlainTextEdit()
        self._history_list.setReadOnly(True)
        self._history_list.setMaximumBlockCount(500)
        self._history_list.setFixedWidth(170)
        layout.addWidget(self._history_list)

    def append_history(
        self,
        symbol: str,
        timeframe: str,
        bias: str,
        time_str: str | None = None,
        count: int = 0,
    ) -> str:
        """追加一条历史记录，返回完整行文本。

        time_str: 本次分析时间（年月日时分秒，与决策面板/飞书推送统一）；
        未传则取当前北京时间。count: 累计序号（由外部维护，保证单调递增）。
        """
        from wkf.util.timefmt import beijing_now_str

        bias_zh = {"long": "多头", "short": "空头", "neutral": "中性"}.get(bias, bias)
        ts = time_str or beijing_now_str()
        # 【改动点】V1.3.3：每条记录前置时间标签（YYYY-MM-DD HH:mm:ss）。
        line = f"{ts} [{count}] {symbol} {timeframe}"
        if bias_zh:
            line += f" → {bias_zh}"
        self._history_list.appendPlainText(line)
        self._history_list.verticalScrollBar().setValue(
            self._history_list.verticalScrollBar().maximum()
        )
        return line

    def toPlainText(self) -> str:
        return self._history_list.toPlainText()

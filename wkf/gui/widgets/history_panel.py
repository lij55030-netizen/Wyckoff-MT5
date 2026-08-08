"""分析日志面板（V3.0 改版，原「分析历史」）。

- 标题「分析日志」+ 「💾 保存日志」按钮；
- 带圈序号 ①-⑩，最多 10 条，超过自动删除最旧一条；
- 分析结果识别多空：中文汉字加粗着色（多头=绿 / 空头=红 / 中性=灰）；
- 仅本次运行内存保留：程序关闭自动清除，不落盘持久化。
"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# 带圈序号（1-10）
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
MAX_LOGS = 10
_COLOR = {"long": "#3ec252", "short": "#f04e4a", "neutral": "#8b949e"}
_LABEL = {"long": "多头", "short": "空头", "neutral": "中性"}


class HistoryPanel(QWidget):
    """分析日志面板：富文本日志 + 保存按钮（最多 10 条，仅内存保留）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        bar.setSpacing(8)  # 【改动点】V3.0：标题与按钮间隔 1 字符空隙，间距自然
        bar.addWidget(QLabel("📋 分析日志"))
        self.save_btn = QPushButton("💾 保存日志")
        self.save_btn.setFixedWidth(84)
        self.save_btn.setToolTip("将当前分析日志导出为文本文件（含时间戳）")
        bar.addWidget(self.save_btn)
        layout.addLayout(bar)

        # 兼容旧引用：_history_list 为富文本视图（支持加粗着色）
        self._history_list = QTextEdit()
        self._history_list.setReadOnly(True)
        # 【改动点】V3.0：侧边栏改为最小宽度限制（可左右拖拽调宽，不能拖没）
        self._history_list.setMinimumWidth(170)
        # 【改动点】V3.0：左侧分析日志背景改为 #082C32（单点改动），
        # 文字颜色/边框/字体保持不变。
        self._history_list.setStyleSheet(
            "QTextEdit{background-color:#082C32;color:#e6edf3;"
            "border:1px solid #2a3442;}"
        )
        layout.addWidget(self._history_list)
        self.save_btn.clicked.connect(self.save_log)

        self._logs: list[dict] = []  # 内存日志（新日志追加末尾，超 10 删最旧）

    def append_history(
        self,
        symbol: str,
        timeframe: str,
        bias: str,
        time_str: str | None = None,
        count: int = 0,
    ) -> str:
        """追加一条分析日志（最多 10 条，超过自动删除最旧一条）。"""
        from wkf.util.timefmt import beijing_now_str

        ts = time_str or beijing_now_str()
        self._logs.append(
            {"symbol": symbol, "timeframe": timeframe, "bias": bias, "ts": ts}
        )
        if len(self._logs) > MAX_LOGS:
            self._logs.pop(0)  # 自动删除最旧一条
        self._render()
        return f"{ts} {symbol} {timeframe}"

    def _render(self) -> None:
        """渲染富文本日志：带圈序号 + 时间 + 品种周期 + 多空中文加粗着色。"""
        html = []
        for i, rec in enumerate(self._logs):
            n = _CIRCLED[i]
            color = _COLOR.get(str(rec["bias"]), _COLOR["neutral"])
            label = _LABEL.get(str(rec["bias"]), str(rec["bias"]))
            html.append(
                f'<div style="font-size:12px;color:#e6edf3;">'
                f'{n} {rec["ts"]} {rec["symbol"]} {rec["timeframe"]} → '
                f'<span style="color:{color};font-weight:bold;">{label}</span></div>'
            )
        self._history_list.setHtml("<br>".join(html))
        self._history_list.verticalScrollBar().setValue(
            self._history_list.verticalScrollBar().maximum()
        )

    def save_log(self) -> None:
        """保存日志到 output/analysis_log_时间戳.txt（纯文本，含多空中文标注）。"""
        try:
            from wkf.config.settings import SETTINGS_JSON_PATH

            out_dir = SETTINGS_JSON_PATH.parent.parent / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = out_dir / f"analysis_log_{ts}.txt"
            lines = []
            for i, rec in enumerate(self._logs):
                label = _LABEL.get(str(rec["bias"]), str(rec["bias"]))
                lines.append(
                    f"{_CIRCLED[i]} {rec['ts']} {rec['symbol']} "
                    f"{rec['timeframe']} → {label}"
                )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            QMessageBox.information(self, "日志已保存", f"已保存至：\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", f"日志保存失败：{exc}")

    def toPlainText(self) -> str:
        return self._history_list.toPlainText()

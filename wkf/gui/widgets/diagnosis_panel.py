"""诊断面板（原 main_window 诊断标签页渲染逻辑拆分）。

【改动点】需求一.1：架构重构——主窗口渐进式拆分。
本文件承载「诊断」标签页：顶部诊断生成时间（北京时间）+ 威科夫三层推理文本。
仅做渲染，不改变任何分析逻辑。
【涉及文件】wkf/gui/widgets/diagnosis_panel.py（新增，自 main_window 抽出）
【验证方式】打开诊断标签可见顶部生成时间，且与决策面板时间一致。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class DiagnosisPanel(QWidget):
    """诊断标签页：顶部生成时间 + 威科夫三层推理文本。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setMaximumBlockCount(2000)
        layout.addWidget(self.text_view)

    def render(self, wa, generated_time: str = "", data_source: str = "") -> None:
        """渲染诊断面板。generated_time 为诊断生成时间，data_source 为行情数据源。"""
        self.text_view.setPlainText(
            self._build_text(wa, generated_time, data_source=data_source)
        )

    def _build_text(self, wa, generated_time: str = "", data_source: str = "") -> str:
        """诊断标签页文本：为什么这么分析（威科夫三层推理）。"""
        if wa is None:
            return "未分析"
        lines = [
            f"🔍 诊断生成时间：{generated_time}",
            # 【改动点】V1.3.3：诊断报告内备注当前数据源来源（区分行情渠道）。
            f"数据源：{data_source or 'MT5实盘数据源'}",
            "",
        ]
        lines.append(wa.render_text())
        return "\n".join(lines)

    def toPlainText(self) -> str:
        return self.text_view.toPlainText()

"""诊断面板（原 main_window 诊断标签页渲染逻辑拆分）。

【改动点】需求一.1：架构重构——主窗口渐进式拆分。
本文件承载「诊断」标签页：顶部诊断生成时间（北京时间）+ 威科夫三层推理文本。
仅做渲染，不改变任何分析逻辑。
【涉及文件】wkf/gui/widgets/diagnosis_panel.py（新增，自 main_window 抽出）
【验证方式】打开诊断标签可见顶部生成时间，且与决策面板时间一致。
"""
from __future__ import annotations

import html

from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

# 【改动点】V3.0 修复 Qt 日志框 BUG：背景 #0f1b19（与上方 K 线图表一致）+
# 深色行情边框 + 主体文字浅灰白。彩色日志分级逻辑不变。
LOG_EDIT_STYLE = (
    "QTextEdit{background-color:#0f1b19;color:#d0d5db;"
    "border:1px solid #2a3442;font-size:13px;"
    "font-family:'Microsoft YaHei UI',Consolas,monospace;}"
)


class DiagnosisPanel(QWidget):
    """诊断标签页：顶部生成时间 + 威科夫三层推理文本。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setStyleSheet(LOG_EDIT_STYLE)
        layout.addWidget(self.text_view)

    def render(self, wa, generated_time: str = "", data_source: str = "") -> None:
        """渲染诊断面板。generated_time 为诊断生成时间，data_source 为行情数据源。"""
        self._render_colored(
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

    def _render_colored(self, text: str) -> None:
        """彩色日志渲染：正常白色 / 成功绿色 / 警告黄色 / 错误红色 / 标题加粗。"""
        parts = []
        for line in text.splitlines():
            if not line.strip():
                parts.append("")
                continue
            esc = html.escape(line)
            if "❌" in line or "错误" in line or "失败" in line:
                color = "#f04e4a"   # 错误红
            elif "⚠" in line or "警告" in line or "风险" in line:
                color = "#f5b942"   # 警告黄
            elif "✅" in line or "成功" in line:
                color = "#3ec252"   # 成功绿
            elif line.startswith(("①", "②", "③", "④", "⑤", "⑥", "🔍", "──")):
                color = "#e6edf3"   # 标题：加粗白色
                parts.append(f'<span style="color:{color};font-weight:bold;">{esc}</span>')
                continue
            else:
                color = "#d0d5db"   # 正常：浅灰白
            parts.append(f'<span style="color:{color};">{esc}</span>')
        self.text_view.setHtml("<br>".join(parts))

    # 【改动点】V3.1 内容分区：AI 完整思考过程、盘面拆解、逐步研判 →
    # 统一输出至【诊断】标签页（追加在威科夫推理之后，不覆盖）。
    def append_ai_reasoning(self, reasoning: str = "", ai: dict | None = None) -> None:
        parts: list[str] = []
        if ai:
            parts.append(
                "<b style='color:#3b82f6;'>🤖 AI 盘面拆解（关键信号）</b>"
            )
            for s in (ai.get("key_signals") or []):
                parts.append(f"· {html.escape(str(s))}")
            if ai.get("cycle_position"):
                parts.append(f"周期定位: {html.escape(str(ai['cycle_position']))}")
            conf = ai.get("diagnosis_confidence")
            if conf is not None:
                parts.append(f"诊断置信度: {html.escape(str(conf))}%")
            wk = ai.get("wyckoff_check") or {}
            if wk:
                agree = "一致 ✅" if wk.get("regime_agree") else "分歧 ⚠️"
                note = wk.get("note", "")
                parts.append(
                    f"与程序诊断: {agree}"
                    + (f" | {html.escape(str(note))}" if note else "")
                )
        if reasoning:
            parts.append("<b style='color:#3b82f6;'>🧠 AI 完整思考过程（逐步研判）</b>")
            parts.append(html.escape(reasoning))
        if not parts:
            return
        self.text_view.append("<br>")
        for p in parts:
            self.text_view.append(p)
        self.text_view.verticalScrollBar().setValue(
            self.text_view.verticalScrollBar().maximum()
        )

    # 【改动点】V3.1：AI 流式输出——边运算边实时追加到诊断页（不等待收尾一次性加载）
    def append_ai_stream(self, chunk: str) -> None:
        if not chunk:
            return
        self.text_view.append(html.escape(chunk))
        self.text_view.verticalScrollBar().setValue(
            self.text_view.verticalScrollBar().maximum()
        )

    def toPlainText(self) -> str:
        return self.text_view.toPlainText()

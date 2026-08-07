"""问AI对话控件（原 main_window._AiChatWidget 拆分）。

【改动点】需求一.1：架构重构——主窗口渐进式拆分。
本文件承载「问AI」标签页子控件（上层对话展示区 + 底部输入框/发送按钮），
仅负责 UI 展示与输入；提问逻辑由 MainWindow._on_ai_send 处理。
【涉及文件】wkf/gui/widgets/ai_chat.py（新增，自 main_window 抽出）
【验证方式】python -m unittest discover tests；提交分析后问AI面板自动追加分析日志；
            发送提问回车/按钮均可触发，回复原地替换"思考中"占位。
"""
from __future__ import annotations

import html

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class AiChatWidget(QWidget):
    """问AI标签页：上层对话展示区 + 底部输入框/发送按钮（深色样式）。"""

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

"""WKF 设置对话框：AI模型 / 飞书通知 / 其他设置(指标参数)。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from wkf.config.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_JSON = PROJECT_ROOT / "config" / "settings.json"


def _save(settings: Settings) -> None:
    from wkf.config.settings import save_settings

    save_settings(settings, SETTINGS_JSON)


class _BaseDialog(QDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self._form = QFormLayout()
        self._layout = QVBoxLayout(self)
        self._layout.addLayout(self._form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_save)
        self._buttons.rejected.connect(self.reject)
        self._layout.addWidget(self._buttons)

    def _on_save(self) -> None:
        self.accept()


class AIModelDialog(_BaseDialog):
    """AI 模型设置：可自行添加任意 OpenAI 兼容大模型。"""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__("AI 模型设置", parent)
        self._settings = settings
        p = settings.provider

        self._model = QLineEdit(p.model)
        self._base_url = QLineEdit(p.base_url)
        self._api_key = QLineEdit(p.api_key)
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._context = QSpinBox()
        self._context.setRange(4000, 2000000)
        self._context.setSingleStep(10000)
        self._context.setValue(p.context_window)
        self._thinking = QCheckBox("启用深度思考（DeepSeek 专用）")
        self._thinking.setChecked(p.thinking)

        self._form.addRow("模型名称:", self._model)
        self._form.addRow("API 地址:", self._base_url)
        self._form.addRow("API Key:", self._api_key)
        self._form.addRow("上下文窗口:", self._context)
        self._form.addRow("", self._thinking)

    def _on_save(self) -> None:
        p = self._settings.provider
        p.model = self._model.text().strip() or "deepseek-v4-pro"
        p.base_url = self._base_url.text().strip() or "https://api.deepseek.com"
        p.api_key = self._api_key.text().strip()
        p.context_window = self._context.value()
        p.thinking = self._thinking.isChecked()
        _save(self._settings)
        super()._on_save()


class FeishuDialog(_BaseDialog):
    """飞书通知设置：用户可自行添加飞书 API/Webhook。"""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__("飞书发送消息通知设置", parent)
        self._settings = settings
        f = settings.feishu

        self._enabled = QCheckBox("启用飞书通知")
        self._enabled.setChecked(f.enabled)
        self._webhook = QLineEdit(f.webhook_url)
        self._secret = QLineEdit(f.secret)
        self._app_id = QLineEdit(f.app_id)
        self._app_secret = QLineEdit(f.app_secret)
        self._app_secret.setEchoMode(QLineEdit.EchoMode.Password)

        self._form.addRow("", self._enabled)
        self._form.addRow("Webhook 地址:", self._webhook)
        self._form.addRow("签名 Secret:", self._secret)
        self._form.addRow("App ID (选填):", self._app_id)
        self._form.addRow("App Secret (选填):", self._app_secret)

    def _on_save(self) -> None:
        f = self._settings.feishu
        f.enabled = self._enabled.isChecked()
        f.webhook_url = self._webhook.text().strip()
        f.secret = self._secret.text().strip()
        f.app_id = self._app_id.text().strip()
        f.app_secret = self._app_secret.text().strip()
        _save(self._settings)
        super()._on_save()


class IndicatorDialog(_BaseDialog):
    """其他设置：分析指标参数调整。"""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__("其他设置 · 指标参数", parent)
        self._settings = settings
        g = settings.general
        ind = settings.indicators

        self._bar_count = QSpinBox()
        self._bar_count.setRange(30, 500)
        self._bar_count.setValue(g.analysis_bar_count)

        self._rsi_period = QSpinBox()
        self._rsi_period.setRange(5, 50)
        self._rsi_period.setValue(ind.rsi_period)

        self._bb_period = QSpinBox()
        self._bb_period.setRange(5, 100)
        self._bb_period.setValue(ind.bollinger_period)

        self._bb_std = QDoubleSpinBox()
        self._bb_std.setRange(1.0, 4.0)
        self._bb_std.setSingleStep(0.1)
        self._bb_std.setValue(ind.bollinger_std)

        self._ema_period = QSpinBox()
        self._ema_period.setRange(5, 100)
        self._ema_period.setValue(ind.ema_period)

        self._atr_period = QSpinBox()
        self._atr_period.setRange(5, 50)
        self._atr_period.setValue(ind.atr_period)

        self._va_pct = QDoubleSpinBox()
        self._va_pct.setRange(0.5, 0.95)
        self._va_pct.setSingleStep(0.01)
        self._va_pct.setDecimals(3)
        self._va_pct.setValue(ind.value_area_pct)

        self._fp_threshold = QDoubleSpinBox()
        self._fp_threshold.setRange(1.0, 5.0)
        self._fp_threshold.setSingleStep(0.5)
        self._fp_threshold.setValue(ind.footprint_threshold)

        self._swing_window = QSpinBox()
        self._swing_window.setRange(10, 100)
        self._swing_window.setValue(ind.swing_window)

        self._form.addRow("K线数量:", self._bar_count)
        self._form.addRow("RSI 周期:", self._rsi_period)
        self._form.addRow("布林带周期:", self._bb_period)
        self._form.addRow("布林带标准差:", self._bb_std)
        self._form.addRow("EMA 周期:", self._ema_period)
        self._form.addRow("ATR 周期:", self._atr_period)
        self._form.addRow("价值区域占比:", self._va_pct)
        self._form.addRow("足迹失衡倍数:", self._fp_threshold)
        self._form.addRow("摆动检测窗口:", self._swing_window)

    def _on_save(self) -> None:
        g = self._settings.general
        ind = self._settings.indicators
        g.analysis_bar_count = self._bar_count.value()
        ind.rsi_period = self._rsi_period.value()
        ind.bollinger_period = self._bb_period.value()
        ind.bollinger_std = self._bb_std.value()
        ind.ema_period = self._ema_period.value()
        ind.atr_period = self._atr_period.value()
        ind.value_area_pct = self._va_pct.value()
        ind.footprint_threshold = self._fp_threshold.value()
        ind.swing_window = self._swing_window.value()
        _save(self._settings)
        super()._on_save()

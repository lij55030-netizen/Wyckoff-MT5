"""WKF 设置对话框：AI模型 / 飞书通知 / 其他设置(指标参数)。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
        self._notify_enabled = QCheckBox("分析完成自动推送（闲置不发消息）")
        self._notify_enabled.setChecked(f.notify_enabled)
        self._webhook = QLineEdit(f.webhook_url)
        self._secret = QLineEdit(f.secret)
        self._app_id = QLineEdit(f.app_id)
        self._app_secret = QLineEdit(f.app_secret)
        self._app_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._dedup = QSpinBox()
        self._dedup.setRange(0, 60)
        self._dedup.setSuffix(" 分钟")
        self._dedup.setValue(f.push_dedup_minutes)
        self._prob_th = QDoubleSpinBox()
        self._prob_th.setRange(50.0, 95.0)
        self._prob_th.setSingleStep(0.5)
        self._prob_th.setSuffix(" %")
        self._prob_th.setValue(f.push_prob_threshold)

        self._form.addRow("", self._enabled)
        self._form.addRow("", self._notify_enabled)
        self._form.addRow("Webhook 地址:", self._webhook)
        self._form.addRow("签名 Secret:", self._secret)
        self._form.addRow("App ID (选填):", self._app_id)
        self._form.addRow("App Secret (选填):", self._app_secret)
        self._form.addRow("同品种防抖间隔:", self._dedup)
        self._form.addRow("概率红色加粗阈值:", self._prob_th)

    def _on_save(self) -> None:
        f = self._settings.feishu
        f.enabled = self._enabled.isChecked()
        f.notify_enabled = self._notify_enabled.isChecked()
        f.webhook_url = self._webhook.text().strip()
        f.secret = self._secret.text().strip()
        f.app_id = self._app_id.text().strip()
        f.app_secret = self._app_secret.text().strip()
        f.push_dedup_minutes = self._dedup.value()
        f.push_prob_threshold = self._prob_th.value()
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

        # K线明细表格渲染样式：新版表格UI / 旧版纯文本（一键回滚）
        self._table_style = QComboBox()
        self._table_style.addItem("新版表格 UI（推荐）", "new")
        self._table_style.addItem("旧版纯文本表格", "old")
        idx = self._table_style.findData(g.table_style)
        self._table_style.setCurrentIndex(idx if idx >= 0 else 0)

        # 【改动点】数据源切换开关（需求三）：MT5（完整功能）/ yfinance（可选，无Tick）
        # 【涉及文件】wkf/gui/settings_dialogs.py + wkf/config/settings.py + wkf/data/datasource.py
        # 【验证方式】切换到 yfinance 保存后，GUI 弹窗提示无Tick并隐藏订单流；MT5 恢复完整功能
        self._data_source = QComboBox()
        self._data_source.addItem("MT5（完整功能，含订单流）", "mt5")
        self._data_source.addItem("yfinance（通用行情，无Tick数据）", "yfinance")
        ds_idx = self._data_source.findData(getattr(g, "data_source", "mt5"))
        self._data_source.setCurrentIndex(ds_idx if ds_idx >= 0 else 0)
        self._data_source.setToolTip(
            "MT5：完整启用全部功能（订单流/足迹图/实时价格线）。\n"
            "yfinance：支持 BTC、美股指数等品种，无 Tick 数据，自动隐藏订单流面板。"
        )

        self._form.addRow("K线数量:", self._bar_count)
        self._form.addRow("RSI 周期:", self._rsi_period)
        self._form.addRow("布林带周期:", self._bb_period)
        self._form.addRow("布林带标准差:", self._bb_std)
        self._form.addRow("EMA 周期:", self._ema_period)
        self._form.addRow("ATR 周期:", self._atr_period)
        self._form.addRow("价值区域占比:", self._va_pct)
        self._form.addRow("足迹失衡倍数:", self._fp_threshold)
        self._form.addRow("摆动检测窗口:", self._swing_window)
        self._form.addRow("K线明细表格样式:", self._table_style)
        self._form.addRow("行情数据源:", self._data_source)

    def _on_save(self) -> None:
        g = self._settings.general
        ind = self._settings.indicators
        g.analysis_bar_count = self._bar_count.value()
        g.table_style = self._table_style.currentData() or "new"
        g.data_source = self._data_source.currentData() or "mt5"
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

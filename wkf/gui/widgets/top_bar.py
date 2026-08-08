"""顶部控制栏组件（原 main_window 控制栏拆分）。

【改动点】需求一.1：架构重构——主窗口渐进式拆分。
本文件承载顶部控制栏子控件：品种下拉 / 周期下拉 / 数据源 / 获取数据 /
提交分析 / 持续跟踪 / 收线确认 / 十字光标 / K线状态 / 北京时钟。
信号连接与业务调度仍由 MainWindow 统一负责。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)


class TopControlBar(QWidget):
    """顶部控制栏：品种/周期选择 + 操作按钮 + 状态与北京时钟。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        ctrl = QHBoxLayout(self)
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(6)

        ctrl.addWidget(QLabel("品种:"))
        self._sym_combo = QComboBox()
        ctrl.addWidget(self._sym_combo)

        ctrl.addWidget(QLabel("周期:"))
        # 周期下拉：显示中文文本(1分…日线/周线)，itemData 存内部键；
        # 开启自适应宽度（AdjustToContents），窗口缩放/高分屏/小窗口不截断。
        self._tf_combo = QComboBox()
        self._tf_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        ctrl.addWidget(self._tf_combo)

        # 【改动点】V1.3.3：顶部新增「行情数据源」下拉选择器。
        # 可选值：MT5实盘数据源 / YFinance公开数据源；切换即清缓存并异步重拉。
        ds_label = QLabel("数据源:")
        self._ds_combo = QComboBox()
        self._ds_combo.addItem("MT5实盘数据源", "mt5")
        self._ds_combo.addItem("YFinance公开数据源", "yfinance")
        self._ds_combo.setToolTip(
            "MT5：NQ/ES/XAU 实盘 CFD，完整订单流/实时价格线。\n"
            "YFinance：BTC/美股指数公开行情，无 Tick（订单流自动隐藏）。"
        )
        # 【改动点】V3.0：隐藏数据源（功能保留，可在「其他设置 → 行情数据源」切换）
        ds_label.setVisible(False)
        self._ds_combo.setVisible(False)
        ctrl.addWidget(ds_label)
        ctrl.addWidget(self._ds_combo)

        self._fetch_btn = QPushButton("🔄 获取数据")
        ctrl.addWidget(self._fetch_btn)

        self._analyze_btn = QPushButton("📝 提交分析")
        ctrl.addWidget(self._analyze_btn)

        self._auto_check = QCheckBox("♾ 持续跟踪分析")
        self._auto_check.setToolTip(
            "开启后自动轮询 MT5，检测到新 K 线收盘即自动重新提交完整分析（含 AI），"
            "持续跟踪最新行情；每次结果自动加入左侧历史记录"
        )
        ctrl.addWidget(self._auto_check)

        # 【改动点】V3.0：收线确认——持续跟踪时等当前 K 线收盘定型后再分析，
        # 分析数据只使用已收盘 K 线，避免未收盘形态误导判断。
        self._close_confirm = QCheckBox("收线确认")
        self._close_confirm.setChecked(True)
        self._close_confirm.setToolTip(
            "持续跟踪分析时：勾选 = 等当前 K 线收线（收盘定型）后再分析，"
            "且分析只用已收盘 K 线；取消 = 新 K 线开始即立即分析（含未收盘数据）。"
        )
        ctrl.addWidget(self._close_confirm)

        # 十字光标工具：可点击开关，激活后十字线跟随鼠标吸附最近K线显示 OHLC+时间戳
        self._crosshair_btn = QPushButton("➕ 十字光标")
        self._crosshair_btn.setCheckable(True)  # 可点击开关：点击激活/再点关闭
        self._crosshair_btn.setToolTip(
            "开启/关闭十字线光标：激活后鼠标在图表区移动自动吸附最近K线，"
            "显示该K线的开/高/低/收与时间戳；离开图表区域自动隐藏"
        )
        ctrl.addWidget(self._crosshair_btn)

        self._kline_status = QLabel("K线: --")
        self._kline_status.setStyleSheet("color:#8b949e;font-size:12px")
        ctrl.addWidget(self._kline_status)

        # 顶部状态栏常驻北京时间时钟（HH:MM:SS，独立 1 秒定时器刷新；
        # 与决策面板分析时间共用 beijing_now 时间源，时区强制 Asia/Shanghai）
        self._clock_label = QLabel("🕐 --:--:--")
        self._clock_label.setStyleSheet(
            "color:#f59e0b;font-size:12px;font-weight:bold;padding:0 6px;"
            "border:1px solid #2a3442;border-radius:4px;background:#161d26;"
        )
        self._clock_label.setToolTip("当前北京时间（东八区）")
        ctrl.addWidget(self._clock_label)

        # 【改动点】V3.1：铃铛提示音开关（高亮=开 / 置灰=关），
        # 分析流程结束、决策生成完成时若开启播放简短提示音。
        self._alert_btn = QPushButton("🔔")
        self._alert_btn.setCheckable(True)
        self._alert_btn.setChecked(True)
        self._alert_btn.setToolTip("提示音开关：开启=分析完成播放提示音，关闭=静音")
        self._update_alert_style(self._alert_btn.isChecked())
        self._alert_btn.toggled.connect(self._update_alert_style)
        ctrl.addWidget(self._alert_btn)
        ctrl.addStretch(1)

    # 【改动点】V3.1：铃铛状态视觉一眼可辨——
    # 开启=主题青绿高亮+放大；关闭=灰色淡化+缩小。功能逻辑不变。
    def _update_alert_style(self, enabled: bool) -> None:
        if enabled:
            self._alert_btn.setFixedSize(34, 28)
            self._alert_btn.setText("🔔")
            self._alert_btn.setStyleSheet(
                "QPushButton{background:#0f3d34;color:#3ec252;"
                "border:1px solid #3ec252;border-radius:5px;font-size:16px;}"
            )
        else:
            self._alert_btn.setFixedSize(28, 22)
            self._alert_btn.setText("🔕")
            self._alert_btn.setStyleSheet(
                "QPushButton{background:#2a3442;color:#8b949e;"
                "border:1px solid #2a3442;border-radius:4px;font-size:12px;}"
            )

"""K线图控件：K线 + EMA20 + 布林带 + VWAP + POC/VA 阴影 + Delta 底部条。"""
from __future__ import annotations

import datetime
import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from wkf.data.base import KlineFrame


# ────────────────────────────────────────────────────────────────────────────
# 可配置项（颜色 / 线宽 / 标签显隐等，便于后续维护与扩展）
# ────────────────────────────────────────────────────────────────────────────
CROSSHAIR_CFG = {
    "line_color": (148, 163, 184),   # 十字线颜色（灰蓝）
    "line_width": 1,                 # 十字线线宽
    "line_style": "dash",            # 线型: solid / dash / dot
    "label_visible": True,           # 光标数值标签显隐
    "label_bg": (13, 17, 23, 210),   # 标签背景（半透明深色）
    "label_fg": "#e6edf3",           # 标签前景文字色
    "label_border": "#3b82f6",       # 标签描边色
    "rsi_sync": True,                # RSI 副图是否同步垂直光标线
}

LAST_PRICE_CFG = {
    "color": "#ef4444",              # 实时价格线颜色（醒目红）
    "width": 1.5,                    # 价格线宽
    "style": "solid",                # 线型
    "label_visible": True,           # 价格标签显隐
    "label_bg": (239, 68, 68, 220),  # 价格标签背景（红色半透明）
    "label_fg": "#ffffff",           # 价格标签文字色
    "label_border": "#ef4444",       # 标签描边
    "currency": "USD",               # 价格货币单位（显示于标签右侧）
    "decimals": 2,                   # 价格小数位数
}

# 绘制层级：K线 < VA/POC < 实时价格线 < 十字线（光标最上层）
_Z_LAST_PRICE_LINE = 20
_Z_LAST_PRICE_LABEL = 21
_Z_CROSS_LINE = 30
_Z_CROSS_LABEL = 31


def _pen_from(color, width, style="dash"):
    """按配置生成 pyqtgraph 画笔（style: solid/dash/dot）。"""
    styles = {
        "solid": pg.QtCore.Qt.PenStyle.SolidLine,
        "dash": pg.QtCore.Qt.PenStyle.DashLine,
        "dot": pg.QtCore.Qt.PenStyle.DotLine,
    }
    return pg.mkPen(color=color, width=width, style=styles.get(style, styles["dash"]))


class WkfChart(QWidget):
    """威科夫风格 K 线图。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setBackground("#0d1117")
        # 【改动点】需求3：显式开启鼠标交互——左键拖拽平移 + 滚轮放大缩小，
        # 解除坐标轴锁定限制（pyqtgraph 默认开启，此处显式声明以防配置覆盖）。
        # 【涉及文件】wkf/gui/chart_widget.py（对应假设文件 kline_chart.py）
        # 【验证方式】滚轮上下滚动实现 K 线放大/缩小；左键按住横向拖动平移图表
        self._plot.setMouseEnabled(x=True, y=True)
        # 矩形框选放大：ViewBox 原生支持——右键拖拽拉出选区即局部放大
        # （左键=平移，滚轮=缩放，右键=框选放大，三键互不冲突）。
        self._plot.getPlotItem().vb.setMouseMode(pg.ViewBox.PanMode)
        layout.addWidget(self._plot)

        # RSI 子图（同样开启交互）
        self._rsi_plot = pg.PlotWidget()
        self._rsi_plot.setBackground("#0d1117")
        self._rsi_plot.setFixedHeight(90)
        self._rsi_plot.showGrid(x=True, y=True, alpha=0.15)
        self._rsi_plot.setYRange(0, 100)
        self._rsi_plot.setMouseEnabled(x=True, y=True)
        layout.addWidget(self._rsi_plot)

        # 【改动点】需求3：用户手动缩放/平移标记——sigRangeChangedManually 仅由用户操作触发；
        # set_frame 刷新时若用户已手动调整视图，则不再强制 autoRange 重置，保留视图位置。
        self._user_viewed = False
        self._last_symbol: str | None = None
        self._last_key: tuple | None = None  # (symbol, timeframe)：任一变化重置视图
        self._plot.getPlotItem().vb.sigRangeChangedManually.connect(
            lambda *_: setattr(self, "_user_viewed", True)
        )

        self._items: list = []

        # ── 覆盖层（十字线 + 实时价格线）：与 _items 独立管理，set_frame 不清除 ──
        self._overlay_items: list = []
        self._frame: KlineFrame | None = None  # 当前数据帧（十字线吸附用）
        self._crosshair_enabled = False        # 十字线开关状态
        self._in_chart_area = False            # 鼠标是否位于图表区域内
        self._cross_idx = -1                   # 当前吸附的K线索引
        self._mouse_scene_pos = None           # 最近一次鼠标场景坐标

        # 十字线：垂直 + 水平两条线 + 数值标签 + RSI 副图垂直同步线
        self._ch_vline = pg.InfiniteLine(
            angle=90, movable=False, pen=_pen_from(
                CROSSHAIR_CFG["line_color"], CROSSHAIR_CFG["line_width"],
                CROSSHAIR_CFG["line_style"]),
        )
        self._ch_hline = pg.InfiniteLine(
            angle=0, movable=False, pen=_pen_from(
                CROSSHAIR_CFG["line_color"], CROSSHAIR_CFG["line_width"],
                CROSSHAIR_CFG["line_style"]),
        )
        self._ch_label = pg.TextItem(
            color=CROSSHAIR_CFG["label_fg"], fill=pg.mkBrush(*CROSSHAIR_CFG["label_bg"]),
            border=CROSSHAIR_CFG["label_border"], anchor=(0, 1),
        )
        self._ch_rsi_vline = pg.InfiniteLine(
            angle=90, movable=False, pen=_pen_from(
                CROSSHAIR_CFG["line_color"], 1, CROSSHAIR_CFG["line_style"]),
        )
        for it in (self._ch_vline, self._ch_hline, self._ch_label):
            it.setZValue(_Z_CROSS_LINE)
            it.setVisible(False)
            self._plot.addItem(it)
            self._overlay_items.append(it)
        self._ch_label.setZValue(_Z_CROSS_LABEL)
        if CROSSHAIR_CFG["rsi_sync"]:
            self._ch_rsi_vline.setVisible(False)
            self._rsi_plot.addItem(self._ch_rsi_vline)
            self._overlay_items.append(self._ch_rsi_vline)

        # 实时价格线：红色水平线 + 右上角价格标签（含货币单位）
        self._last_price_line = pg.InfiniteLine(
            angle=0, movable=False,
            pen=_pen_from(LAST_PRICE_CFG["color"], LAST_PRICE_CFG["width"],
                          LAST_PRICE_CFG["style"]),
        )
        self._last_price_label = pg.TextItem(
            color=LAST_PRICE_CFG["label_fg"],
            fill=pg.mkBrush(*LAST_PRICE_CFG["label_bg"]),
            border=LAST_PRICE_CFG["label_border"], anchor=(1, 0),
        )
        self._last_price_line.setZValue(_Z_LAST_PRICE_LINE)
        self._last_price_label.setZValue(_Z_LAST_PRICE_LABEL)
        self._last_price_line.setVisible(False)
        self._last_price_label.setVisible(False)
        self._plot.addItem(self._last_price_line)
        self._plot.addItem(self._last_price_label)
        self._overlay_items += [self._last_price_line, self._last_price_label]

        # 鼠标跟踪：启用后 sigSceneMouseMoved 才能收到移动事件
        self.setMouseTracking(True)
        self._plot.setMouseTracking(True)
        self._plot.scene().sigMouseMoved.connect(self._on_scene_mouse_moved)

    def clear_items(self) -> None:
        """清空主图 K线/指标/VA/POC 数据层（overlay 覆盖层独立保留，Z 层级不变）。"""
        for it in self._items:
            try:
                self._plot.removeItem(it)
            except Exception:
                pass
        self._items = []

    def clear_rsi(self) -> None:
        """清空 RSI 副图数据层，保留十字线 RSI 同步线（overlay）。"""
        for it in list(self._rsi_plot.items()):
            if it is not self._ch_rsi_vline:
                try:
                    self._rsi_plot.removeItem(it)
                except Exception:
                    pass

    def reset_view_state(self, symbol: str) -> None:
        """切换品种/周期前置：重置用户视图标记与旧数据帧，新数据强制 autoRange 适配。"""
        self._last_symbol = symbol
        self._last_key = None
        self._user_viewed = False
        self._frame = None  # 旧数据帧失效（十字线吸附/实时价格线基准一并重置）

    def reset_view(self) -> None:
        """空格键快捷键：重置图表为完整视图（主图 + RSI 全部 autoRange）。"""
        self._user_viewed = False
        self._plot.autoRange()
        self._rsi_plot.autoRange()

    # ── 加载挂起/恢复（品种/周期切换期间禁用交互，避免旧数据残留）──────
    def suspend_interactions(self) -> None:
        """切换加载前调用：隐藏全部覆盖层（价格线/十字线），挂起鼠标监听。"""
        self._suspended = True
        # 记录用户十字光标开关状态，加载完成后恢复
        self._crosshair_state_before_suspend = self._crosshair_enabled
        self._last_price_line.setVisible(False)
        self._last_price_label.setVisible(False)
        self._ch_vline.setVisible(False)
        self._ch_hline.setVisible(False)
        self._ch_label.setVisible(False)
        self._ch_rsi_vline.setVisible(False)
        self._cross_idx = -1

    def resume_interactions(self) -> None:
        """数据加载完成：恢复鼠标监听；若用户开启过十字光标则重新激活。"""
        self._suspended = False
        if getattr(self, "_crosshair_state_before_suspend", False):
            self._crosshair_enabled = True
            if self._frame is not None and self._mouse_scene_pos is not None:
                vb = self._plot.getPlotItem().vb
                if vb.sceneBoundingRect().contains(self._mouse_scene_pos):
                    self._update_crosshair(self._mouse_scene_pos)
        else:
            self._crosshair_enabled = False

    def _render_candles(self, frame: KlineFrame, x: np.ndarray) -> None:
        bars = frame.bars
        o = np.array([b.open for b in bars])
        h = np.array([b.high for b in bars])
        l = np.array([b.low for b in bars])
        c = np.array([b.close for b in bars])
        up = c >= o
        dn = c < o

        # 蜡烛实体
        body_low = np.where(up, o, c)
        body_high = np.where(up, c, o)
        width = 0.5
        up_brush = pg.mkBrush(62, 194, 82, 200)  # 涨绿
        dn_brush = pg.mkBrush(240, 78, 74, 200)  # 跌红
        up_pen = pg.mkPen(62, 194, 82, width=1)
        dn_pen = pg.mkPen(240, 78, 74, width=1)

        for i in range(len(bars)):
            if up[i]:
                self._items.append(
                    pg.BarGraphItem(x=[x[i]], height=[body_high[i] - body_low[i]],
                                    y0=[body_low[i]], width=width, brush=up_brush, pen=up_pen)
                )
                self._items.append(
                    pg.PlotDataItem([x[i], x[i]], [l[i], h[i]], pen=up_pen)
                )
            else:
                self._items.append(
                    pg.BarGraphItem(x=[x[i]], height=[body_high[i] - body_low[i]],
                                    y0=[body_low[i]], width=width, brush=dn_brush, pen=dn_pen)
                )
                self._items.append(
                    pg.PlotDataItem([x[i], x[i]], [l[i], h[i]], pen=dn_pen)
                )
        for it in self._items:
            self._plot.addItem(it)

    def _render_indicator_lines(self, frame: KlineFrame, x: np.ndarray) -> None:
        ind = frame.indicators
        series = [
            ("EMA20", ind.ema20, (255, 200, 0)),
            ("BB上", ind.bb_upper, (100, 160, 255)),
            ("BB中", ind.bb_middle, (100, 160, 255)),
            ("BB下", ind.bb_lower, (100, 160, 255)),
            ("VWAP", ind.vwap, (220, 130, 255)),
        ]
        for name, vals, color in series:
            ys = np.array([v if not math.isnan(v) else np.nan for v in vals])
            line = pg.PlotDataItem(
                x=x, y=ys,
                pen=pg.mkPen(color=color, width=1, style=pg.QtCore.Qt.PenStyle.DashLine),
                name=name,
            )
            self._items.append(line)
            self._plot.addItem(line)

        # VA 阴影（用最新 POC/VAH/VAL 画水平价格区域）
        # 注意：LinearRegionItem 默认 orientation='vertical'（x 方向区域），
        # 若把价格 (val, vah) 直接传给它会被当作 x 坐标，污染 autoRange 视图范围
        # （x 被撑到 29000 量级，蜡烛被压缩成几乎不可见）。
        # 必须显式指定 orientation='horizontal'，让区域沿 y(价格) 方向。
        of = frame.orderflow
        if of is not None:
            vah = of.vah[0] if of.vah and not math.isnan(of.vah[0]) else None
            val = of.val[0] if of.val and not math.isnan(of.val[0]) else None
            if vah is not None and val is not None:
                region = pg.LinearRegionItem(
                    values=(val, vah),
                    orientation="horizontal",
                    brush=pg.mkBrush(120, 180, 255, 40),
                    pen=pg.mkPen(120, 180, 255, 120),
                    movable=False,
                )
                region.setZValue(-10)
                self._items.append(region)
                self._plot.addItem(region)
            poc = of.poc_price[0] if of.poc_price and not math.isnan(of.poc_price[0]) else None
            if poc is not None:
                poc_line = pg.InfiniteLine(
                    pos=poc, angle=0,
                    pen=pg.mkPen(255, 170, 60, width=1, style=pg.QtCore.Qt.PenStyle.DotLine),
                )
                self._items.append(poc_line)
                self._plot.addItem(poc_line)

    def _render_delta_bars(self, frame: KlineFrame, x: np.ndarray) -> None:
        of = frame.orderflow
        if of is None or not of.delta:
            return
        deltas = np.array([d if not math.isnan(d) else 0.0 for d in of.delta[: len(x)]])
        up = deltas >= 0
        up_brush = pg.mkBrush(62, 194, 82, 160)
        dn_brush = pg.mkBrush(240, 78, 74, 160)
        new_items: list = []
        # 底部 12% 区域绘制
        xr = self._plot.viewRange()[0]
        yr = self._plot.viewRange()[1]
        if xr and yr and len(yr) >= 2:
            y_base = yr[0]
            y_scale = (yr[1] - yr[0]) * 0.12
            for i in range(len(deltas)):
                h = abs(deltas[i]) / (max(abs(deltas)) or 1.0) * y_scale
                brush = up_brush if up[i] else dn_brush
                new_items.append(
                    pg.BarGraphItem(x=[x[i]], height=[h], y0=[y_base], width=0.5, brush=brush)
                )
        for it in new_items:
            self._items.append(it)
            self._plot.addItem(it)

    def _render_rsi(self, frame: KlineFrame, x: np.ndarray) -> None:
        ind = frame.indicators
        if not ind.rsi14:
            return
        ys = np.array([v if not math.isnan(v) else np.nan for v in ind.rsi14[: len(x)]])
        self._rsi_plot.plot(x, ys, pen=pg.mkPen(180, 120, 255, width=1))
        self._rsi_plot.addLine(y=70, pen=pg.mkPen(240, 78, 74, style=pg.QtCore.Qt.PenStyle.DashLine))
        self._rsi_plot.addLine(y=30, pen=pg.mkPen(62, 194, 82, style=pg.QtCore.Qt.PenStyle.DashLine))
        self._rsi_plot.addLine(y=50, pen=pg.mkPen(150, 150, 150, style=pg.QtCore.Qt.PenStyle.DotLine))

    def set_frame(self, frame: KlineFrame) -> None:
        self.clear_items()
        self.clear_rsi()
        n = len(frame.bars)
        if n == 0:
            return
        # 【改动点】需求3/图表交互升级：品种或周期任一变化 → 重置用户视图标记，
        # 新数据强制 autoRange；同品种同周期刷新/用户手动缩放平移时保持视图。
        # 【涉及文件】wkf/gui/chart_widget.py（对应假设文件 kline_chart.py）
        # 【验证方式】手动缩放视图后刷新 K 线，视图不自动复位；切换品种/周期后重新适配
        key = (frame.symbol, frame.timeframe)
        if key != self._last_key:
            self._last_key = key
            self._last_symbol = frame.symbol
            self._user_viewed = False
        do_autorange = not self._user_viewed

        # bars 为 新->旧（seq=1 最新在 index 0）；x 数组递减生成，
        # 让最新一根 K 线显示在图表最右侧（时间从左往右）
        x = np.arange(n, dtype=float)[::-1]  # n-1(最新) ... 0(最旧)
        self._render_candles(frame, x)
        self._render_indicator_lines(frame, x)
        # 仅在首次加载/切换品种时 autoRange 确定视图；用户手动缩放后保留视图。
        # （Delta 条依赖 viewRange 取底部基准，须在 autoRange 后调用）
        if do_autorange:
            self._plot.autoRange()
        self._render_delta_bars(frame, x)
        self._render_rsi(frame, x)
        if do_autorange:
            self._rsi_plot.autoRange()

        # 保存当前数据帧（供十字线吸附读取 OHLC/时间戳）
        self._frame = frame
        # 切换品种/刷新后旧价格线数值已过时 → 隐藏，等待新一轮 tick 到达再显示
        self._last_price_line.setVisible(False)
        self._last_price_label.setVisible(False)
        # 十字线若已激活且鼠标仍在图表区域内 → 用新数据立即重画
        if self._crosshair_enabled and self._in_chart_area and self._mouse_scene_pos is not None:
            self._update_crosshair(self._mouse_scene_pos)

    # ────────────────────────────────────────────────────────────────────────
    # 十字线光标工具（可点击开关，独立于 K 线渲染，关闭后不留任何残留状态）
    # ────────────────────────────────────────────────────────────────────────
    def set_crosshair_enabled(self, enabled: bool) -> None:
        """开关十字线：enabled=True 激活（跟随鼠标吸附K线），False 关闭并清场。"""
        self._crosshair_enabled = enabled
        if not enabled:
            # 关闭：隐藏所有光标元素，清空吸附状态，恢复默认交互（拖拽/缩放不受影响）
            self._ch_vline.setVisible(False)
            self._ch_hline.setVisible(False)
            self._ch_label.setVisible(False)
            self._ch_rsi_vline.setVisible(False)
            self._cross_idx = -1
            self._in_chart_area = False
        elif self._frame is not None and self._mouse_scene_pos is not None:
            # 激活：仅当鼠标当前位于图表区域内才立即显示，避免鼠标在图外时十字线跳至远处
            vb = self._plot.getPlotItem().vb
            if vb.sceneBoundingRect().contains(self._mouse_scene_pos):
                self._update_crosshair(self._mouse_scene_pos)

    def is_crosshair_enabled(self) -> bool:
        return self._crosshair_enabled

    def _on_scene_mouse_moved(self, scene_pos) -> None:
        """场景鼠标移动（每帧触发）：记录位置，判断是否在图表区域并刷新十字线。"""
        if getattr(self, "_suspended", False):
            return  # 加载挂起期间忽略鼠标监听（切换前置清理的一部分）
        self._mouse_scene_pos = scene_pos
        if not self._crosshair_enabled:
            return
        # 判断鼠标是否位于主图绘制区域（ViewBox 场景矩形内）
        vb = self._plot.getPlotItem().vb
        inside = vb.sceneBoundingRect().contains(scene_pos)
        if inside:
            if not self._in_chart_area:
                self._in_chart_area = True  # 重新进入 → 恢复显示
            self._update_crosshair(scene_pos)
        else:
            # 离开图表区域 → 自动隐藏十字线
            if self._in_chart_area:
                self._in_chart_area = False
                self._ch_vline.setVisible(False)
                self._ch_hline.setVisible(False)
                self._ch_label.setVisible(False)
                self._ch_rsi_vline.setVisible(False)

    def _bar_index_at(self, vx: float) -> int:
        """视图 x 坐标 → 最近K线索引。

        坐标系说明：set_frame 里 x = arange(n)[::-1]，即最新K线(index 0)在最右
        (x = n-1)，最旧K线(index n-1)在最左 (x = 0)。因此：
        idx = n-1 - round(vx)，并 clamp 到 [0, n-1]。
        """
        n = len(self._frame.bars) if self._frame else 0
        if n == 0:
            return -1
        return max(0, min(n - 1, n - 1 - int(round(vx))))

    def _update_crosshair(self, scene_pos) -> None:
        """吸附最近K线并更新十字线位置与数值标签。"""
        if self._frame is None or not self._frame.bars:
            return
        vb = self._plot.getPlotItem().vb
        vp = vb.mapSceneToView(scene_pos)
        idx = self._bar_index_at(vp.x())
        if idx < 0:
            return
        bar = self._frame.bars[idx]
        self._cross_idx = idx

        # 十字线定位：
        #  - 垂直 x 方向：吸附到最近K线中心（snap，标签显示该K线精确 OHLC+时间戳）
        #  - 水平 y 方向：跟随鼠标当前价格坐标（保证十字线交点实时与鼠标对齐）
        x_center = len(self._frame.bars) - 1 - idx
        mouse_y = vp.y()
        self._ch_vline.setPos(x_center)
        self._ch_hline.setPos(mouse_y)
        self._ch_vline.setVisible(True)
        self._ch_hline.setVisible(True)
        if CROSSHAIR_CFG["rsi_sync"]:
            self._ch_rsi_vline.setPos(x_center)
            self._ch_rsi_vline.setVisible(True)

        # 数值标签：跟随交点位置（x=K线中心, y=鼠标价格），默认右上方；靠近右边界时翻转
        if CROSSHAIR_CFG["label_visible"]:
            xr = vb.viewRange()[0]
            flip = x_center > (xr[0] + xr[1]) / 2
            self._ch_label.setPos(x_center, mouse_y)
            self._ch_label.setAnchor((1, 0) if flip else (0, 1))
            self._ch_label.setText(self._format_crosshair_label(bar))
            self._ch_label.setVisible(True)

    def _format_crosshair_label(self, bar) -> str:
        """十字线标签文本：时间戳 + 开/高/低/收。"""
        ts = datetime.datetime.fromtimestamp(bar.ts_open / 1000).strftime("%m-%d %H:%M")
        return (f"{ts}\n"
                f"开 {bar.open:.2f}  高 {bar.high:.2f}\n"
                f"低 {bar.low:.2f}  收 {bar.close:.2f}")

    # ────────────────────────────────────────────────────────────────────────
    # 实时价格标注（红色水平线 + 价格标签，随行情平滑更新）
    # ────────────────────────────────────────────────────────────────────────
    def set_last_price(self, price: float) -> None:
        """更新最新成交价红线与标签。

        仅 setPos/setText（不重建 item），天然平滑无闪烁；
        标签锚点根据价格在视图中的上下位置自动翻转，避免超出可视边界。
        """
        if price is None or math.isnan(price):
            return
        self._last_price_line.setPos(price)
        self._last_price_line.setVisible(True)

        if LAST_PRICE_CFG["label_visible"]:
            decimals = LAST_PRICE_CFG["decimals"]
            cur = LAST_PRICE_CFG["currency"]
            self._last_price_label.setText(f"{price:,.{decimals}f} {cur}")
            # 标签固定贴右边缘（x = 视图右边界），垂直跟随价格
            vb = self._plot.getPlotItem().vb
            xr, yr = vb.viewRange()
            x_right = xr[1]
            flip_up = (price - yr[0]) < (yr[1] - yr[0]) * 0.15  # 价格接近顶部 → 标签放线上方
            self._last_price_label.setPos(x_right, price)
            self._last_price_label.setAnchor((1, 1) if flip_up else (1, 0))
            self._last_price_label.setVisible(True)

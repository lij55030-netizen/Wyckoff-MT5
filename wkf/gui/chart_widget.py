"""K线图控件：K线 + EMA20 + 布林带 + VWAP + POC/VA 阴影 + Delta 底部条。"""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from wkf.data.base import KlineFrame


class WkfChart(QWidget):
    """威科夫风格 K 线图。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setBackground("#0d1117")
        layout.addWidget(self._plot)

        # RSI 子图
        self._rsi_plot = pg.PlotWidget()
        self._rsi_plot.setBackground("#0d1117")
        self._rsi_plot.setFixedHeight(90)
        self._rsi_plot.showGrid(x=True, y=True, alpha=0.15)
        self._rsi_plot.setYRange(0, 100)
        layout.addWidget(self._rsi_plot)

        self._items: list = []

    def clear_items(self) -> None:
        for it in self._items:
            try:
                self._plot.removeItem(it)
            except Exception:
                pass
        self._items = []

    def clear_rsi(self) -> None:
        self._rsi_plot.clear()

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

        # VA 阴影（用最新 POC/VAH/VAL 画水平区域）
        of = frame.orderflow
        if of is not None:
            x_min = float(x.min())
            x_max = float(x.max())
            vah = of.vah[0] if of.vah and not math.isnan(of.vah[0]) else None
            val = of.val[0] if of.val and not math.isnan(of.val[0]) else None
            if vah is not None and val is not None:
                region = pg.LinearRegionItem(
                    values=(val, vah),
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
        x = np.arange(n, dtype=float)  # 0=最旧 ... n-1=最新
        self._render_candles(frame, x)
        self._render_indicator_lines(frame, x)
        self._render_delta_bars(frame, x)
        self._render_rsi(frame, x)
        self._plot.autoRange()
        self._rsi_plot.autoRange()

"""K线图控件（性能优化版）：K线 + 成交量 + EMA20 + 布林带 + VWAP + POC/VA 阴影 + RSI 副图。

性能优化说明
------------
旧实现每根K线创建 2 个 item（实体 BarGraphItem + 影线 PlotDataItem），
另加每根 Delta 一个 BarGraphItem——100 根K线共 ~307 个 item，
切换品种时全量重建导致明显卡顿。

新版采用 pyqtgraph 批量渲染：
  · K线实体：2 个 BarGraphItem（涨/跌各一，numpy 数组一次绘制）
  · K线影线：2 个 PlotDataItem（connect='pairs' 分段线，涨/跌各一）
  · 成交量：2 个 BarGraphItem（底部 12% 区域，涨红/跌绿半透明）
  · 指标线：5 个 PlotDataItem（EMA20/BB上中下/VWAP）
  · VA 区域 1 + POC 线 1 + RSI 曲线 1
  合计约 13 个 item，渲染与重绘开销下降约 20 倍，连续切换品种流畅。

配色（全局统一，中国习惯：涨红跌绿）
  · 阳线/上涨：红 #ef4444      · 阴线/下跌：绿 #22c55e
  · VWAP：蓝 #3b82f6           · RSI：紫 #a78bfa
  · EMA20：黄 #f59e0b          · 布林带：青灰 #94a3b8（虚线）
  · POC：橙 #fb923c（点线）     · VA 区域：蓝半透明
"""
from __future__ import annotations

import datetime
import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from wkf.data.base import KlineFrame

# ── 全局配色（中国习惯：涨红跌绿）──────────────────────────────────────
UP_COLOR = "#ef4444"            # 阳线/上涨 红
DN_COLOR = "#22c55e"            # 阴线/下跌 绿
VWAP_COLOR = "#3b82f6"          # VWAP 蓝
RSI_COLOR = "#a78bfa"           # RSI 紫
EMA_COLOR = "#f59e0b"           # EMA20 黄
BB_COLOR = "#94a3b8"            # 布林带 青灰
POC_COLOR = "#fb923c"           # POC 橙

UP_BRUSH = pg.mkBrush(239, 68, 68, 210)      # 阳实体
DN_BRUSH = pg.mkBrush(34, 197, 94, 210)      # 阴实体
UP_PEN = pg.mkPen(239, 68, 68, width=1)      # 阳影线
DN_PEN = pg.mkPen(34, 197, 94, width=1)      # 阴影线
VOL_UP_BRUSH = pg.mkBrush(239, 68, 68, 110)  # 阳量柱
VOL_DN_BRUSH = pg.mkBrush(34, 197, 94, 110)  # 阴量柱


class WkfChart(QWidget):
    """威科夫风格 K 线图（批量渲染 + 悬停信息 + 图例）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 主图（K线 + 成交量 + 指标）
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setBackground("#0d1117")
        self._plot.setMouseEnabled(x=True, y=False)  # 滚轮/拖动缩放 x 轴
        layout.addWidget(self._plot, stretch=1)

        # RSI 副图
        self._rsi_plot = pg.PlotWidget()
        self._rsi_plot.setBackground("#0d1117")
        self._rsi_plot.setFixedHeight(100)
        self._rsi_plot.showGrid(x=True, y=True, alpha=0.15)
        self._rsi_plot.setYRange(0, 100)
        layout.addWidget(self._rsi_plot)

        self._items: list = []

        # ── 图例（主图右上角）──────────────────────────────────────────
        self._legend = self._plot.addLegend(offset=(10, 10))
        self._legend.addItem(pg.PlotDataItem(pen=UP_PEN), "阳线(涨)")
        self._legend.addItem(pg.PlotDataItem(pen=DN_PEN), "阴线(跌)")

        # ── 鼠标悬停信息浮层 ───────────────────────────────────────────
        self._hover_text = pg.TextItem(anchor=(0, 0), color="#e2e8f0",
                                       fill=pg.mkBrush(15, 20, 30, 220))
        self._hover_text.hide()
        self._plot.addItem(self._hover_text)
        self._proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved
        )
        self._hover_x: np.ndarray | None = None
        self._hover_bars = ()

    # ── 清理 ────────────────────────────────────────────────────────────
    def clear_items(self) -> None:
        for it in self._items:
            try:
                self._plot.removeItem(it)
            except Exception:
                pass
        self._items = []

    def clear_rsi(self) -> None:
        self._rsi_plot.clear()

    # ── 渲染：K线（批量）───────────────────────────────────────────────
    def _render_candles(self, frame: KlineFrame, x: np.ndarray) -> None:
        bars = frame.bars
        o = np.array([b.open for b in bars])
        h = np.array([b.high for b in bars])
        l = np.array([b.low for b in bars])
        c = np.array([b.close for b in bars])
        up = c >= o
        width = 0.6

        def add_body(mask: np.ndarray, brush, pen) -> None:
            idx = np.where(mask)[0]
            if len(idx) == 0:
                return
            lo = np.minimum(o[idx], c[idx])
            hi = np.maximum(o[idx], c[idx])
            hgt = np.maximum(hi - lo, 0.5)  # 十字星最小高度 0.5 保证可见
            it = pg.BarGraphItem(x=x[idx], height=hgt, y0=lo, width=width,
                                 brush=brush, pen=pen)
            self._items.append(it)
            self._plot.addItem(it)

        def add_wick(mask: np.ndarray, pen) -> None:
            idx = np.where(mask)[0]
            if len(idx) == 0:
                return
            seg = np.empty(len(idx) * 4)  # pairs: x0,y0,x1,y1,...
            seg[0::4] = x[idx]
            seg[1::4] = l[idx]
            seg[2::4] = x[idx]
            seg[3::4] = h[idx]
            it = pg.PlotDataItem(seg, pen=pen, connect="pairs")
            self._items.append(it)
            self._plot.addItem(it)

        add_body(up, UP_BRUSH, UP_PEN)
        add_body(~up, DN_BRUSH, DN_PEN)
        add_wick(up, UP_PEN)
        add_wick(~up, DN_PEN)

    # ── 渲染：成交量柱（主图底部 12% 区域，涨红/跌绿）──────────────────
    def _render_volume(self, frame: KlineFrame, x: np.ndarray, min_p: float, max_p: float) -> None:
        bars = frame.bars
        vols = np.array([b.volume for b in bars], dtype=float)
        if vols.max() <= 0:
            return
        height = vols / vols.max() * (max_p - min_p) * 0.12
        c = np.array([b.close for b in bars])
        o = np.array([b.open for b in bars])
        up = c >= o

        def add_vol(mask: np.ndarray, brush) -> None:
            idx = np.where(mask)[0]
            if len(idx) == 0:
                return
            it = pg.BarGraphItem(x=x[idx], height=height[idx],
                                 y0=np.full(len(idx), min_p), width=0.6, brush=brush)
            self._items.append(it)
            self._plot.addItem(it)

        add_vol(up, VOL_UP_BRUSH)
        add_vol(~up, VOL_DN_BRUSH)
        self._legend.addItem(pg.PlotDataItem(pen=pg.mkPen(239, 68, 68, 110)), "成交量(涨/跌)")

    # ── 渲染：指标线（EMA20/BB/VWAP，图例标注颜色）──────────────────────
    def _render_indicator_lines(self, frame: KlineFrame, x: np.ndarray) -> None:
        ind = frame.indicators
        series = [
            ("EMA20", ind.ema20, pg.mkPen(EMA_COLOR, width=1.4)),
            ("BB上", ind.bb_upper, pg.mkPen(BB_COLOR, width=1, style=Qt.PenStyle.DashLine)),
            ("BB中", ind.bb_middle, pg.mkPen(BB_COLOR, width=1, style=Qt.PenStyle.DashLine)),
            ("BB下", ind.bb_lower, pg.mkPen(BB_COLOR, width=1, style=Qt.PenStyle.DashLine)),
            ("VWAP", ind.vwap, pg.mkPen(VWAP_COLOR, width=1.6)),
        ]
        for name, vals, pen in series:
            ys = np.array([v if not math.isnan(v) else np.nan for v in vals])
            line = pg.PlotDataItem(x=x, y=ys, pen=pen, name=name)
            self._items.append(line)
            self._plot.addItem(line)

    # ── 渲染：价值区域阴影 + POC ────────────────────────────────────────
    def _render_va(self, frame: KlineFrame) -> None:
        of = frame.orderflow
        if of is None:
            return
        # VA 阴影：必须 orientation='horizontal'（沿价格 y 方向），
        # 否则默认 vertical 会把价格当 x 坐标污染视图范围（历史 bug）
        vah = of.vah[0] if of.vah and not math.isnan(of.vah[0]) else None
        val = of.val[0] if of.val and not math.isnan(of.val[0]) else None
        if vah is not None and val is not None:
            region = pg.LinearRegionItem(
                values=(val, vah), orientation="horizontal",
                brush=pg.mkBrush(120, 180, 255, 40),
                pen=pg.mkPen(120, 180, 255, 120), movable=False,
            )
            region.setZValue(-10)
            self._items.append(region)
            self._plot.addItem(region)
        poc = of.poc_price[0] if of.poc_price and not math.isnan(of.poc_price[0]) else None
        if poc is not None:
            poc_line = pg.InfiniteLine(
                pos=poc, angle=0,
                pen=pg.mkPen(POC_COLOR, width=1, style=Qt.PenStyle.DotLine),
            )
            self._items.append(poc_line)
            self._plot.addItem(poc_line)

    # ── 渲染：RSI 副图（紫色）──────────────────────────────────────────
    def _render_rsi(self, frame: KlineFrame, x: np.ndarray) -> None:
        ind = frame.indicators
        if not ind.rsi14:
            return
        ys = np.array([v if not math.isnan(v) else np.nan for v in ind.rsi14[: len(x)]])
        self._rsi_plot.plot(x, ys, pen=pg.mkPen(RSI_COLOR, width=1.4), name="RSI")
        self._rsi_plot.addLine(y=70, pen=pg.mkPen(UP_COLOR, style=Qt.PenStyle.DashLine))
        self._rsi_plot.addLine(y=30, pen=pg.mkPen(DN_COLOR, style=Qt.PenStyle.DashLine))
        self._rsi_plot.addLine(y=50, pen=pg.mkPen(150, 150, 150, style=Qt.PenStyle.DotLine))
        # RSI 副图图例
        leg = self._rsi_plot.addLegend(offset=(10, 10))
        leg.addItem(pg.PlotDataItem(pen=pg.mkPen(RSI_COLOR)), "RSI14(紫)")

    # ── 主入口：刷新整图（切换品种/周期/分析完成后调用）────────────────
    def set_frame(self, frame: KlineFrame) -> None:
        self.clear_items()
        self.clear_rsi()
        n = len(frame.bars)
        if n == 0:
            return
        # bars 新->旧（seq=1 最新 index0）；x 递减，最新K线在最右侧
        x = np.arange(n, dtype=float)[::-1]
        # 价格范围取真实 high/low（防区间为零导致水平线）
        hs = np.array([b.high for b in frame.bars])
        ls = np.array([b.low for b in frame.bars])
        min_p, max_p = float(ls.min()), float(hs.max())
        if max_p <= min_p:
            pad = (abs(min_p) or 1.0) * 0.005
            min_p -= pad
            max_p += pad

        self._render_candles(frame, x)
        self._render_volume(frame, x, min_p, max_p)
        self._render_indicator_lines(frame, x)
        self._render_va(frame)
        self._plot.autoRange()
        self._render_rsi(frame, x)
        self._rsi_plot.autoRange()

        # 悬停数据缓存
        self._hover_x = x
        self._hover_bars = frame.bars
        self._hover_ind = frame.indicators

    # ── 鼠标悬停：显示该K线完整数值 ─────────────────────────────────────
    def _on_mouse_moved(self, evt) -> None:
        if self._hover_x is None or len(self._hover_x) == 0:
            return
        pos = evt[0]
        if not self._plot.sceneBoundingRect().contains(pos):
            self._hover_text.hide()
            return
        mp = self._plot.getViewBox().mapSceneToView(pos)
        idx = int(np.argmin(np.abs(self._hover_x - mp.x())))
        if idx < 0 or idx >= len(self._hover_bars):
            return
        b = self._hover_bars[idx]
        ind = getattr(self, "_hover_ind", None)
        rsi = ind.rsi14[idx] if ind and idx < len(ind.rsi14) and not math.isnan(ind.rsi14[idx]) else None
        vwap = ind.vwap[idx] if ind and idx < len(ind.vwap) and not math.isnan(ind.vwap[idx]) else None
        ts = datetime.datetime.fromtimestamp(b.ts_open / 1000).strftime("%m-%d %H:%M")
        trend = "阳" if b.close >= b.open else "阴"
        rsi_s = f"{rsi:.1f}" if rsi is not None else "-"
        vwap_s = f"{vwap:.2f}" if vwap is not None else "-"
        txt = (
            f"{ts}  {trend}\n"
            f"开 {b.open:.2f}  高 {b.high:.2f}\n"
            f"低 {b.low:.2f}  收 {b.close:.2f}\n"
            f"量 {b.volume:.0f}  RSI {rsi_s}\n"
            f"VWAP {vwap_s}"
        )
        self._hover_text.setText(txt)
        # 悬停在上半区则浮层显示在K线下方，避免溢出顶部
        if mp.y() > (self._plot.viewRange()[1][0] + self._plot.viewRange()[1][1]) / 2:
            self._hover_text.setAnchor((0, 0))
            self._hover_text.setPos(mp.x(), b.high)
        else:
            self._hover_text.setAnchor((0, 1))
            self._hover_text.setPos(mp.x(), b.low)
        self._hover_text.show()

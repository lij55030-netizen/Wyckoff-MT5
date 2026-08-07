"""十字线光标工具 + 实时价格标注 验证脚本（offscreen，不依赖 AI）。"""
import sys
sys.path.insert(0, r"E:\workbuddy\MT50802\wkf")

from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pyqtgraph as pg

from wkf.data.mt5_source import (
    fetch_mt5_bars, compute_indicators, enrich_frame_with_orderflow,
)
from wkf.data.base import KlineFrame
from wkf.gui.chart_widget import WkfChart, CROSSHAIR_CFG, LAST_PRICE_CFG

bars = fetch_mt5_bars("NQ1!", "15m", 100)
ind = compute_indicators(bars)
frame = KlineFrame(symbol="NQ1!", timeframe="15m", bars=tuple(bars), indicators=ind)
frame = enrich_frame_with_orderflow(frame)

chart = WkfChart()
chart.resize(900, 520)
chart.show()
app.processEvents()
chart.set_frame(frame)
app.processEvents()

ok = True
def chk(name, cond):
    global ok
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        ok = False

vb = chart._plot.getPlotItem().vb

# 1. 默认状态：十字线/价格线全部隐藏
chk("默认隐藏: 十字线",
   not chart._ch_vline.isVisible() and not chart._ch_hline.isVisible() and not chart._ch_label.isVisible())
chk("默认隐藏: 价格线",
   not chart._last_price_line.isVisible() and not chart._last_price_label.isVisible())
chk("默认关闭: crosshair_enabled=False", not chart.is_crosshair_enabled())

# 2. 启用十字线 → 模拟鼠标移动到图表内任意位置（吸附 bars[5]，vx = 100-1-5 = 94）
chart.set_crosshair_enabled(True)
target_idx = 5
mouse_view_x = 100 - 1 - target_idx + 0.3   # 鼠标不在K线正中心（测试吸附）
mouse_view_y = bars[target_idx].close + 55.5  # 鼠标y远离收盘价（测试水平线跟随鼠标）
scene_pos = vb.mapViewToScene(pg.QtCore.QPointF(mouse_view_x, mouse_view_y))
chart._on_scene_mouse_moved(scene_pos)
app.processEvents()
chk("激活后: 十字线可见",
   chart._ch_vline.isVisible() and chart._ch_hline.isVisible() and chart._ch_label.isVisible())
chk("吸附索引正确 (bars[5])", chart._cross_idx == target_idx)
chk("垂直线吸附K线中心",
   abs(chart._ch_vline.value() - (100 - 1 - target_idx)) < 1e-9)
chk("水平线跟随鼠标y对齐",
   abs(chart._ch_hline.value() - mouse_view_y) < 1e-9)

# 像素级对齐验证：十字线映射回场景坐标与鼠标场景坐标对比
v_line_scene_x = vb.mapViewToScene(pg.QtCore.QPointF(chart._ch_vline.value(), 0)).x()
h_line_scene_y = vb.mapViewToScene(pg.QtCore.QPointF(0, chart._ch_hline.value())).y()
dx_px = abs(v_line_scene_x - scene_pos.x())   # 垂直线吸附偏差（应≤半格）
dy_px = abs(h_line_scene_y - scene_pos.y())   # 水平线偏差（应≈0）
half_bar_px = abs(vb.mapViewToScene(pg.QtCore.QPointF(0, 0)).x()
                  - vb.mapViewToScene(pg.QtCore.QPointF(0.5, 0)).x())
chk(f"像素对齐: 水平线偏差 {dy_px:.2f}px (≈0)", dy_px < 1.0)
chk(f"像素对齐: 垂直线偏差 {dx_px:.2f}px (≤半格 {half_bar_px:.2f}px)", dx_px <= half_bar_px + 1.0)

label_txt = chart._ch_label.toPlainText()
chk("标签含OHLC+时间", "开" in label_txt and "收" in label_txt and "-" in label_txt)
print("   标签内容:", label_txt.replace(chr(10), " | "))

# 3. 鼠标离开图表区域 → 自动隐藏；重新进入 → 恢复
outside = pg.QtCore.QPointF(5, 5)  # 场景左上角（通常在图外）
chart._on_scene_mouse_moved(outside)
app.processEvents()
chk("离开图表: 自动隐藏", not chart._ch_vline.isVisible())
chart._on_scene_mouse_moved(scene_pos)
app.processEvents()
chk("重新进入: 恢复显示", chart._ch_vline.isVisible())

# 4. 实时价格线：set_last_price 更新位置与标签
chart.set_last_price(4300.52)
app.processEvents()
chk("价格线可见", chart._last_price_line.isVisible())
chk("红线位置=最新价", abs(chart._last_price_line.value() - 4300.52) < 1e-9)
chk("标签含价格+货币单位", "4,300.52 USD" in chart._last_price_label.toPlainText())
print("   价格标签:", chart._last_price_label.toPlainText())

# 5. 两功能同时启用互不干扰
chart.set_last_price(4310.11)
chk("价格线更新不影响十字线",
   chart._ch_vline.isVisible() and chart._ch_hline.isVisible())

# 6. 关闭十字线 → 全部隐藏 + 状态重置，价格线保留
chart.set_crosshair_enabled(False)
app.processEvents()
chk("关闭后: 光标全隐藏",
   not chart._ch_vline.isVisible() and not chart._ch_hline.isVisible() and not chart._ch_label.isVisible())
chk("关闭后: 状态重置", chart._cross_idx == -1 and not chart._in_chart_area)
chk("关闭不影响价格线", chart._last_price_line.isVisible())

# 7. set_frame 后价格线隐藏（等新tick），十字线状态保留
chart.set_frame(frame)
app.processEvents()
chk("set_frame后: 价格线暂隐藏", not chart._last_price_line.isVisible())
chk("set_frame后: 十字线仍关闭", not chart.is_crosshair_enabled())

# 8. 配置项存在
chk("配置项: CROSSHAIR_CFG",
   all(k in CROSSHAIR_CFG for k in ("line_color", "line_width", "label_visible")))
chk("配置项: LAST_PRICE_CFG",
   all(k in LAST_PRICE_CFG for k in ("color", "width", "label_visible", "currency", "decimals")))

print()
print("🎉 十字线+实时价格线:", "全部通过" if ok else "存在失败")
sys.exit(0 if ok else 1)

"""主窗口集成验证：十字光标按钮 + 实时tick轮询（真实 MT5 取价）。"""
import sys
import time
sys.path.insert(0, r"E:\workbuddy\MT50802\wkf")

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from wkf.gui.main_window import MainWindow

win = MainWindow()
win.show()
app.processEvents()
time.sleep(1)
app.processEvents()

ok = True
def chk(name, cond):
    global ok
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        ok = False

# 1. 按钮存在且可勾选
chk("十字光标按钮存在", hasattr(win, "_crosshair_btn"))
chk("按钮可勾选(checkable)", win._crosshair_btn.isCheckable())
chk("默认未激活", not win._crosshair_btn.isChecked())

# 2. 点击按钮 → 图表十字线激活 + 按钮文字/样式反馈
win._crosshair_btn.setChecked(True)
app.processEvents()
chk("按钮激活→图表启用", win._chart.is_crosshair_enabled())
chk("按钮文字反馈", win._crosshair_btn.text() == "⛔ 关闭光标")
chk("按钮样式反馈", "3b82f6" in win._crosshair_btn.styleSheet())
chk("状态栏反馈", "已开启" in win._kline_status.text())

# 再次点击 → 关闭
win._crosshair_btn.setChecked(False)
app.processEvents()
chk("再次点击→图表关闭", not win._chart.is_crosshair_enabled())
chk("按钮文字恢复", win._crosshair_btn.text() == "➕ 十字光标")
chk("样式恢复", win._crosshair_btn.styleSheet() == "")

# 3. 实时 tick 链路：等待初始 fetch 完成后轮询取价 → 价格线可见
# 主窗口启动时会自动 fetch，等它完成
deadline = time.time() + 30
while not win._chart._frame and time.time() < deadline:
    time.sleep(0.5)
    app.processEvents()
chk("图表已加载数据", win._chart._frame is not None)

# 等待 tick 轮询（2s 周期）至少一次成功
price_line_visible = False
deadline = time.time() + 15
while time.time() < deadline:
    time.sleep(1)
    app.processEvents()
    if win._chart._last_price_line.isVisible():
        price_line_visible = True
        break
chk("tick轮询后价格线可见", price_line_visible)
if price_line_visible:
    p = win._chart._last_price_line.value()
    txt = win._chart._last_price_label.toPlainText()
    print(f"   最新成交价: {p:,.2f} | 标签: {txt}")
    chk("价格标签含货币单位", "USD" in txt)

# 4. 两功能同时启用
win._crosshair_btn.setChecked(True)
app.processEvents()
chk("十字线+价格线同时启用",
   win._chart.is_crosshair_enabled() and win._chart._last_price_line.isVisible())

print()
print("🎉 主窗口集成:", "全部通过" if ok else "存在失败")
sys.exit(0 if ok else 1)

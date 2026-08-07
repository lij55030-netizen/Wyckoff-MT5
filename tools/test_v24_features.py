"""WKF V2.4 迭代功能验证（offscreen，不依赖 AI）。"""
import sys
import re
sys.path.insert(0, r"E:\workbuddy\MT50802\wkf")

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from wkf.config.settings import load_settings, save_settings
from wkf.gui.main_window import MainWindow
from wkf.orchestrator.runner import run_analysis

ok = True
def chk(name, cond):
    global ok
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        ok = False

# 避免首次启动弹窗：先置 first_run=False 保存
s = load_settings()
s.general.first_run = False
save_settings(s, r"E:\workbuddy\MT50802\wkf\config\settings.json")

win = MainWindow()
win.show()
app.processEvents()

# 运行一次分析（不调 AI，快）
res = run_analysis("NQ1!", "15m", bar_count=60, settings=win._settings, with_ai=False)
assert res.ok, res.error
win._on_analysis_done(res)
app.processEvents()

# 1. 分析时间栏
dec_html = win._tab_decision.toHtml()
dec_txt = win._tab_decision.toPlainText()
chk("决策页含【本次分析时间】", "本次分析时间" in dec_txt)
chk("时间格式 年-月-日 时:分:秒",
   bool(re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", win._analysis_time or "")))
print("   本次分析时间:", win._analysis_time)

# 2. 历史记录统一时间戳
hist = win._history_list.toPlainText()
chk("历史记录含完整时间戳", win._analysis_time in hist)
chk("历史记录含多头/空头中文", "多头" in hist or "空头" in hist or "中性" in hist)
print("   历史记录行:", [l for l in hist.split(chr(10)) if l.strip()][-1])

# 3. Δ 列：首行横线 + 收盘价差 + 颜色
t = win._data_table
r0 = t.item(0, 10).text()
chk("Δ首行填横线", r0 == "—", )
delta_ok = True
for r in range(1, min(5, t.rowCount())):
    txt = t.item(r, 10).text()
    color = t.item(r, 10).foreground().color().name()
    if txt.startswith("↑"):
        if color != "#22c55e": delta_ok = False
    elif txt.startswith("↓"):
        if color != "#ef4444": delta_ok = False
    else:
        if txt != "—": delta_ok = False
chk("Δ其余行 正↑绿/负↓红/平—灰", delta_ok)
if t.rowCount() > 1:
    print("   Δ示例:", t.item(1, 10).text(), "|", t.item(2, 10).text())

# 4. 表格样式回滚开关
win._settings.general.table_style = "old"
win._populate_tabs(res.frame, res.wyckoff, res)
app.processEvents()
txt_old = win._tab_data.toPlainText()
chk("旧版纯文本模式生效", "序号 | 时间" in txt_old)
win._settings.general.table_style = "new"
win._populate_tabs(res.frame, res.wyckoff, res)
app.processEvents()
chk("新版表格模式恢复", win._data_table.isVisible() and not win._tab_data._text_view.isVisible())

# 5. 飞书推送：无 webhook 安全跳过 + 防抖 + 日志
from wkf.notify.feishu_notifier import push_analysis_notice, _last_push, _log_push, PUSH_LOG_PATH
s2 = load_settings()
s2.feishu.notify_enabled = True
s2.feishu.webhook_url = ""  # 模拟未配置
_last_push.clear()
r = push_analysis_notice(symbol="NQ1!", timeframe="15m", prob={"long": 70, "short": 20, "neutral": 10},
                         bias_zh="多头", price=29000.0, settings=s2)
chk("无Webhook时安全跳过(不抛异常)", r is False)
chk("防抖记录未写入(未发送)", "NQ1!" not in _last_push)
# 日志写入
import os
_log_push("NQ1!", False, "测试日志")
chk("推送日志本地留存", PUSH_LOG_PATH.exists() and "NQ1!" in PUSH_LOG_PATH.read_text(encoding="utf-8"))

# 6. 对话框新字段
from wkf.gui.settings_dialogs import FeishuDialog, IndicatorDialog
d1 = FeishuDialog(load_settings())
chk("飞书对话框含推送开关", hasattr(d1, "_notify_enabled"))
chk("飞书对话框含防抖/阈值字段", hasattr(d1, "_dedup") and hasattr(d1, "_prob_th"))
d2 = IndicatorDialog(load_settings())
chk("指标对话框含表格样式下拉", hasattr(d2, "_table_style"))
chk("表格样式默认new", d2._table_style.currentData() == "new")

print()
print("🎉 V2.4 功能验证:", "全部通过" if ok else "存在失败")
sys.exit(0 if ok else 1)

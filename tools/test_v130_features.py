"""WKF V1.3.0 功能验收验证（offscreen，不依赖 AI）。"""
import sys
import time
sys.path.insert(0, r"E:\workbuddy\MT50802\wkf")

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from wkf.config.settings import load_settings, save_settings
from wkf.gui.main_window import MainWindow, TIMEFRAME_ITEMS, TF_MINUTES
from wkf.orchestrator.runner import run_analysis
from wkf.util.timefmt import beijing_now_str, beijing_now
from wkf.util import audio_player

ok = True
def chk(name, cond):
    global ok
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        ok = False

# 0. 配置准备：避免首次启动弹窗 + 恢复默认基线（防测试间顺序耦合）
s0 = load_settings()
s0.general.first_run = False
s0.general.last_symbol = "GC1!"
s0.general.last_timeframe = "5m"
save_settings(s0, r"E:\workbuddy\MT50802\wkf\config\settings.json")

# ── 模块一：周期枚举与排序 ──────────────────────────────────────────────
expected = ["1分", "3分", "5分", "10分", "15分", "30分", "60分", "120分", "240分", "日线", "周线"]
actual_labels = [l for l, _ in TIMEFRAME_ITEMS]
chk("周期排序严格匹配(1分→周线)", actual_labels == expected)
chk("周期数量=11", len(TIMEFRAME_ITEMS) == 11)
chk("映射 日线=1440 分钟", TF_MINUTES["1d"] == 1440)
chk("映射 周线=10080 分钟", TF_MINUTES["1w"] == 10080)
chk("映射 3分=3 / 120分=120 / 240分=240", TF_MINUTES["3m"] == 3 and TF_MINUTES["2h"] == 120 and TF_MINUTES["4h"] == 240)

# ── 模块三：默认配置（验证 settings 类默认值 = 首次启动无配置时的默认）──
from wkf.config.settings import GeneralSettings as _GS
chk("默认品种=XAU(GC1!)", _GS().last_symbol == "GC1!")
chk("默认周期=5分", _GS().last_timeframe == "5m")

# ── 主窗口实例化 ────────────────────────────────────────────────────────
win = MainWindow()
win.show()
app.processEvents()
time.sleep(0.5)
app.processEvents()

# 模块一：下拉内容与初始选择
labels = [win._tf_combo.itemText(i) for i in range(win._tf_combo.count())]
chk("下拉显示文本顺序正确", labels == expected)
chk("下拉初始选择=5分", win._tf_combo.currentData() == "5m")
from PyQt6.QtWidgets import QComboBox as _CB
chk("自适应宽度已开启",
   win._tf_combo.sizeAdjustPolicy() == _CB.SizeAdjustPolicy.AdjustToContents)

# 模块三：品种-周期独立记忆（验收步骤：GC1!选30分 → 切NQ1!选10分 → 切回GC1!恢复30分）
g = win._settings.general
g.per_symbol_timeframe = {}
# 1) 先让 combo 与内存状态同步（GC1!/30m，触发周期切换分支写入记忆）
win._sym_combo.setCurrentText("GC1!")
app.processEvents()
win._tf_combo.setCurrentIndex(win._tf_combo.findData("30m"))
app.processEvents()
chk("GC1! 选30分已写入记忆", g.per_symbol_timeframe.get("GC1!") == "30m")
# 2) 切到 NQ1!（品种切换：保存 GC1!→30m，NQ1! 无记忆）
win._sym_combo.setCurrentText("NQ1!")
app.processEvents()
# 3) NQ1! 上选 10 分（周期切换分支 → 写入记忆）
win._tf_combo.setCurrentIndex(win._tf_combo.findData("10m"))
app.processEvents()
chk("NQ1! 选10分已写入记忆", g.per_symbol_timeframe.get("NQ1!") == "10m")
# 4) 切回 GC1! → 自动恢复 30m
win._sym_combo.setCurrentText("GC1!")
app.processEvents()
chk("切回GC1!恢复记忆周期30分", win._current_tf() == "30m")
# 5) 再切 NQ1! → 自动恢复 10m
win._sym_combo.setCurrentText("NQ1!")
app.processEvents()
chk("再切NQ1!恢复记忆周期10分", win._current_tf() == "10m")
# 6) 测试结束恢复默认记忆（避免污染）
g.per_symbol_timeframe = {}
g.last_symbol = "GC1!"
g.last_timeframe = "5m"
save_settings(win._settings, r"E:\workbuddy\MT50802\wkf\config\settings.json")

# 模块四：缓存命中（断开信号防真实渲染，仅测命中分支耗时）
win._fetch_done.disconnect()
key = ("NQ1!", win._current_tf())
win._frame_cache[key] = (time.monotonic(), object(), None)
t0 = time.monotonic()
win._on_fetch_data()  # 命中缓存 → 立即 emit
hit_ms = (time.monotonic() - t0) * 1000
chk(f"缓存命中毫秒级返回 ({hit_ms:.0f}ms)", hit_ms < 200)
win._frame_cache.clear()
win._fetch_done.connect(win._on_fetch_done)

# 模块五：汉化（用不依赖 AI 的分析结果渲染决策页）
res = run_analysis("GC1!", "15m", bar_count=60, settings=win._settings, with_ai=False)
assert res.ok, res.error
win._on_analysis_done(res)
app.processEvents()
dec_html = win._tab_decision.toHtml()
dec_txt = win._tab_decision.toPlainText()
eng_words = ["buy", "sell", "absorption", "active_side", "reversal_stage", "none"]
has_eng = any(w in dec_txt.lower() for w in eng_words)
chk("订单流区域无英文词汇(汉化)", not has_eng)
chk("活跃方中文", "活跃方：买方" in dec_txt or "活跃方：卖方" in dec_txt or "活跃方：无" in dec_txt)
if "吸收" in dec_txt:
    chk("反转阶段汉化(吸收)", True)
elif "吸筹" in dec_txt or "派发" in dec_txt:
    chk("反转阶段汉化(其他阶段)", True)
else:
    chk("反转阶段汉化(任意中文阶段)", False)

# 补充1：北京时钟 + 决策时间北京时间
win._update_clock()
app.processEvents()
import re
m = re.search(r"🕐 (\d{2}:\d{2}:\d{2})", win._clock_label.text())
chk("顶部北京时钟 HH:MM:SS", bool(m))
bjt = beijing_now()
chk("决策分析时间=北京时间(与beijing_now一致)",
   win._analysis_time.startswith(bjt.strftime("%Y-%m-%d")) if win._analysis_time else False)

# 补充2：邮箱标签
chk("问AI右侧邮箱标签", hasattr(win, "_contact_label") and "lij55030@gmail.com" in win._contact_label.text())
from PyQt6.QtCore import Qt as _Qt
chk("邮箱可选中复制",
   bool(win._contact_label.textInteractionFlags() & _Qt.TextInteractionFlag.TextSelectableByMouse))

# 补充3：提示音防抖
audio_player._last_alert.clear()
first = audio_player.play_alert("NQ1!", dedup_s=30)
audio_player._last_alert.clear()
second = audio_player.play_alert("NQ1!", dedup_s=30)  # 重置后应 True（wav 存在）
audio_player._last_alert["NQ1!"] = time.time()  # 模拟刚响过
third = audio_player.play_alert("NQ1!", dedup_s=30)  # 30秒内应 False
chk("提示音播放(有wav)", second is True or first is True)
chk("30秒同品种防抖生效", third is False)

print()
print("🎉 V1.3.0 功能验证:", "全部通过" if ok else "存在失败")
import time as _t
_t.sleep(2)  # 等待后台 fetch/tick 线程收尾，避免退出时 emit 到已销毁窗口
sys.exit(0 if ok else 1)

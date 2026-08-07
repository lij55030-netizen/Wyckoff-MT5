"""需求1-3 功能验证（offscreen）：时间戳补齐 / 磁盘缓存 / 图表交互。"""
import sys
import time
sys.path.insert(0, r"E:\workbuddy\MT50802\wkf")

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from wkf.config.settings import load_settings
from wkf.gui.main_window import MainWindow
from wkf.orchestrator.runner import run_analysis, fetch_frame_cached
from wkf.data import cache_manager

ok = True
def chk(name, cond):
    global ok
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        ok = False

# 避免首次启动弹窗
s = load_settings()
s.general.first_run = False
from wkf.config.settings import save_settings

# 【改动点】测试隔离：清空磁盘缓存后再测"缓存写入/命中"，避免残留缓存干扰断言。
# 【涉及文件】tools/test_v131_features.py
# 【验证方式】本测试独立/连带运行均通过；其他测试不再受本测试 60 根缓存影响
try:
    if cache_manager.CACHE_DIR.exists():
        for _f in cache_manager.CACHE_DIR.glob("kline_*.json"):
            _f.unlink(missing_ok=True)
except Exception:
    pass
save_settings(s, r"E:\workbuddy\MT50802\wkf\config\settings.json")

win = MainWindow()
win.show()
app.processEvents()
time.sleep(0.5)
app.processEvents()

# ── 需求1：时间戳补齐 ───────────────────────────────────────────────────
res = run_analysis("NQ1!", "15m", bar_count=60, settings=win._settings, with_ai=False)
assert res.ok, res.error
win._on_analysis_done(res)
app.processEvents()

# 1a. 历史记录含完整北京时间戳
hist = win._history_list.toPlainText()
import re
m = re.search(r"\[1\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", hist)
chk("历史记录前置完整北京时间戳", bool(m))
if m:
    print("   历史记录:", [l for l in hist.split(chr(10)) if l.strip()][-1])

# 1b. 诊断面板顶部生成时间（北京时间）
diag_txt = win._tab_diagnosis.toPlainText()
chk("诊断面板顶部生成时间", "诊断生成时间" in diag_txt)
chk("诊断时间与决策同源(同日)", win._analysis_time[:10] in diag_txt or win._analysis_time[:13] in diag_txt)

# 1c. 快照预览底部生成时间
chk("快照预览底部生成时间", "快照生成时间" in win._snapshot_time_label.text())
chk("快照时间含年月日时分秒",
   bool(re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", win._snapshot_time_label.text())))

# 1d. 保存快照文件名含时间戳（直接调用保存方法，拦截消息框）
win._tab_snapshot_text.setPlainText("测试快照内容")
from PyQt6.QtWidgets import QMessageBox
QMessageBox.information = lambda *a, **k: None  # 拦截弹窗
QMessageBox.warning = lambda *a, **k: None
win._save_snapshot()
import glob
snapshots = glob.glob(r"E:\workbuddy\MT50802\wkf\output\snapshot_*.txt")
chk("快照文件已保存", len(snapshots) >= 1)
if snapshots:
    name = snapshots[-1]
    chk("快照文件名含时间戳", bool(re.search(r"snapshot_\d{8}_\d{6}", name)))
    content = open(name, encoding="utf-8").read()
    chk("快照文件内容含生成时间", "生成时间" in content)
    print("   快照文件:", name)

# ── 需求2：磁盘缓存 ─────────────────────────────────────────────────────
from wkf.data.mt5_source import fetch_mt5_bars

# 2a. 缓存写入/读取往返
# 【改动点】测试隔离：缓存往返验证使用独立测试键 "TST!"（不污染真实品种 NQ1! 5m，
# 否则后续 switch 测试期望 576 根会命中本测试写入的 60 根陈旧缓存）。
# 【涉及文件】tools/test_v131_features.py
# 【验证方式】v131 与 switch 任意顺序运行均通过
bars = fetch_mt5_bars("NQ1!", "5m", 60)
chk("缓存写入", cache_manager.disk_cache_put("TST!", "5m", bars))
bars2 = cache_manager.disk_cache_get("TST!", "5m")
chk("缓存读取往返一致", bars2 is not None and len(bars2) == len(bars))
if bars2:
    chk("缓存K线字段一致", abs(bars2[0].close - bars[0].close) < 1e-9)

# 2b. fetch_frame_cached 磁盘命中（首次后再次调用 from_cache=True）
cache_manager.CACHE_TTL_S = 300
frame1, wa1, err1, from_net = fetch_frame_cached("GC1!", "10m", bar_count=48,
                                                  settings=load_settings(), use_disk_cache=True)
frame2, wa2, err2, from_cache = fetch_frame_cached("GC1!", "10m", bar_count=48,
                                                   settings=load_settings(), use_disk_cache=True)
chk("首次拉取成功", frame1 is not None and not err1)
chk("二次访问磁盘缓存命中", from_cache is True)
chk("磁盘命中frame可用", frame2 is not None and len(frame2.bars) == len(frame1.bars))
t0 = time.monotonic()
frame3, _, _, _ = fetch_frame_cached("GC1!", "10m", bar_count=48,
                                     settings=load_settings(), use_disk_cache=True)
disk_ms = (time.monotonic() - t0) * 1000
chk(f"磁盘缓存加载耗时 {disk_ms:.0f}ms (<1000ms)", disk_ms < 1000)
print(f"   磁盘命中加载: {disk_ms:.0f}ms")

# ── 需求3：图表交互 ─────────────────────────────────────────────────────
# 3a. 鼠标交互已开启
chk("主图鼠标拖拽/缩放开启", win._chart._plot.getPlotItem().vb.state["mouseEnabled"] == [True, True])
chk("RSI副图鼠标交互开启", win._chart._rsi_plot.getPlotItem().vb.state["mouseEnabled"] == [True, True])

# 3b. 用户手动缩放后刷新视图不重置
chart = win._chart
vb = chart._plot.getPlotItem().vb
# 模拟用户缩放：直接设置视图范围 + 触发手动标记
chart._user_viewed = False
chart.set_frame(res.frame)  # 首次（未操作）→ autoRange
auto_x = vb.viewRange()[0]
# 模拟用户手动缩放（缩小到前半段）
chart._user_viewed = True
vb.setRange(xRange=(0, 20), padding=0)
manual_x = vb.viewRange()[0]
chart.set_frame(res.frame)  # 同品种刷新 → 应保持用户视图
after_x = vb.viewRange()[0]
chk("手动缩放后刷新视图保持", abs(after_x[0] - manual_x[0]) < 1.0 and abs(after_x[1] - manual_x[1]) < 1.0)
# 切换品种 → 重新适配
res2 = run_analysis("ES1!", "15m", bar_count=60, settings=win._settings, with_ai=False)
chart.set_frame(res2.frame)
chk("切换品种后重新适配视图", chart._last_symbol == "ES1!" and not chart._user_viewed)

print()
print("🎉 需求1-3 验证:", "全部通过" if ok else "存在失败")
time.sleep(2)
sys.exit(0 if ok else 1)

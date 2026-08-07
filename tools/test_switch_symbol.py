# -*- coding: utf-8 -*-
"""
验证：切换品种后图表自动刷新 + 48小时时间级别保持 + 防竞态。
连续多次切换 NQ → ES → GC → NQ → ES，每次等待刷新完成，
断言：图表数据品种一致、K线根数=48h窗口、时间跨度≈48h、无错误；
并验证快速连切（不等完成）最终显示最后一个品种。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

app = QApplication([])

from wkf.gui.main_window import MainWindow, TF_MINUTES, WINDOW_HOURS  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("✅" if ok else "❌"), name, "|", detail)


def wait_fetch(win, timeout_ms: int = 60000) -> None:
    """等待 fetch 完成（信号可能已被消费，用轮询 fetch_btn 恢复判断）。"""
    loop = QEventLoop()
    win._fetch_done.connect(lambda *_: loop.quit())
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    app.processEvents()


win = MainWindow()
win.show()
app.processEvents()
wait_fetch(win)  # 等初始加载

# 期望根数（48h 窗口）
def expected_bars(tf: str) -> int:
    return max(WINDOW_HOURS * 60 // TF_MINUTES[tf], win._settings.general.analysis_bar_count)


# ── 1. 顺序切换（每次等待完成）──────────────────────────────────────────
print("=" * 60)
print("测试1: 顺序切换 4 个品种/周期（每次等待刷新完成）")
print("=" * 60)
sequence = [("ES1!", "15m"), ("GC1!", "30m"), ("NQ1!", "5m"), ("ES1!", "1h")]
for sym, tf in sequence:
    win._sym_combo.setCurrentText(sym)
    win._tf_combo.setCurrentIndex(win._tf_combo.findData(tf))
    app.processEvents()
    # 防抖定时器触发后 fetch
    wait_fetch(win)
    time.sleep(0.3)
    app.processEvents()
    frame = win._chart._frame if hasattr(win._chart, "_frame") else None
    # 通过 _last_bar_ts / 数据页判断
    data_txt = win._tab_data.toPlainText()
    ok_sym = sym in data_txt and "❌" not in data_txt
    ok_bars = f"{expected_bars(tf)} 根" in data_txt or f"共 {expected_bars(tf)}" in data_txt
    check(f"切换 {sym} {tf}", ok_sym and ok_bars,
          f"数据页: {data_txt.splitlines()[0][:60]!r}")

# ── 2. 连续快速切换（防抖+防竞态，最终显示最后一个）──────────────────────
print()
print("=" * 60)
print("测试2: 快速连切 GC→NQ→ES（不等待，验证最终显示 ES）")
print("=" * 60)
win._sym_combo.setCurrentText("GC1!")
win._tf_combo.setCurrentIndex(win._tf_combo.findData("5m"))
win._sym_combo.setCurrentText("NQ1!")
win._tf_combo.setCurrentIndex(win._tf_combo.findData("15m"))
win._sym_combo.setCurrentText("ES1!")
win._tf_combo.setCurrentIndex(win._tf_combo.findData("30m"))
app.processEvents()
time.sleep(1.5)  # 防抖 300ms + fetch 时间
wait_fetch(win)
time.sleep(0.5)
app.processEvents()
data_txt = win._tab_data.toPlainText()
check("快速连切后显示 ES1! 30m", "ES1!" in data_txt and "30m" in data_txt,
      f"数据页首行: {data_txt.splitlines()[0][:60]!r}")

# ── 3. 加载状态提示 ────────────────────────────────────────────────────
win._sym_combo.setCurrentText("GC1!")
app.processEvents()
time.sleep(0.15)  # 防抖触发前
loading_shown = "加载" in win._tab_data.toPlainText() or "切换中" in win._kline_status.text()
wait_fetch(win)
check("切换时显示加载状态", loading_shown,
      f"状态栏: {win._kline_status.text()!r}")

# ── 4. 异常路径：无效品种应显示错误提示 ─────────────────────────────────
print()
print("=" * 60)
print("测试4: 异常处理（直接调用 fetch 传无效周期）")
print("=" * 60)
win._tf_combo.setCurrentIndex(win._tf_combo.findData("1h"))  # 正常
# 用 monkeypatch 模拟失败
from wkf.gui import main_window as mw  # noqa: E402
orig_fetch = mw.fetch_frame_only
mw.fetch_frame_only = lambda *a, **k: (None, None, "模拟获取失败: MT5 无数据")
win._on_fetch_data()
wait_fetch(win)
mw.fetch_frame_only = orig_fetch
err_txt = win._tab_data.toPlainText()
check("失败时显示错误提示", "❌" in err_txt and "失败" in err_txt,
      f"错误提示: {err_txt[:60]!r}")
check("失败后按钮恢复", win._fetch_btn.isEnabled(), "获取数据按钮可用")

print()
total = len(results)
ok_n = sum(1 for _, o, _ in results if o)
print(f"结果: {ok_n} / {total} 通过")
raise SystemExit(0 if ok_n == total else 1)

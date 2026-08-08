# -*- coding: utf-8 -*-
"""V3.0 品种扩容回归：MT5 全部品种下拉 + 任意品种/周期切换卡顿检测。

流程：
  1. 品种下拉应包含 MT5 终端全部品种（>200），可见品种排前；
  2. 依次切换多品种 × 多周期，每次加载完成后保持 5 秒，
     期间用 500ms 定时器计数验证 UI 事件循环无冻结；
  3. 记录每次 fetch 耗时、K 线渲染结果（frame/图表 items）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from wkf.gui.main_window import MainWindow  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("✅" if ok else "❌"), name, "|", detail)


def wait_fetch(win, timeout_ms: int = 60000) -> tuple[bool, float]:
    """等待 fetch 完成，返回 (是否完成, 耗时秒)。"""
    t0 = time.monotonic()
    loop = QEventLoop()
    done = [False]
    win._fetch_done.connect(lambda *_: (done.__setitem__(0, True), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    app.processEvents()
    return done[0], time.monotonic() - t0


win = MainWindow()
win.show()
app.processEvents()

# ── 1. 品种下拉完整性 ─────────────────────────────────────────────────
print("=" * 60)
print("测试1: 品种下拉包含 MT5 全部品种")
print("=" * 60)
syms = [win._sym_combo.itemText(i) for i in range(win._sym_combo.count())]
print(f"品种总数: {len(syms)}")
print(f"前 8 个: {syms[:8]}")
check("品种数 >= 200", len(syms) >= 200, f"实际 {len(syms)}")
for must in ("XAUUSD", "US500c", "USTECHc", "WTIUSD", "BTCUSDT"):
    check(f"包含 {must}", must in syms, "")

# ── 2. 多品种 × 多周期切换 + 5 秒保持检测 ─────────────────────────────
print()
print("=" * 60)
print("测试2: 任意品种/周期切换，保持 5 秒，观察 K 线与卡顿")
print("=" * 60)
wait_fetch(win)  # 初始加载

# 事件循环响应计数器（每 500ms +1；冻结则计数停止）
ticks = [0]
timer = QTimer()
timer.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))
timer.start(500)

switches = [
    ("XAUUSD", "5m"), ("XAUUSD", "15m"), ("XAUUSD", "1h"),
    ("WTIUSD", "15m"), ("BTCUSDT", "5m"),
    ("US500c", "5m"), ("US500c", "1h"), ("USTECHc", "15m"),
]
fetch_times: list[float] = []
ok_count = 0
for sym, tf in switches:
    win._sym_combo.setCurrentText(sym)
    win._tf_combo.setCurrentIndex(win._tf_combo.findData(tf))
    app.processEvents()
    ok, elapsed = wait_fetch(win)
    fetch_times.append(elapsed)
    # 保持 5 秒：验证事件循环持续响应（约 10 次 tick）
    t0 = ticks[0]
    hold_loop = QEventLoop()
    QTimer.singleShot(5000, hold_loop.quit)
    hold_loop.exec()
    app.processEvents()
    tick_delta = ticks[0] - t0
    frame = win._chart._frame
    rendered = frame is not None and len(win._chart._items) > 0
    status = win._kline_status.text()
    frozen = tick_delta < 8  # 5 秒内应有约 10 次 500ms 响应，<8 视为卡顿
    detail = (
        f"{sym} {tf}: fetch {elapsed:.1f}s | 5s 响应 {tick_delta}/10 | "
        f"K线 {len(frame.bars) if frame else 0} 根 | {status[:30]}"
    )
    ok_all = ok and rendered and not frozen
    ok_count += 1 if ok_all else 0
    check(f"切换 {sym} {tf}", ok_all, detail)

avg_fetch = sum(fetch_times) / len(fetch_times)
print(f"平均加载耗时: {avg_fetch:.2f}s | 全部成功: {ok_count}/{len(switches)}")
# 加载耗时是子线程数据拉取时间（首次冷加载含 MT5 拉取 + tick 订单流），
# 卡顿判定以 5 秒保持期事件循环响应为准（上面已逐项检查 ≥8/10）。
check("平均首次加载 <= 10 秒（子线程不阻塞 UI）", avg_fetch <= 10.0,
      f"平均 {avg_fetch:.2f}s")
check("全部切换成功且无冻结", ok_count == len(switches),
      f"{ok_count}/{len(switches)}")

timer.stop()
win.close()
app.processEvents()

total = len(results)
ok_n = sum(1 for _, o, _ in results if o)
print()
print(f"结果: {ok_n} / {total} 通过")
raise SystemExit(0 if ok_n == total else 1)

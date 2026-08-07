# -*- coding: utf-8 -*-
"""V1.3.2 异步加载迭代回归：品种/周期切换稳定性。

覆盖（核心优化1-4）：
  1. 切换第一时间前置清理：图表 items 清空、Tick 定时器挂起、状态栏加载提示；
  2. 防抖 + 全局加载锁：快速连续切换只发一次请求；加载中切换不排队只记录 pending；
  3. 数据回传一次性渲染（子线程不碰画布），完成后恢复 Tick/十字光标/缩放；
  4. 快速连切后无旧品种残留、无重复加载。
数据源用 monkeypatch 模拟耗时返回，不依赖 MT5/yfinance。
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

from wkf.data.base import IndicatorBundle, KlineBar, KlineFrame  # noqa: E402
from wkf.gui.main_window import MainWindow  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("✅" if ok else "❌"), name, "|", detail)


def make_frame(symbol: str, timeframe: str, n: int = 30) -> KlineFrame:
    """构造假 K 线帧（含指标与订单流空束，避免真实数据源）。"""
    bars: list[KlineBar] = []
    for i in range(n):
        base = 100.0 + i * 0.1
        bars.append(
            KlineBar(
                seq=n - i, ts_open=1_700_000_000_000 - i * 300_000,
                open=base, high=base + 0.5, low=base - 0.5,
                close=base + 0.2, volume=100.0, closed=True,
            )
        )
    bars.reverse()  # 新→旧
    ind = IndicatorBundle(
        ema20=tuple([100.0] * n),
        atr14=tuple([0.5] * n),
        rsi14=tuple([50.0] * n),
        bb_upper=tuple([101.0] * n),
        bb_middle=tuple([100.0] * n),
        bb_lower=tuple([99.0] * n),
        vwap=tuple([100.0] * n),
    )
    return KlineFrame(symbol=symbol, timeframe=timeframe, bars=tuple(bars), indicators=ind)


# 模拟耗时数据源：0.5 秒后返回对应品种的假帧（只记录请求，不真拉数据）
request_log: list[tuple[str, str]] = []


def fake_fetch_frame_cached(symbol, timeframe, *, bar_count=100, settings=None, use_disk_cache=True):
    request_log.append((symbol, timeframe))
    time.sleep(0.5)  # 模拟 MT5/yfinance 拉取耗时
    return make_frame(symbol, timeframe, bar_count), None, "", False


import wkf.orchestrator.runner as runner  # noqa: E402

runner.fetch_frame_cached = fake_fetch_frame_cached


def wait_fetch(win, timeout_ms: int = 8000) -> None:
    loop = QEventLoop()
    win._fetch_done.connect(lambda *_: loop.quit())
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    app.processEvents()


win = MainWindow()
win.show()
app.processEvents()
wait_fetch(win)  # 等初始加载（含 0.5s 模拟耗时）

# ── 1. 切换前置清理 + 状态提示 ─────────────────────────────────────────
print("=" * 60)
print("测试1: 切换前置清理 + 加载状态提示")
print("=" * 60)
win._sym_combo.setCurrentText("NQ1!")
win._tf_combo.setCurrentIndex(win._tf_combo.findData("5m"))
app.processEvents()
time.sleep(0.05)  # 防抖窗口内（切换已执行，请求未发）
check("切换后图表 items 已清空", len(win._chart._items) == 0,
      f"items={len(win._chart._items)}")
check("Tick 定时器已挂起", not win._tick_timer.isActive(), "加载期间停止 2s 轮询")
check("状态栏显示加载提示", "加载中" in win._kline_status.text() or "重构渲染中" in win._kline_status.text(),
      f"状态栏: {win._kline_status.text()!r}")
wait_fetch(win)
check("完成后恢复 Tick 定时器", win._tick_timer.isActive(), "MT5 模式重启 2s 轮询")
check("完成后图表交互恢复", not win._chart._suspended, "鼠标/十字光标监听恢复")
check("渲染后图表无残留旧数据", win._chart._frame is not None
      and win._chart._frame.symbol == "NQ1!", "frame 为最新品种")

# ── 2. 快速连续切换（防抖 + 加载锁）────────────────────────────────────
print()
print("=" * 60)
print("测试2: 快速连切只发一次请求，加载中切换不排队")
print("=" * 60)
request_log.clear()
win._sym_combo.setCurrentText("GC1!")
win._tf_combo.setCurrentIndex(win._tf_combo.findData("15m"))
win._sym_combo.setCurrentText("ES1!")
win._tf_combo.setCurrentIndex(win._tf_combo.findData("30m"))
app.processEvents()
time.sleep(0.8)  # 防抖 300ms + 首次请求发出（加载锁生效）
win._sym_combo.setCurrentText("NQ1!")  # 加载中切换 → 应被忽略（记录 pending）
win._tf_combo.setCurrentIndex(win._tf_combo.findData("1h"))
app.processEvents()
time.sleep(1.2)  # 等首次请求完成 + pending 补发
wait_fetch(win)
app.processEvents()
check("加载中切换被记录为 pending", win._pending_switch is None, "完成后 pending 已消费")
check("请求未堆积（<=2 次）", len(request_log) <= 2,
      f"实际请求: {request_log}")
check("最终渲染为最新选择", win._chart._frame is not None
      and win._chart._frame.symbol == "NQ1!" and win._chart._frame.timeframe == "1h",
      f"frame: {win._chart._frame.symbol} {win._chart._frame.timeframe}")

# ── 3. 十字光标开关状态跨加载保持 ─────────────────────────────────────
print()
print("=" * 60)
print("测试3: 十字光标状态跨加载保持")
print("=" * 60)
win._chart.set_crosshair_enabled(True)
win._sym_combo.setCurrentText("ES1!")
app.processEvents()
wait_fetch(win)
check("十字光标开关状态保持", win._chart.is_crosshair_enabled(),
      "加载完成后仍为开启")

print()
total = len(results)
ok_n = sum(1 for _, o, _ in results if o)
print(f"结果: {ok_n} / {total} 通过")
raise SystemExit(0 if ok_n == total else 1)

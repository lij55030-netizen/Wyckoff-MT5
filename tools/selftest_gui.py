# -*- coding: utf-8 -*-
"""
WKF GUI 自检脚本（阶段2：逐项测试 + 阶段4：数据采集）
=====================================================
测试方式：offscreen 实例化 MainWindow，程序化调用每个按钮/菜单的槽函数，
对每个测试项「操作 → 截图 → 断言」，输出结构化测试记录。

注意：对话框的 _on_save() 会写入真实 config/settings.json，
测试前先备份，测试后恢复，避免污染用户配置。
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])

from wkf.config.settings import SETTINGS_JSON_PATH, load_settings, save_settings  # noqa: E402
from wkf.gui.main_window import MainWindow  # noqa: E402
from wkf.gui.settings_dialogs import AIModelDialog, FeishuDialog, IndicatorDialog  # noqa: E402

SHOTS = PROJECT_ROOT / "test_reports" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

# ── 测试记录 ────────────────────────────────────────────────────────────
RECORDS: list[dict] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RECORDS.append({"name": name, "ok": ok, "detail": detail})
    mark = "✅" if ok else "❌"
    print(f"{mark} {name} | {detail}")


def shot(name: str, widget) -> None:
    path = SHOTS / f"{name}.png"
    widget.grab().save(str(path))
    print(f"📸 {path.name}")


def wait_signal(signal, timeout_ms: int = 120000) -> bool:
    """等待信号触发，超时返回 False。"""
    loop = QEventLoop()
    signal.connect(lambda *_: loop.quit())
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return True


# ── 阶段2：逐项测试 ─────────────────────────────────────────────────────
print("=" * 70)
print("阶段2 开始：逐项测试")
print("=" * 70)

# 备份配置（带时间戳，防止多次运行时覆盖上一次备份导致原始值丢失）
import datetime as _dt  # noqa: E402

backup = SETTINGS_JSON_PATH.with_suffix(f".bak.{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}")
shutil.copy2(SETTINGS_JSON_PATH, backup)
print(f"🔒 已备份配置 -> {backup.name}")


def restore_config() -> None:
    # 恢复为**最初**的备份（若存在），并清理本次备份
    import glob

    baks = sorted(glob.glob(str(SETTINGS_JSON_PATH.with_suffix(".bak.*"))))
    if baks:
        shutil.copy2(baks[0], SETTINGS_JSON_PATH)
    if backup.exists():
        backup.unlink()
    print("🔓 已恢复配置")


import atexit  # noqa: E402

atexit.register(restore_config)  # 无论正常/异常退出都恢复配置


win = MainWindow()
win.resize(1280, 800)
win.show()
app.processEvents()
shot("02_offscreen初始界面", win)

# ── 测试项1：菜单栏结构 ─────────────────────────────────────────────────
menubar = win.menuBar()
menus = [a.text() for a in menubar.actions() if a.text()]
record("菜单栏结构", "⚙ 设置" in menus and "ℹ 关于" in menus, f"菜单: {menus}")
sm = next(a.menu() for a in menubar.actions() if "设置" in a.text())
items = [a.text() for a in sm.actions()]
record("设置菜单3项", len(items) == 3, f"项: {items}")

# ── 测试项2：AI 模型设置对话框 ──────────────────────────────────────────
dlg = AIModelDialog(win._settings, win)
dlg.show()
app.processEvents()
shot("03_AI模型设置对话框", dlg)
model_old = win._settings.provider.model
dlg._model.setText("deepseek-v4-flash")
dlg._context.setValue(200000)
dlg._thinking.setChecked(False)
dlg._on_save()  # 触发保存逻辑（等于点「保存」按钮）
reloaded = load_settings()
ok = reloaded.provider.model == "deepseek-v4-flash" and reloaded.provider.context_window == 200000
record("AI模型设置-保存生效", ok,
       f"model: {model_old}->{reloaded.provider.model}, ctx: {reloaded.provider.context_window}")

# ── 测试项3：飞书通知设置对话框 ──────────────────────────────────────────
dlg2 = FeishuDialog(load_settings(), win)
dlg2.show()
app.processEvents()
shot("04_飞书设置对话框", dlg2)
old_webhook = dlg2._webhook.text()
dlg2._enabled.setChecked(True)
dlg2._webhook.setText("https://open.feishu.cn/open-apis/bot/v2/hook/test-123")
dlg2._on_save()
r2 = load_settings()
ok2 = r2.feishu.webhook_url == "https://open.feishu.cn/open-apis/bot/v2/hook/test-123" and r2.feishu.enabled
record("飞书通知设置-保存生效", ok2, f"webhook: {old_webhook[:20]}...->{r2.feishu.webhook_url[:35]}...")

# ── 测试项4：其他设置（指标参数）对话框 ──────────────────────────────────
dlg3 = IndicatorDialog(load_settings(), win)
dlg3.show()
app.processEvents()
shot("05_指标参数设置对话框", dlg3)
dlg3._rsi_period.setValue(21)
dlg3._va_pct.setValue(0.700)
dlg3._swing_window.setValue(30)
dlg3._on_save()
r3 = load_settings()
ok3 = r3.indicators.rsi_period == 21 and abs(r3.indicators.value_area_pct - 0.7) < 0.001 and r3.indicators.swing_window == 30
record("指标参数设置-保存生效", ok3,
       f"RSI:{r3.indicators.rsi_period} VA:{r3.indicators.value_area_pct} 摆动:{r3.indicators.swing_window}")

# ── 测试项5：🔄 获取数据按钮 ─────────────────────────────────────────────
win._on_fetch_data()
wait_signal(win._fetch_done, 60000)
app.processEvents()
shot("06_获取数据后", win)
data_txt = win._tab_data.toPlainText()
record("获取数据-数据页更新", "分析数据" in data_txt or "数据已更新" in data_txt,
       f"数据页前50字: {data_txt[:50]!r}")
record("获取数据-图表渲染", len(win._chart._items) > 100, f"图表 items: {len(win._chart._items)}")

# ── 测试项6：📝 提交分析按钮（完整管线含 AI）────────────────────────────
win._on_analyze()
wait_signal(win._analysis_done, 180000)
app.processEvents()
shot("07_提交分析后", win)
snap = win._tab_snapshot.toPlainText()
diag = win._tab_diagnosis.toPlainText()
dec = win._tab_decision.toPlainText()
ai = win._tab_ai.toPlainText()
hist = win._history_list.toPlainText()
record("提交分析-快照页", "行情快照" in snap and "RSI14" in snap, f"快照: {snap[:40]!r}")
record("提交分析-诊断页", "威科夫" in diag or "背景" in diag, f"诊断前40字: {diag[:40]!r}")
record("提交分析-决策页", "交易决策" in dec and "倾向" in dec, f"决策: {dec[:40]!r}")
record("提交分析-AI页", "置信度" in ai, f"AI页含置信度: {'置信度' in ai}")
record("提交分析-历史记录", "[1]" in hist, f"历史: {hist[:60]!r}")
record("提交分析-按钮恢复", win._analyze_btn.isEnabled(), "按钮可用状态")

# ── 测试项7：♾ 持续跟踪分析开关 ──────────────────────────────────────────
win._auto_check.setChecked(True)
app.processEvents()
ok_on = win._auto_active and win._auto_timer.isActive()
record("持续跟踪-开启", ok_on, f"auto_active={win._auto_active} timer={win._auto_timer.isActive()}")
win._auto_check.setChecked(False)
app.processEvents()
ok_off = not win._auto_active and not win._auto_timer.isActive()
record("持续跟踪-关闭", ok_off, f"auto_active={win._auto_active} timer={win._auto_timer.isActive()}")

# ── 测试项8：关于对话框 ─────────────────────────────────────────────────
about_calls = []
orig_about = QMessageBox.about
QMessageBox.about = lambda *a, **k: about_calls.append(a[2] if len(a) > 2 else "")
win._show_about()
QMessageBox.about = orig_about
record("关于对话框", len(about_calls) == 1 and "WKF" in (about_calls[0] or ""),
       f"弹窗调用: {len(about_calls)}次")

# ── 测试项9：品种/周期切换 ──────────────────────────────────────────────
win._sym_combo.setCurrentText("GC1!")
win._tf_combo.setCurrentText("30m")
app.processEvents()
record("品种/周期切换", win._sym_combo.currentText() == "GC1!" and win._tf_combo.currentText() == "30m",
       f"现在: {win._sym_combo.currentText()} {win._tf_combo.currentText()}")

# ── 阶段4：数据采集（用当前 GC1! 30m 跑一次完整分析导出 JSON）────────────
print("=" * 70)
print("阶段4 开始：数据采集")
print("=" * 70)
from wkf.orchestrator.runner import run_analysis  # noqa: E402
import json  # noqa: E402

res = run_analysis("GC1!", "30m", bar_count=120, settings=win._settings, with_ai=True)
export = {
    "symbol": res.symbol, "timeframe": res.timeframe, "ok": res.ok, "error": res.error,
    "latency_ms": res.latency_ms, "steps": res.steps,
    "ai_direction": (res.ai_diagnosis or {}).get("direction"),
    "ai_confidence": (res.ai_diagnosis or {}).get("diagnosis_confidence"),
    "ai_cycle": (res.ai_diagnosis or {}).get("cycle_position"),
    "ai_raw": res.ai_raw, "ai_reasoning": res.ai_reasoning,
    "usage": res.usage,
}
if res.wyckoff is not None:
    w = res.wyckoff
    export["wyckoff"] = {
        "price": w.price, "bias": w.bias, "trigger": w.trigger, "invalidation": w.invalidation,
        "background_regime": w.background.regime,
        "background_phase": w.background.phase,
        "background_hh_hl": w.background.hh_hl_count,
        "background_lh_ll": w.background.lh_ll_count,
        "background_reasoning": w.background.reasoning,
        "value_area": None if w.value_area is None else {
            "vah": w.value_area.vah, "val": w.value_area.val, "vpoc": w.value_area.vpoc,
            "vwap": w.value_area.vwap, "hvn": w.value_area.hvn, "lvn": w.value_area.lvn,
            "va_width": w.value_area.va_width,
        },
        "orderflow": None if w.orderflow is None else {
            "delta": w.orderflow.delta, "cumulative_delta": w.orderflow.cumulative_delta,
            "active_side": w.orderflow.active_side, "reversal_stage": w.orderflow.reversal_stage,
            "imbalance_count": len(w.orderflow.imbalances),
            "stacked_count": len(w.orderflow.stacked_imbalances),
        },
    }
if res.frame is not None:
    bars = res.frame.bars
    ind = res.frame.indicators
    of = res.frame.orderflow
    export["kline"] = [
        {
            "seq": b.seq,
            "time": time.strftime("%m-%d %H:%M", time.localtime(b.ts_open / 1000)),
            "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": int(b.volume),
            "rsi14": round(ind.rsi14[i], 2) if i < len(ind.rsi14) and not __import__("math").isnan(ind.rsi14[i]) else None,
            "vwap": round(ind.vwap[i], 2) if i < len(ind.vwap) and not __import__("math").isnan(ind.vwap[i]) else None,
            "ema20": round(ind.ema20[i], 2) if i < len(ind.ema20) and not __import__("math").isnan(ind.ema20[i]) else None,
            "delta": round(of.delta[i]) if of and i < len(of.delta) and not __import__("math").isnan(of.delta[i]) else None,
        }
        for i, b in enumerate(bars[:30])
    ]
out_path = PROJECT_ROOT / "test_reports" / "selftest_data_export.json"
out_path.write_text(json.dumps(export, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
record("数据采集-导出JSON", out_path.exists(), str(out_path))

# 截图面板各标签页（当前 win 显示的是 NQ 分析结果，切换查看）
shot("08_数据标签页", win._tab_data)
shot("09_快照标签页", win._tab_snapshot)
shot("10_诊断标签页", win._tab_diagnosis)
shot("11_决策标签页", win._tab_decision)
shot("12_问AI标签页", win._tab_ai)
shot("13_历史记录面板", win._history_list)

# ── 恢复配置 ────────────────────────────────────────────────────────────
restore_config()
print()
print("=" * 70)
print("测试完成")
print("=" * 70)

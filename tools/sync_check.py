# -*- coding: utf-8 -*-
"""
交易软件(MT5) ↔ 分析软件(WKF) 实时行情同步验证
============================================
对 XAU 5m → ES 15m → NQ 10m 依次检测：
  - 交易软件侧: MT5 symbol_info_tick 实时报价 + copy_rates_from_pos 最新K线
  - 分析软件侧: WKF 数据管道 fetch_mt5_bars（分析软件图表同源数据）
  - 60 秒窗口内每 10 秒采样一次（共 7 个采样点），记录：
    ① K线 open_time 序列 → 新柱生成时刻/间隔
    ② bid 价格轨迹 → 波动幅度
    ③ 两软件数据一致性: 分析软件最新收盘是否落在交易软件 bid~ask 点差区间
    ④ 断线/卡顿检测: 采样失败(返回None/异常) 或 连续2次采样完全静止
"""
import datetime
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import MetaTrader5 as mt5  # noqa: E402
from wkf.data.mt5_source import fetch_mt5_bars  # noqa: E402  (分析软件数据源)

# 内部符号映射（与 WKF 一致: GC1!→XAUUSD 等）
ANALYSIS_SYMBOL = {"XAUUSD": "GC1!", "US500c": "ES1!", "USTECHc": "NQ1!"}
TF_CONST = {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "10m": mt5.TIMEFRAME_M10}

TESTS = [
    {"label": "XAU 黄金", "mt5_sym": "XAUUSD", "tf": "5m", "wait_s": 60},
    {"label": "ES 标普500", "mt5_sym": "US500c", "tf": "15m", "wait_s": 60},
    {"label": "NQ 纳指100", "mt5_sym": "USTECHc", "tf": "10m", "wait_s": 60},
]
SAMPLE_INT = 10  # 每 10 秒采样

records: list[str] = []


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    records.append(line)


def fmt_ts(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


def sample_both(mt5_sym: str, tf: str, ana_sym: str) -> dict:
    """同时采样交易软件与分析软件数据。"""
    out = {"tick_ok": False, "rate_ok": False, "ana_ok": False, "error": ""}
    try:
        tick = mt5.symbol_info_tick(mt5_sym)
        if tick:
            out["bid"] = round(tick.bid, 2)
            out["ask"] = round(tick.ask, 2)
            out["spread"] = round(tick.ask - tick.bid, 2)
            out["tick_time"] = tick.time_msc
            out["tick_ok"] = True
    except Exception as e:
        out["error"] = f"tick异常: {e}"
    try:
        rates = mt5.copy_rates_from_pos(mt5_sym, TF_CONST[tf], 0, 1)
        if rates is not None and len(rates):
            r = rates[-1]
            out["bar_open"] = int(r["time"]) * 1000
            out["bar_close"] = round(float(r["close"]), 2)
            out["bar_vol"] = int(r["tick_volume"])
            out["rate_ok"] = True
    except Exception as e:
        out["error"] += f" | rates异常: {e}"
    try:
        bars = fetch_mt5_bars(ana_sym, tf, 3)  # 分析软件图表同源数据（最新3根）
        if bars:
            b0 = bars[0]  # 最新
            out["ana_close"] = round(b0.close, 2)
            out["ana_open"] = b0.ts_open
            out["ana_vol"] = int(b0.volume)
            out["ana_ok"] = True
    except Exception as e:
        out["error"] += f" | 分析软件异常: {e}"
    return out


def run() -> None:
    if not mt5.initialize():
        log(f"❌ MT5 初始化失败: {mt5.last_error()}")
        sys.exit(1)
    info = mt5.account_info()
    log(f"✅ 交易软件已登录: {info.name} | {info.server} | Login {info.login}")
    log(f"   实时报价正常: XAUUSD bid={mt5.symbol_info_tick('XAUUSD').bid:.2f} 点差={mt5.symbol_info_tick('XAUUSD').ask - mt5.symbol_info_tick('XAUUSD').bid:.2f}")
    log("=" * 70)

    report_lines = []  # 供最终汇总

    for t in TESTS:
        mt5_sym, tf, ana_sym = t["mt5_sym"], t["tf"], ANALYSIS_SYMBOL[t["mt5_sym"]]
        log(f"▶ 检测 {t['label']}（交易软件: {mt5_sym} / 分析软件: {ana_sym} @ {tf}）")
        samples: list[dict] = []
        n_points = t["wait_s"] // SAMPLE_INT + 1  # 0s,10s,...,60s = 7 点
        for i in range(n_points):
            s = sample_both(mt5_sym, tf, ana_sym)
            s["elapsed"] = i * SAMPLE_INT
            samples.append(s)
            if s["tick_ok"]:
                log(f"  T+{s['elapsed']:>2}s bid={s['bid']:.2f} K线起点={fmt_ts(s['bar_open']) if s['rate_ok'] else '?'} "
                    f"量={s['bar_vol'] if s['rate_ok'] else '?'} | 分析软件收盘={s.get('ana_close', '?')}")
            else:
                log(f"  T+{s['elapsed']:>2}s ⚠️ {s.get('error', '采样失败')}")
            if i < n_points - 1:
                time.sleep(SAMPLE_INT)

        # ── 判定 ─────────────────────────────────────────────────────
        ok_pts = [s for s in samples if s["tick_ok"]]
        if len(ok_pts) < 2:
            log(f"  判定: ❌ 数据不可用（有效采样仅 {len(ok_pts)} 点）")
            records.append(f"== {t['label']}: 数据不可用 ==")
            continue

        bids = [s["bid"] for s in ok_pts]
        bar_opens = [s["bar_open"] for s in ok_pts if s["rate_ok"]]
        price_range = max(bids) - min(bids)
        new_bars = len(set(bar_opens)) - 1  # 新柱数量
        # 卡顿/断线: 连续2次采样 tick 时间戳相同且 bid 完全不变
        stalls = 0
        for j in range(1, len(ok_pts)):
            same_tick = ok_pts[j].get("tick_time") == ok_pts[j - 1].get("tick_time")
            same_bid = ok_pts[j]["bid"] == ok_pts[j - 1]["bid"]
            if same_tick or same_bid:
                stalls += 1
        # 一致性: 分析软件收盘 vs 交易软件 bid/ask 区间
        consist_ok = 0
        consist_total = 0
        for s in ok_pts:
            if s.get("ana_close") is not None and s["tick_ok"]:
                consist_total += 1
                if s["ana_close"] >= s["bid"] - 0.5 and s["ana_close"] <= s["ask"] + 0.5:
                    consist_ok += 1
        consist_pct = round(consist_ok / consist_total * 100, 1) if consist_total else 0.0

        active = price_range > 0.01 or new_bars > 0
        conclusion = "✅ 实时行情" if active else "⚠️ 无明显波动"
        log(f"  判定: {conclusion}")
        log(f"  价格波动: {min(bids):.2f} ~ {max(bids):.2f}（幅度 {price_range:.2f}）")
        log(f"  新柱生成: {new_bars} 根（K线起点序列: {[fmt_ts(x) for x in dict.fromkeys(bar_opens)]}）")
        log(f"  卡顿/静止采样: {stalls}/{len(ok_pts)-1} 次 | 断线: {'无' if not any(s.get('error') for s in samples) else '有'}")
        log(f"  两软件一致性: {consist_ok}/{consist_total} 采样点一致（{consist_pct}%）")
        records.append(f"== {t['label']} {tf}: {conclusion} | 波动{price_range:.2f} | 新柱{new_bars} | 一致性{consist_pct}% | 卡顿{stalls} ==")
        log("-" * 70)

    mt5.shutdown()
    log("全部检测完成")

    out = PROJECT_ROOT / "test_reports" / "sync_check.log"
    out.write_text("\n".join(records), encoding="utf-8")
    print(f"\n记录已保存: {out}", flush=True)


if __name__ == "__main__":
    run()

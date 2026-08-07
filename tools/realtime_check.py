# -*- coding: utf-8 -*-
"""
实时行情检测：XAUUSD 5m → US500c(ES) 15m → USTECHc(NQ) 10m
每品种：t0 采样 → 精确等待 60 秒 → t1 采样，对比判断是否正在实时走出行情。
判断标准：
  1. 新K线生成：最新K线 open_time 是否在两次采样间推进
  2. 价格变动：最新价（close/bid/ask）是否持续变动
  3. 成交量：最新K线 tick_volume 是否增长 / 新K线出现
"""
import datetime
import sys
import time

import MetaTrader5 as mt5

# ── 检测配置 ────────────────────────────────────────────────────────────
TESTS = [
    {"name": "XAUUSD 黄金", "mt5_symbol": "XAUUSD", "timeframe": mt5.TIMEFRAME_M5, "label": "XAU 5m"},
    {"name": "ES 标普500", "mt5_symbol": "US500c", "timeframe": mt5.TIMEFRAME_M15, "label": "ES 15m"},
    {"name": "NQ 纳指100", "mt5_symbol": "USTECHc", "timeframe": mt5.TIMEFRAME_M10, "label": "NQ 10m"},
]
WAIT_SEC = 60  # 每个品种精确等待 60 秒

records = []  # 逐项记录


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    records.append(line)


def fmt_ts(ts_ms: int) -> str:
    return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%m-%d %H:%M:%S")


def snapshot(symbol: str, tf: int) -> dict:
    """采集一次快照：最新K线 + 实时报价。"""
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, 3)  # 最新3根
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    out = {
        "has_rates": rates is not None and len(rates) > 0,
        "open_time": int(rates[-1]["time"]) * 1000 if rates is not None and len(rates) else 0,
        "close": float(rates[-1]["close"]) if rates is not None and len(rates) else 0.0,
        "volume": int(rates[-1]["tick_volume"]) if rates is not None and len(rates) else 0,
        "bid": float(tick.bid) if tick else 0.0,
        "ask": float(tick.ask) if tick else 0.0,
        "spread": round(tick.ask - tick.bid, 2) if tick else 0.0,
    }
    return out


def run() -> None:
    if not mt5.initialize():
        log(f"❌ MT5 初始化失败: {mt5.last_error()}")
        sys.exit(1)
    info = mt5.account_info()
    if info is None:
        log(f"❌ 未登录交易账户: {mt5.last_error()}")
        sys.exit(1)
    log(f"✅ 交易软件已登录: {info.name} | {info.server} | Login {info.login}")
    log("=" * 66)

    for t in TESTS:
        sym = t["mt5_symbol"]
        log(f"▶ 检测 {t['label']}（{t['name']} @ {sym}）开始")
        log(f"  等待 {WAIT_SEC} 秒，采样中...")
        t0 = snapshot(sym, t["timeframe"])
        if not t0["has_rates"]:
            log(f"  ❌ 无K线数据: {sym} 可能不可用或未显示")
            records.append(f"== {t['label']}: 数据不可用 ==")
            continue
        log(f"  T0 采样: K线起点={fmt_ts(t0['open_time'])} 收盘={t0['close']:.2f} "
            f"量={t0['volume']} bid={t0['bid']:.2f} ask={t0['ask']:.2f} 点差={t0['spread']}")

        # 精确等待 60 秒
        deadline = time.time() + WAIT_SEC
        while time.time() < deadline:
            time.sleep(1)
        elapsed = round(time.time() - (deadline - WAIT_SEC), 1)

        t1 = snapshot(sym, t["timeframe"])
        log(f"  T1 采样: K线起点={fmt_ts(t1['open_time'])} 收盘={t1['close']:.2f} "
            f"量={t1['volume']} bid={t1['bid']:.2f} ask={t1['ask']:.2f} 点差={t1['spread']}")

        # ── 判定 ─────────────────────────────────────────────────────
        new_bar = t1["open_time"] != t0["open_time"]                      # 新K线生成
        price_moved = abs(t1["bid"] - t0["bid"]) > 0.0001 or abs(t1["close"] - t0["close"]) > 0.0001
        vol_grew = t1["volume"] > t0["volume"]                            # 成交量增长
        bar_vol = new_bar and t1["volume"] > 0                            # 新K线有量

        evidence = []
        if new_bar:
            evidence.append(f"新K线生成({fmt_ts(t1['open_time'])}，T0为{fmt_ts(t0['open_time'])})")
        if price_moved:
            evidence.append(f"价格变动(bid {t0['bid']:.2f}→{t1['bid']:.2f})")
        if vol_grew:
            evidence.append(f"成交量增长({t0['volume']}→{t1['volume']})")
        elif bar_vol:
            evidence.append(f"新K线带量({t1['volume']})")

        active = new_bar or price_moved or vol_grew or bar_vol
        conclusion = "✅ 正在实时走出行情" if active else "⚠️ 无明显实时行情（数据静止）"
        log(f"  判定: {conclusion}")
        log(f"  依据: {evidence if evidence else '两次采样数据无变化'}")
        log(f"  用时: {elapsed}s")
        records.append(f"== {t['label']}: {conclusion} ==")
        log("-" * 66)

    mt5.shutdown()
    log("全部检测完成")


if __name__ == "__main__":
    run()
    # 保存记录
    out = "E:/workbuddy/MT50802/wkf/test_reports/realtime_check.log"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(records))
    print(f"\n记录已保存: {out}", flush=True)

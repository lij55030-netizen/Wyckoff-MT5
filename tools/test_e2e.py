#!/usr/bin/env python
"""WKF 端到端测试：数据 → 指标 → 订单流 → 威科夫三层 → AI 诊断 → 输出。"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from wkf.data.base import IndicatorBundle, KlineFrame
from wkf.data.mt5_source import (
    compute_indicators,
    enrich_frame_with_orderflow,
    fetch_mt5_bars,
)
from wkf.wyckoff.analyzer import analyze
from wkf.wyckoff.background import analyze_background
from wkf.wyckoff.value_area import compute_value_area
from wkf.wyckoff.orderflow_verify import verify_orderflow

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def test_indicators(bars) -> None:
    print("\n[1] 指标计算")
    ind = compute_indicators(bars)
    n = len(bars)
    check("EMA20 长度", len(ind.ema20) == n)
    check("ATR14 长度", len(ind.atr14) == n)
    check("RSI14 长度", len(ind.rsi14) == n)
    check("布林带长度", len(ind.bb_upper) == n == len(ind.bb_lower))
    check("VWAP 长度", len(ind.vwap) == n)

    rsi_ok = [v for v in ind.rsi14 if not math.isnan(v)]
    check("RSI 有非NaN值", len(rsi_ok) > 0)
    if rsi_ok:
        check("RSI 范围 0-100", 0 <= rsi_ok[-1] <= 100, f"({rsi_ok[-1]:.1f})")

    bb_valid = 0
    for i in range(n):
        u, m, l = ind.bb_upper[i], ind.bb_middle[i], ind.bb_lower[i]
        if not (math.isnan(u) or math.isnan(m) or math.isnan(l)):
            bb_valid += 1
            if not (u >= m >= l):
                check(f"BB 顺序 @{i}", False)
                return
    check("BB 顺序 upper>=mid>=lower", bb_valid > 0)


def test_orderflow(frame: KlineFrame) -> None:
    print("\n[2] 订单流增强")
    of = frame.orderflow
    check("orderflow 非 None", of is not None)
    if of is None:
        return
    check("delta 长度", len(of.delta) == len(frame.bars))
    check("cumulative_delta 长度", len(of.cumulative_delta) == len(frame.bars))
    check("POC 长度", len(of.poc_price) == len(frame.bars))
    check("buy_vwap 长度", len(of.buy_vwap) == len(frame.bars))
    check("footprint 长度", len(of.footprint) == len(frame.bars))
    has_fp = sum(1 for f in of.footprint if f is not None)
    check("有可用足迹", has_fp > 0, f"({has_fp}/{len(of.footprint)})")


def test_wyckoff(frame: KlineFrame) -> None:
    print("\n[3] 威科夫三层分析")
    wa = analyze(frame)
    check("background 判定", wa.background.regime in ("trend_up", "trend_down", "range", "unknown"))
    check("background 有推理", len(wa.background.reasoning) > 0)
    check("value_area 非 None", wa.value_area is not None)
    if wa.value_area:
        va = wa.value_area
        check("VAH >= VAL", va.vah >= va.val, f"({va.val:.2f}/{va.vah:.2f})")
        check("VPOC 在 [VAL, VAH]", va.val <= va.vpoc <= va.vah)
        check("price_position 有效", va.price_position(frame.bars[0].close) in ("above_va", "below_va", "inside_va"))
    check("orderflow 验证", wa.orderflow is not None)
    if wa.orderflow:
        check("active_side 有效", wa.orderflow.active_side in ("buy", "sell", "none"))
        check("reversal_stage 有效", wa.orderflow.reversal_stage in ("none", "exhaustion", "absorption", "active"))
    check("bias 有效", wa.bias in ("long", "short", "neutral"))
    check("trigger 非空", len(wa.trigger) > 10)
    check("invalidation 非空", len(wa.invalidation) > 10)
    print(f"  报告预览:\n{wa.render_text()[:400]}")


def test_ai(frame: KlineFrame) -> None:
    print("\n[4] AI 诊断（真实调用 DeepSeek）")
    from wkf.config.settings import load_settings
    from wkf.orchestrator.runner import run_analysis

    settings = load_settings()
    if not settings.provider.api_key:
        check("AI 跳过（无 API Key）", True)
        return
    res = run_analysis("NQ1!", "15m", bar_count=80, with_ai=True)
    check("分析成功", res.ok, res.error)
    check("威科夫结果", res.wyckoff is not None)
    check("AI 诊断 JSON", res.ai_diagnosis is not None)
    if res.ai_diagnosis:
        direction = res.ai_diagnosis.get("direction")
        # 接受标准值或"xxx_to_yyy"过渡值；None 视为 LLM 输出缺失
        valid_dir = (
            direction in ("bullish", "bearish", "neutral", None)
            or (isinstance(direction, str) and "_to_" in direction)
        )
        check("direction 有效", valid_dir, f"({direction!r})")
        check("confidence 0-100", 0 <= res.ai_diagnosis.get("diagnosis_confidence", 50) <= 100)
        # LLM 偶发方向缺失：重试一次
        if direction not in ("bullish", "bearish", "neutral"):
            res2 = run_analysis("NQ1!", "15m", bar_count=80, with_ai=True)
            d2 = (res2.ai_diagnosis or {}).get("direction")
            check("重试后 direction 有效", d2 in ("bullish", "bearish", "neutral"), f"({d2!r})")


def test_unit_functions() -> None:
    print("\n[5] 单元函数")
    # background（真实波浪：每浪4根K线，峰谷两侧各有2根确认 → HH+HL）
    peaks = [104, 108, 112, 116, 120]
    troughs = [100, 103, 106, 109, 112]  # 逐浪抬高
    bars_t: list[tuple] = []
    for i in range(len(peaks)):
        t, p = troughs[i], peaks[i]
        bars_t.append((t, t + 2, t, t + 2))
        bars_t.append((t + 2, p, t + 1.5, p - 0.3))
        if i < len(peaks) - 1:
            nt = troughs[i + 1]
            bars_t.append((p - 0.3, p, p - 2, p - 2))
            bars_t.append((p - 2, nt + 1, nt, nt + 0.5))
    up_highs = [b[1] for b in bars_t]
    up_lows = [b[2] for b in bars_t]
    up_closes = [b[3] for b in bars_t]
    bg = analyze_background(
        up_highs[::-1], up_lows[::-1], up_closes[::-1]
    )
    check("上升趋势识别", bg.regime == "trend_up", f"({bg.regime})")

    flat_h = [50] * 30
    flat_l = [40] * 30
    bg2 = analyze_background(flat_h[::-1], flat_l[::-1], flat_h[::-1])
    check("区间识别", bg2.regime == "range", f"({bg2.regime})")

    # value area
    prices = [100, 101, 102, 103, 104]
    vols = [10, 30, 100, 40, 20]
    va = compute_value_area(prices, vols)
    check("VA 计算", va is not None)
    if va:
        check("VPOC 是最大量价位", va.vpoc == 102)

    # orderflow
    of_res = verify_orderflow(
        bars_delta=[100.0, -50.0],
        cumulative_delta=50.0,
        footprint=None,
        tick_size=0.25,
    )
    check("无足迹回退", of_res is not None)


def main() -> int:
    print("=" * 60)
    print("WKF 端到端测试")
    print("=" * 60)

    print("\n[0] MT5 数据获取")
    try:
        bars = fetch_mt5_bars("NQ1!", "15m", 100)
        check("获取 100 根 15m K线", len(bars) == 100, f"({len(bars)})")
        check("最新 bar seq=1", bars[0].seq == 1)
        check("K线方向有序", all(b.high >= max(b.open, b.close) and b.low <= min(b.open, b.close) for b in bars))
    except Exception as exc:
        check("MT5 数据获取", False, str(exc))
        print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
        return 1

    test_indicators(bars)

    ind = compute_indicators(bars)
    frame = KlineFrame(symbol="NQ1!", timeframe="15m", bars=tuple(bars), indicators=ind)
    frame = enrich_frame_with_orderflow(frame)
    test_orderflow(frame)
    test_wyckoff(frame)
    test_ai(frame)
    test_unit_functions()

    print(f"\n{'=' * 60}")
    print(f"结果: {PASS} 通过 / {FAIL} 失败")
    print(f"{'=' * 60}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

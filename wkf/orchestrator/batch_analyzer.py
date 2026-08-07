"""WKF 批量分析工具：全周期复盘、三品种汇总、精简查询。"""
from __future__ import annotations

import datetime
from pathlib import Path

from wkf.orchestrator.runner import AnalysisResult, run_analysis

SYMBOLS = ["NQ1!", "ES1!", "GC1!"]
TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


def run_full_review(symbol: str, *, with_ai: bool = True) -> list[AnalysisResult]:
    """单品种全周期复盘：5m/10m/15m/30m/1h。"""
    results = []
    for tf in TIMEFRAMES:
        try:
            res = run_analysis(symbol, tf, bar_count=80, with_ai=with_ai)
            results.append(res)
        except Exception as exc:
            results.append(AnalysisResult(symbol=symbol, timeframe=tf, error=str(exc)))
    return results


def run_all_symbols_review(*, with_ai: bool = True) -> dict[str, list[AnalysisResult]]:
    """三品种全周期汇总。"""
    return {sym: run_full_review(sym, with_ai=with_ai) for sym in SYMBOLS}


def render_full_review(symbol: str, results: list[AnalysisResult]) -> str:
    """渲染单品种全周期复盘文本。"""
    lines = [
        f"📊 WKF 全周期复盘: {symbol}",
        "=" * 40,
    ]
    for res in results:
        if res.error or res.wyckoff is None:
            lines.append(f"\n❌ {res.timeframe}: {res.error}")
            continue
        wa = res.wyckoff
        va = wa.value_area
        of = wa.orderflow
        bias_zh = {"long": "偏多", "short": "偏空", "neutral": "中性观望"}.get(wa.bias, wa.bias)
        lines.append(
            f"\n【{res.timeframe}】{wa.price:.2f} | 背景:{_regime_zh(wa.background.regime)}"
            f" | 倾向:{bias_zh}"
        )
        if va:
            lines.append(f"  VA [{va.val:.2f}, {va.vah:.2f}] VPOC {va.vpoc:.2f}")
        if of:
            lines.append(f"  Delta {of.delta:+.0f} 累积{of.cumulative_delta:+.0f} 活跃:{of.active_side}")
    return "\n".join(lines)


def render_all_summary(data: dict[str, list[AnalysisResult]]) -> str:
    """渲染三品种全周期汇总。"""
    lines = ["📊 WKF 三品种全周期汇总", "=" * 46]
    for sym in SYMBOLS:
        lines.append(f"\n■ {sym}")
        for res in data.get(sym, []):
            if res.error or res.wyckoff is None:
                lines.append(f"  {res.timeframe}: 失败 {res.error}")
                continue
            wa = res.wyckoff
            bias_zh = {"long": "偏多", "short": "偏空", "neutral": "中性"}.get(wa.bias, wa.bias)
            lines.append(
                f"  {res.timeframe}: {wa.price:.2f} {_regime_zh(wa.background.regime)} → {bias_zh}"
            )
    return "\n".join(lines)


def render_key_levels(res: AnalysisResult) -> str:
    """定向查询：关键价位。"""
    if res.error or res.wyckoff is None:
        return f"❌ {res.symbol} {res.timeframe}: {res.error}"
    wa = res.wyckoff
    va = wa.value_area
    lines = [
        f"🔑 {wa.symbol} {wa.timeframe} 关键价位",
        f"现价: {wa.price:.2f}",
    ]
    if va:
        lines.append(f"VA上沿: {va.vah:.2f}（做空参考）")
        lines.append(f"VA下沿: {va.val:.2f}（做多参考）")
        lines.append(f"VPOC: {va.vpoc:.2f}")
        if va.vwap:
            lines.append(f"VWAP: {va.vwap:.2f}")
        if va.hvn:
            lines.append(f"高量节点(HVN): {', '.join(f'{p:.2f}' for p in va.hvn[:3])}")
        if va.lvn:
            lines.append(f"低量节点(LVN): {', '.join(f'{p:.2f}' for p in va.lvn[:3])}")
    lines.append(f"入场: {wa.trigger}")
    lines.append(f"失效: {wa.invalidation}")
    return "\n".join(lines)


def render_orderflow_pivot(res: AnalysisResult) -> str:
    """定向查询：订单流拐点（失衡/吸收位置）。"""
    if res.error or res.wyckoff is None:
        return f"❌ {res.symbol} {res.timeframe}: {res.error}"
    wa = res.wyckoff
    of = wa.orderflow
    lines = [
        f"⚡ {wa.symbol} {wa.timeframe} 订单流拐点",
        f"现价: {wa.price:.2f}",
    ]
    if of is None:
        lines.append("订单流数据不可用")
        return "\n".join(lines)
    lines.append(f"Delta: {of.delta:+.0f} 累积: {of.cumulative_delta:+.0f}")
    lines.append(f"活跃方: {of.active_side} 反转阶段: {of.reversal_stage}")
    if of.imbalances:
        strongest = max(of.imbalances, key=lambda x: x["level"])
        lines.append(
            f"最强失衡: {strongest['side']} {strongest['level']}级 "
            f"({strongest['ratio']}x @ {strongest['price']:.2f})"
        )
        lines.append("失衡价位: " + ", ".join(
            f"{i['price']:.2f}({i['side']}{i['level']})" for i in of.imbalances[:6]
        ))
    if of.stacked_imbalances:
        lines.append(f"堆叠失衡: {len(of.stacked_imbalances)} 组（强拐点信号）")
    return "\n".join(lines)


def render_one_line_bias(res: AnalysisResult) -> str:
    """定向查询：多空定性一句话结论。"""
    if res.error or res.wyckoff is None:
        return f"❌ {res.symbol} {res.timeframe}: {res.error}"
    wa = res.wyckoff
    bias_zh = {"long": "偏多", "short": "偏空", "neutral": "中性观望"}.get(wa.bias, wa.bias)
    return (
        f"💬 {wa.symbol} {wa.timeframe} 一句话结论：{bias_zh}。"
        f"{_regime_zh(wa.background.regime)}，现价 {wa.price:.2f}，"
        f"{wa.trigger[:60]}"
    )


def _regime_zh(r: str) -> str:
    return {
        "trend_up": "上升趋势", "trend_down": "下降趋势",
        "range": "区间震荡", "unknown": "背景不明",
    }.get(r, r)

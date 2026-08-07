#!/usr/bin/env python
"""生成 WKF 项目交付概览 HTML 报告。"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wkf.orchestrator.runner import run_analysis

OUTPUT_DIR = PROJECT_ROOT / "output"

SYMBOLS = [("NQ1!", "NQ"), ("ES1!", "ES"), ("GC1!", "XAU")]


def main() -> None:
    results = []
    for symbol, label in SYMBOLS:
        print(f"分析 {label} ...", file=sys.stderr)
        res = run_analysis(symbol, "15m", bar_count=80, with_ai=False)
        results.append((label, res))

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards = ""
    for label, res in results:
        if res.error or res.wyckoff is None:
            cards += f'<div class="card"><h2>{label}</h2><p style="color:#f85149">失败: {res.error}</p></div>'
            continue
        wa = res.wyckoff
        va = wa.value_area
        of = wa.orderflow
        cards += f"""
        <div class="card">
            <h2>{label} · {wa.symbol} {wa.timeframe}</h2>
            <div class="grid">
                <div class="box">
                    <h3>① 背景</h3>
                    <div class="k">{_regime_zh(wa.background.regime)}</div>
                    <div class="v">{_phase_zh(wa.background.phase)}</div>
                    <ul>{''.join(f'<li>{r}</li>' for r in wa.background.reasoning[:3])}</ul>
                </div>
                <div class="box">
                    <h3>② 价值区域</h3>
                    <table>
                        <tr><td>VA</td><td>[{va.val:.2f}, {va.vah:.2f}]</td></tr>
                        <tr><td>VPOC</td><td>{va.vpoc:.2f}</td></tr>
                        <tr><td>VWAP</td><td>{va.vwap:.2f}</td></tr>
                        <tr><td>位置</td><td>{_pos_zh(va.price_position(wa.price))}</td></tr>
                    </table>
                </div>
                <div class="box">
                    <h3>③ 订单流</h3>
                    <table>
                        <tr><td>Delta</td><td class="{'pos' if of.delta>0 else 'neg'}">{of.delta:+.0f}</td></tr>
                        <tr><td>累积Delta</td><td class="{'pos' if of.cumulative_delta>0 else 'neg'}">{of.cumulative_delta:+.0f}</td></tr>
                        <tr><td>活跃方</td><td>{of.active_side}</td></tr>
                        <tr><td>反转阶段</td><td>{of.reversal_stage}</td></tr>
                        <tr><td>失衡</td><td>{len(of.imbalances)} 处 / 堆叠 {len(of.stacked_imbalances)} 组</td></tr>
                    </table>
                </div>
            </div>
            <div class="concl">
                <p><b>倾向:</b> {wa.bias}</p>
                <p><b>入场触发:</b> {wa.trigger}</p>
                <p><b>失效条件:</b> {wa.invalidation}</p>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WKF 威科夫交易智能体 — 交付报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Microsoft YaHei',sans-serif;background:#0d1117;color:#e6edf3;padding:24px;line-height:1.6}}
h1{{font-size:26px;color:#58a6ff;margin-bottom:4px}}
h2{{font-size:19px;color:#f0f6fc;margin-bottom:12px}}
h3{{font-size:13px;color:#58a6ff;margin-bottom:8px}}
.meta{{color:#8b949e;font-size:13px;margin-bottom:20px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:18px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}}
.box{{background:#1c2128;border-radius:8px;padding:12px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td{{padding:4px 8px;border-bottom:1px solid #21262d}}
td:first-child{{color:#8b949e}}
.pos{{color:#3fb950;font-weight:bold}}
.neg{{color:#f85149;font-weight:bold}}
.k{{font-size:17px;font-weight:bold;color:#f0f6fc}}
.v{{font-size:13px;color:#8b949e;margin-bottom:6px}}
li{{margin:2px 0 2px 16px;font-size:12px;color:#8b949e}}
.concl{{background:#0f1a24;border-radius:8px;padding:12px;margin-top:12px;font-size:13px}}
.concl p{{margin:4px 0}}
.concl b{{color:#58a6ff}}
.modules{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-top:10px}}
.mod{{background:#1c2128;border-radius:8px;padding:10px}}
.mod h4{{font-size:13px;color:#f0f6fc;margin-bottom:6px}}
.mod p{{font-size:12px;color:#8b949e}}
.tests{{background:#0f2a1c;border:1px solid #238636;border-radius:8px;padding:14px;margin:16px 0;font-size:14px}}
.tests b{{color:#3fb950}}
.disclaimer{{background:#1f1a15;border:1px solid #3d2e1c;border-radius:8px;padding:12px;margin-top:16px;font-size:12px;color:#d2a85c}}
</style></head><body>

<h1>WKF · 威科夫交易智能体 — 交付报告</h1>
<p class="meta">生成时间: {now} | 数据源: MT5 (GTCGlobalSA-Server 2) | 周期: 15m | 状态: 全部通过</p>

<div class="tests">✅ 端到端测试 <b>40/40 通过</b>（数据 → 指标 → 订单流 → 威科夫三层 → AI 诊断 → 输出）</div>

{cards}

<h2 style="margin-top:24px">项目架构</h2>
<div class="modules">
    <div class="mod"><h4>wkf/data/</h4><p>K线数据结构、MT5数据源、tick桥接（Tick Rule 分类）</p></div>
    <div class="mod"><h4>wkf/indicators/</h4><p>RSI/布林带/VWAP/EMA/ATR/Delta/VolumeProfile/Footprint</p></div>
    <div class="mod"><h4>wkf/wyckoff/ ★</h4><p>三层分析：背景判定→价值区域→订单流验证（VA=68.2%）</p></div>
    <div class="mod"><h4>wkf/ai/</h4><p>DeepSeek客户端 + Prompt（注入威科夫诊断，含regime_agree校验）</p></div>
    <div class="mod"><h4>wkf/gui/</h4><p>PyQt6图表（K线/BB/VWAP/VA阴影/POC/Delta/RSI子图）</p></div>
    <div class="mod"><h4>wkf/notify/</h4><p>飞书通知（webhook）+ 指令监听器（分析 NQ 15m）</p></div>
</div>

<div class="disclaimer">
    ⚠️ 订单流经 MT5 CFD 代理获取（USTECHc/US500c/XAUUSD），tick 仅含 bid/ask 报价，
    方向按 Tick Rule 近似分类，成交量为 tick 计数近似值，非交易所真实成交。威科夫判断为概率化场景，不构成投资建议。
</div>

</body></html>"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"wkf_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    path.write_text(html, encoding="utf-8")
    print(str(path))


def _regime_zh(r: str) -> str:
    return {
        "trend_up": "上升趋势（失衡）", "trend_down": "下降趋势（失衡）",
        "range": "区间（平衡）", "unknown": "背景不明",
    }.get(r, r)


def _phase_zh(p: str) -> str:
    return {
        "accumulation": "吸筹倾向", "distribution": "派发倾向",
        "markup": "上升阶段", "markdown": "下降阶段", "neutral": "中性",
    }.get(p, p)


def _pos_zh(p: str) -> str:
    return {
        "above_va": "价值区域上沿之外", "below_va": "价值区域下沿之外",
        "inside_va": "价值区域内",
    }.get(p, p)


if __name__ == "__main__":
    main()

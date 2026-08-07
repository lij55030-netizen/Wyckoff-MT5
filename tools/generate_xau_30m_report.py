#!/usr/bin/env python
"""生成 XAU 单品种 HTML 报告（含威科夫三层 + AI 诊断 + K线表）。"""
from __future__ import annotations

import datetime
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wkf.orchestrator.runner import run_analysis

OUTPUT_DIR = PROJECT_ROOT / "output"


def n2s(v, fmt=".2f"):
    return f"{v:{fmt}}" if not math.isnan(v) else "-"


def main() -> int:
    res = run_analysis("GC1!", "30m", bar_count=80, with_ai=True)
    if res.error or res.wyckoff is None:
        print(f"❌ 分析失败: {res.error}")
        return 1

    wa = res.wyckoff
    va = wa.value_area
    frame = res.frame
    of_res = wa.orderflow  # OrderFlowVerifyResult（标量字段）
    of_bundle = frame.orderflow if frame else None  # OrderFlowBundle（序列字段）
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # AI 摘要
    ai = res.ai_diagnosis or {}
    ai_keys = ai.get("key_signals") or []
    ai_plan = ai.get("trade_plan") or {}
    ai_wk = ai.get("wyckoff_check") or {}
    ai_signals_html = "".join(f"<li>{s}</li>" for s in ai_keys[:6])

    # K线表（最近15根）
    krows = ""
    if frame:
        for i in range(min(15, len(frame.bars))):
            b = frame.bars[i]
            ts = datetime.datetime.fromtimestamp(b.ts_open / 1000).strftime("%m-%d %H:%M")
            dc = "up" if b.close > b.open else "down"
            rsi = frame.indicators.rsi14[i] if i < len(frame.indicators.rsi14) else float("nan")
            d_s = ""
            if of_bundle and i < len(of_bundle.delta):
                d_s = f'<span class="{"pos" if of_bundle.delta[i]>=0 else "neg"}">{of_bundle.delta[i]:+.0f}</span>'
            krows += f"""<tr><td>{b.seq}</td><td>{ts}</td>
                <td class="{dc}">{b.open:.2f}</td><td>{b.high:.2f}</td><td>{b.low:.2f}</td>
                <td class="{dc}">{b.close:.2f}</td><td>{b.volume:.0f}</td>
                <td>{n2s(rsi, '.1f')}</td><td>{d_s}</td></tr>"""

    of_rows = ""
    if of_bundle:
        for i in range(min(8, len(frame.bars))):
            b = frame.bars[i]
            d = of_bundle.delta[i]
            cd = of_bundle.cumulative_delta[i]
            poc = of_bundle.poc_price[i]
            vah = of_bundle.vah[i]
            val = of_bundle.val[i]
            if math.isnan(poc):
                continue
            of_rows += f"""<tr><td>{b.seq}</td>
                <td class="{'pos' if d>=0 else 'neg'}">{d:+.0f}</td>
                <td class="{'pos' if cd>=0 else 'neg'}">{cd:+.0f}</td>
                <td>{poc:.2f}</td><td>{vah:.2f}</td><td>{val:.2f}</td></tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>XAU 黄金 15分钟威科夫分析报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Microsoft YaHei',sans-serif;background:#0d1117;color:#e6edf3;padding:24px;line-height:1.6}}
h1{{font-size:26px;color:#f0b90b;margin-bottom:4px}}
h2{{font-size:19px;color:#58a6ff;margin:22px 0 10px;padding-bottom:6px;border-bottom:1px solid #30363d}}
h3{{font-size:13px;color:#8b949e;margin:12px 0 6px}}
.meta{{color:#8b949e;font-size:13px;margin-bottom:18px}}
.grid3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;margin:12px 0}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td{{padding:4px 8px;border-bottom:1px solid #21262d}}
tr:last-child td{{border-bottom:none}}
td:first-child{{color:#8b949e;width:36%}}
.pos{{color:#3fb950;font-weight:bold}}
.neg{{color:#f85149;font-weight:bold}}
.big{{font-size:20px;font-weight:bold;color:#f0b90b}}
.regime{{display:inline-block;padding:4px 12px;border-radius:14px;font-size:13px;font-weight:600;margin:4px 4px 4px 0}}
.r-trend{{background:#0f3022;color:#3fb950;border:1px solid #238636}}
.r-range{{background:#1c2128;color:#d2a85c;border:1px solid #9e6a03}}
.r-unknown{{background:#3d1117;color:#f85149;border:1px solid #da3633}}
.concl{{background:#0f1a24;border:1px solid #1f3a5f;border-radius:10px;padding:14px;margin:12px 0}}
.concl p{{margin:6px 0;font-size:14px}}
.concl b{{color:#58a6ff}}
.ai-box{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px;margin:12px 0}}
.ai-box li{{margin:4px 0 4px 18px;font-size:13px}}
.wk-note{{background:#1f1a15;border-left:4px solid #d2a85c;padding:10px 14px;margin:10px 0;font-size:13px;color:#d2a85c}}
.tw{{overflow-x:auto}}
.kt{{font-size:12px}}
.kt th{{background:#161b22;color:#8b949e;padding:5px 6px;text-align:right}}
.kt th:first-child,.kt th:nth-child(2){{text-align:left}}
.kt td{{padding:3px 6px;text-align:right;font-variant-numeric:tabular-nums}}
.kt td:first-child,.kt td:nth-child(2){{text-align:left}}
.kt .up{{color:#3fb950}}.kt .down{{color:#f85149}}
.disclaimer{{background:#1f1a15;border:1px solid #3d2e1c;border-radius:8px;padding:12px;margin-top:16px;font-size:12px;color:#d2a85c}}
</style></head><body>

<h1>XAU · 黄金 30分钟威科夫分析</h1>
<p class="meta">生成时间: {now} | 数据源: MT5 (XAUUSD CFD) | 周期: 30m | K线数: 80 | AI: {res.usage.get('total_tokens', 'N/A')} tokens</p>

<div class="grid3">
    <div class="box">
        <h3>现价</h3>
        <div class="big">{wa.price:.2f}</div>
    </div>
    <div class="box">
        <h3>背景判定</h3>
        <div>
            <span class="regime {'r-trend' if wa.background.is_trending else 'r-range' if wa.background.is_range else 'r-unknown'}">
                {wa.background.regime}
            </span>
            <span class="regime r-range">{wa.background.phase}</span>
        </div>
        <div style="font-size:12px;color:#8b949e;margin-top:6px">
            HH+HL {wa.background.hh_hl_count} 组 | LH+LL {wa.background.lh_ll_count} 组
        </div>
    </div>
    <div class="box">
        <h3>倾向</h3>
        <div style="font-size:17px;font-weight:bold;color:{'#3fb950' if wa.bias=='long' else '#f85149' if wa.bias=='short' else '#d2a85c'}">
            {wa.bias}
        </div>
    </div>
</div>

<h2>① 威科夫三层分析</h2>
<div class="grid3">
    <div class="box">
        <h3>背景</h3>
        <ul style="font-size:12px;color:#8b949e;padding-left:16px">
            {''.join(f'<li>{r}</li>' for r in wa.background.reasoning)}
        </ul>
    </div>
    <div class="box">
        <h3>价值区域</h3>
        <table>
            <tr><td>VA</td><td>[{va.val:.2f}, {va.vah:.2f}]</td></tr>
            <tr><td>VPOC</td><td>{va.vpoc:.2f}</td></tr>
            <tr><td>VWAP</td><td>{va.vwap:.2f}</td></tr>
            <tr><td>位置</td><td>{'下沿之外' if va.price_position(wa.price)=='below_va' else '上沿之外' if va.price_position(wa.price)=='above_va' else '区域内'}</td></tr>
            <tr><td>HVN</td><td>{', '.join(f'{p:.2f}' for p in va.hvn[:4])}</td></tr>
            <tr><td>LVN</td><td>{', '.join(f'{p:.2f}' for p in va.lvn[:4])}</td></tr>
        </table>
    </div>
    <div class="box">
        <h3>订单流</h3>
        <table>
            <tr><td>Delta</td><td class="{'pos' if of_res.delta>=0 else 'neg'}">{of_res.delta:+.0f}</td></tr>
            <tr><td>累积Delta</td><td class="{'pos' if of_res.cumulative_delta>=0 else 'neg'}">{of_res.cumulative_delta:+.0f}</td></tr>
            <tr><td>活跃方</td><td>{of_res.active_side}</td></tr>
            <tr><td>反转阶段</td><td>{of_res.reversal_stage}</td></tr>
            <tr><td>失衡</td><td>{len(of_res.imbalances)} 处</td></tr>
            <tr><td>堆叠失衡</td><td>{len(of_res.stacked_imbalances)} 组</td></tr>
        </table>
    </div>
</div>

<div class="concl">
    <p><b>🎯 入场触发：</b>{wa.trigger}</p>
    <p><b>🚫 失效条件：</b>{wa.invalidation}</p>
</div>

<h2>② AI 增强诊断（DeepSeek）</h2>
<div class="wk-note">💡 程序与 AI 一致性：<b>{'一致 ✅' if ai_wk.get('regime_agree') else '存在分歧 ⚠️'}</b> — {ai_wk.get('note','')}</div>
<div class="ai-box">
    <h3>关键信号</h3>
    <ul>{ai_signals_html}</ul>
    <h3>交易计划</h3>
    <table>
        <tr><td>倾向</td><td>{ai_plan.get('bias','')}</td></tr>
        <tr><td>触发</td><td>{ai_plan.get('trigger','')}</td></tr>
        <tr><td>失效</td><td>{ai_plan.get('invalidation','')}</td></tr>
        <tr><td>止损参考</td><td>{ai_plan.get('stop_reference','')}</td></tr>
        <tr><td>目标参考</td><td>{ai_plan.get('target_reference','')}</td></tr>
    </table>
    <h3>风险提示</h3>
    <p style="font-size:13px;color:#d2a85c">{ai.get('risk_warning','')}</p>
</div>

<h2>③ 最近15根K线</h2>
<div class="tw"><table class="kt">
<thead><tr><th>#</th><th>时间</th><th>开</th><th>高</th><th>低</th><th>收</th><th>量</th><th>RSI</th><th>Δ</th></tr></thead>
<tbody>{krows}</tbody>
</table></div>

<h2>④ 订单流明细（最近8根）</h2>
<div class="tw"><table class="kt">
<thead><tr><th>#</th><th>Δ</th><th>累积Δ</th><th>POC</th><th>VAH</th><th>VAL</th></tr></thead>
<tbody>{of_rows}</tbody>
</table></div>

<div class="disclaimer">⚠️ 订单流经 MT5 CFD (XAUUSD) 获取，tick 仅含 bid/ask，方向按 Tick Rule 近似分类，成交量为 tick 计数近似值。威科夫判断为概率化场景，不构成投资建议。</div>
</body></html>"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"xau_30m_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    path.write_text(html, encoding="utf-8")
    print(str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

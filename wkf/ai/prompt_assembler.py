"""Prompt 组装：K线表 + 指标表 + 订单流 + 威科夫诊断 → LLM 两阶段分析。

与 PA-Agent 不同，WKF 将程序化威科夫诊断作为「第一意见」注入 Prompt，
要求 LLM 在此基础上做增强诊断与交易决策。
"""
from __future__ import annotations

import datetime
import json
import math
from typing import Any

from wkf.data.base import KlineFrame
from wkf.wyckoff.analyzer import WyckoffAnalysis

_SYSTEM_PROMPT = """你是 WKF 威科夫交易智能体的 AI 分析引擎，精通《威科夫2.0：市场结构、成交量分布与订单流》。

## 分析纪律
1. 必须先定性市场背景（平衡/失衡、吸筹/派发倾向），再给具体价位与操作逻辑。
2. 所有结论使用条件化措辞（「如果……则……」「潜在」「可能」），只对下一步提概率场景。
3. 关键价位必须同时说明「价格在此做什么行为才算有效」。
4. 不预测终点，不保证涨跌；只做概率化场景分析。
5. 程序已给出威科夫三层诊断（背景→价值区域→订单流），你应在此基础上深化而非重复。

## 输出格式（严格 JSON）
{
  "cycle_position": "trending_tr|range|broad_channel|normal_channel|...",
  "direction": "bullish|bearish|neutral",
  "diagnosis_confidence": 0-100,
  "key_signals": ["...", "..."],
  "wyckoff_check": {
    "regime_agree": true/false,
    "note": "与程序威科夫诊断的一致/分歧说明"
  },
  "support_levels": ["...", "..."],
  "resistance_levels": ["...", "..."],
  "entry_setup": "等待|是（条件）|否",
  "risk_warning": "...",
  "trade_plan": {
    "bias": "long|short|neutral",
    "trigger": "入场触发条件（可验证）",
    "invalidation": "失效条件",
    "stop_reference": "止损参考位与理由",
    "target_reference": "止盈参考位（磁吸区）"
  },
  "bar_by_bar_summary": [
    {"bar": "K1", "role": "structure|signal|test|noise", "bar_type": "...",
     "context_effect": "strengthens_bull|weakened_bull|...", "reason": "..."}
  ]
}
"""


def _fmt_price(v: float) -> str:
    return f"{v:.4f}" if not math.isnan(v) else "N/A"


def build_kline_table(frame: KlineFrame, limit: int = 40) -> str:
    bars = frame.bars[:limit]
    ind = frame.indicators
    lines = [
        "序号 | 时间 | 开盘 | 最高 | 最低 | 收盘 | 阳阴 | 成交量 | RSI14 | 布林上 | 布林下 | VWAP | EMA20 | ATR14",
        "-----+------+------+------+------+------+------+--------+-------+--------+--------+------+-------+------",
    ]
    for i, b in enumerate(bars):
        yang = "阳" if b.close > b.open else "阴"
        dt = datetime.datetime.fromtimestamp(b.ts_open / 1000).strftime("%m-%d %H:%M")
        rsi = ind.rsi14[i] if i < len(ind.rsi14) else float("nan")
        bbu = ind.bb_upper[i] if i < len(ind.bb_upper) else float("nan")
        bbl = ind.bb_lower[i] if i < len(ind.bb_lower) else float("nan")
        vwap = ind.vwap[i] if i < len(ind.vwap) else float("nan")
        ema = ind.ema20[i] if i < len(ind.ema20) else float("nan")
        atr = ind.atr14[i] if i < len(ind.atr14) else float("nan")
        lines.append(
            f"{b.seq:<4} | {dt} | {b.open:.2f} | {b.high:.2f} | {b.low:.2f} | {b.close:.2f} | "
            f"{yang} | {b.volume:.0f} | {_fmt_price(rsi)} | {_fmt_price(bbu)} | {_fmt_price(bbl)} | "
            f"{_fmt_price(vwap)} | {_fmt_price(ema)} | {_fmt_price(atr)}"
        )
    return "\n".join(lines)


def build_orderflow_block(frame: KlineFrame, limit: int = 5) -> str:
    of = frame.orderflow
    if of is None:
        return ""
    bars = frame.bars[:limit]
    lines = [
        "序号 | Delta | 累积Delta | POC | VAH | VAL | 买方VWAP | 卖方VWAP | VWAP Delta",
        "-----+-------+----------+-----+-----+-----+----------+----------+-----------",
    ]
    for i, b in enumerate(bars):
        d = of.delta[i] if i < len(of.delta) else float("nan")
        cd = of.cumulative_delta[i] if i < len(of.cumulative_delta) else float("nan")
        poc = of.poc_price[i] if i < len(of.poc_price) else float("nan")
        vah = of.vah[i] if i < len(of.vah) else float("nan")
        val = of.val[i] if i < len(of.val) else float("nan")
        bv = of.buy_vwap[i] if i < len(of.buy_vwap) else float("nan")
        sv = of.sell_vwap[i] if i < len(of.sell_vwap) else float("nan")
        vd = of.vwap_delta[i] if i < len(of.vwap_delta) else float("nan")
        lines.append(
            f"{b.seq:<4} | {d:+.0f} | {cd:+.0f} | {_fmt_price(poc)} | {_fmt_price(vah)} | "
            f"{_fmt_price(val)} | {_fmt_price(bv)} | {_fmt_price(sv)} | {_fmt_price(vd)}"
        )
    lines.append("")
    lines.append(
        "⚠️ 订单流经 MT5 CFD 代理获取，方向按 Tick Rule 近似分类，成交量为 tick 计数近似值，非交易所真实成交。"
    )
    return "\n".join(lines)


def build_wyckoff_block(wa: WyckoffAnalysis) -> str:
    return wa.render_text()


def build_stage1_messages(
    frame: KlineFrame,
    wyckoff: WyckoffAnalysis,
    *,
    analysis_mode: str = "original",
) -> list[dict]:
    """组装 Stage1 诊断消息。"""
    kline_table = build_kline_table(frame)
    of_block = build_orderflow_block(frame)
    wk_block = build_wyckoff_block(wyckoff)

    user = f"""## 阶段一：市场诊断

品种: {frame.symbol}  周期: {frame.timeframe}  K线数量: {len(frame.bars)}
（K线序号：1=最新已收盘，越大越早）

### K线数据（含技术指标）
{kline_table}

### 威科夫程序化诊断（第一意见，供你参考与校验）
{wk_block}

### 订单流数据
{of_block if of_block else "（订单流不可用）"}

请基于以上数据，严格按输出格式给出阶段一 JSON 诊断。
特别地，在 wyckoff_check 中说明你与程序威科夫诊断的一致性或分歧。
"""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def extract_json(content: str) -> dict | None:
    """从 LLM 输出提取 JSON。"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    if "```json" in content:
        start = content.index("```json") + 7
        end = content.index("```", start)
        try:
            return json.loads(content[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass
    b = content.find("{")
    if b >= 0:
        e = content.rfind("}")
        if e > b:
            try:
                return json.loads(content[b : e + 1])
            except json.JSONDecodeError:
                pass
    return None

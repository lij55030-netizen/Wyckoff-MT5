"""WKF 分析编排：数据 → 指标 → 订单流 → 威科夫 → AI。"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from wkf.ai.deepseek_client import DeepSeekClient
from wkf.ai.prompt_assembler import build_stage1_messages, extract_json
from wkf.config.settings import Settings
from wkf.data.base import KlineFrame
from wkf.data.mt5_source import (
    compute_indicators,
    enrich_frame_with_orderflow,
    fetch_mt5_bars,
)
from wkf.wyckoff.analyzer import WyckoffAnalysis, analyze

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    symbol: str
    timeframe: str
    frame: KlineFrame | None = None
    wyckoff: WyckoffAnalysis | None = None
    ai_diagnosis: dict | None = None
    ai_raw: str = ""
    ai_reasoning: str = ""
    usage: dict | None = None
    latency_ms: float = 0.0
    error: str = ""
    steps: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error == ""

    def to_report(self) -> str:
        parts = [
            f"=== WKF 威科夫分析报告: {self.symbol} {self.timeframe} ===",
            "",
        ]
        if self.error:
            parts.append(f"❌ 分析失败: {self.error}")
            return "\n".join(parts)
        if self.wyckoff:
            parts.append(self.wyckoff.render_text())
        if self.ai_diagnosis:
            parts.append("")
            parts.append("=== AI 增强诊断 ===")
            parts.append(json.dumps(self.ai_diagnosis, ensure_ascii=False, indent=2))
        parts.append("")
        parts.append(f"耗时: {self.latency_ms/1000:.1f}s")
        if self.usage:
            parts.append(f"Tokens: {self.usage}")
        return "\n".join(parts)


def run_analysis(
    symbol: str,
    timeframe: str,
    *,
    bar_count: int = 100,
    settings: Settings | None = None,
    with_ai: bool = True,
) -> AnalysisResult:
    """完整分析管线。"""
    from wkf.config.settings import load_settings

    settings = settings or load_settings()
    res = AnalysisResult(symbol=symbol, timeframe=timeframe)
    t0 = time.monotonic()

    try:
        # 1. 数据
        bars = fetch_mt5_bars(symbol, timeframe, bar_count)
        res.steps.append("MT5 K线获取")
        if not bars:
            res.error = "MT5 返回空 K 线数据"
            return res

        # 2. 指标
        ind = compute_indicators(bars)
        res.steps.append("指标计算(EMA/ATR/RSI/BB/VWAP)")

        frame = KlineFrame(
            symbol=symbol,
            timeframe=timeframe,
            bars=tuple(bars),
            indicators=ind,
        )
        # 3. 订单流
        frame = enrich_frame_with_orderflow(frame)
        res.steps.append("订单流增强(Delta/POC/VA/足迹)")

        # 4. 威科夫三层
        wa = analyze(frame)
        res.wyckoff = wa
        res.steps.append("威科夫三层分析(背景/价值区域/订单流验证)")

        res.frame = frame

        # 5. AI 诊断（无 API Key 自动切换纯规则模式）
        if with_ai and settings.provider.api_key:
            client = DeepSeekClient(settings.provider)
            messages = build_stage1_messages(frame, wa)
            reply = client.chat(messages, thinking=settings.provider.thinking)
            res.ai_raw = reply.content
            res.ai_reasoning = reply.reasoning_content
            res.ai_diagnosis = extract_json(reply.content)
            res.usage = reply.usage
            res.latency_ms = reply.latency_ms
            res.steps.append("AI 增强诊断")
        elif with_ai and not settings.provider.api_key:
            res.steps.append("AI 诊断(纯规则模式：未配置 API Key)")
        elif not with_ai:
            res.steps.append("AI 诊断(跳过)")

    except Exception as exc:
        logger.exception("WKF 分析失败")
        res.error = str(exc)

    res.latency_ms = (time.monotonic() - t0) * 1000
    return res

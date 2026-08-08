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


def _fetch_bars_via_source(
    symbol: str, timeframe: str, bar_count: int,
    settings: Settings | None, close_confirm: bool | None = None,
) -> list:
    """按数据源模式拉取 K 线（需求三：yfinance 可选数据源）。

    【改动点】取数统一走 wkf.data.datasource.get_data_source()：
      · data_source=mt5（默认）→ 走既有 fetch_mt5_bars（完整功能）；
      · data_source=yfinance → 走 YfinanceSource（无Tick，上层逻辑不变）。
    【改动点】V3.0 收线确认：close_confirm=True 时 MT5 取数剔除未收盘 K 线。
    【涉及文件】wkf/orchestrator/runner.py + wkf/data/datasource.py
    【验证方式】data_source=mt5 行为与旧版完全一致（e2e 40/40）；
                yfinance 模式返回的 KlineBar 列表结构一致。
    """
    from wkf.data.datasource import DS_MT5, get_data_source

    mode = None
    try:
        mode = settings.general.data_source if settings is not None else None
    except Exception:
        mode = None
    if close_confirm is None:
        close_confirm = True
        try:
            close_confirm = bool(settings.general.close_confirm)  # type: ignore[union-attr]
        except Exception:
            close_confirm = True
    if mode == DS_MT5 or mode is None:
        return fetch_mt5_bars(symbol, timeframe, bar_count, close_confirm=close_confirm)
    src = get_data_source(mode)
    return src.fetch_bars(symbol, timeframe, bar_count)


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
    progress_callback=None,
    ai_stream_callback=None,
) -> AnalysisResult:
    """完整分析管线。

    progress_callback: 可选进度回调（0~100 整数），阶段划分：
      数据加载 0~25 → 快照生成 25~50 → AI诊断推理 50~80 → 决策组装 80~100。
    ai_stream_callback: 可选 AI 流式回调 (reasoning, content)，边生成边输出。
    """
    from wkf.config.settings import load_settings

    settings = settings or load_settings()
    res = AnalysisResult(symbol=symbol, timeframe=timeframe)
    t0 = time.monotonic()

    try:
        # 1. 数据
        bars = _fetch_bars_via_source(symbol, timeframe, bar_count, settings)
        res.steps.append("行情K线获取")
        if not bars:
            res.error = "数据源返回空 K 线数据"
            return res
        if progress_callback:
            progress_callback(25, "数据加载完成")

        # 2. 指标（参数来自设置，可配置）
        ind_cfg = settings.indicators
        ind = compute_indicators(
            bars,
            rsi_period=ind_cfg.rsi_period,
            bollinger_period=ind_cfg.bollinger_period,
            bollinger_std=ind_cfg.bollinger_std,
            ema_period=ind_cfg.ema_period,
            atr_period=ind_cfg.atr_period,
        )
        res.steps.append("指标计算(EMA/ATR/RSI/BB/VWAP)")

        frame = KlineFrame(
            symbol=symbol,
            timeframe=timeframe,
            bars=tuple(bars),
            indicators=ind,
        )
        # 3. 订单流
        frame = enrich_frame_with_orderflow(frame, va_pct=ind_cfg.value_area_pct)
        res.steps.append("订单流增强(Delta/POC/VA/足迹)")

        # 4. 威科夫三层
        wa = analyze(
            frame,
            va_pct=ind_cfg.value_area_pct,
            swing_window=ind_cfg.swing_window,
            footprint_threshold=ind_cfg.footprint_threshold,
        )
        res.wyckoff = wa
        res.steps.append("威科夫三层分析(背景/价值区域/订单流验证)")
        if progress_callback:
            progress_callback(50, "快照生成")

        res.frame = frame

        # 5. AI 诊断（无 API Key 自动切换纯规则模式）
        if with_ai and settings.provider.api_key:
            if progress_callback:
                progress_callback(55, "AI诊断推理中")
            try:
                client = DeepSeekClient(settings.provider)
                messages = build_stage1_messages(frame, wa)
                reply = client.chat(
                    messages,
                    thinking=settings.provider.thinking,
                    stream_callback=ai_stream_callback,
                )
                res.ai_raw = reply.content
                res.ai_reasoning = reply.reasoning_content
                res.ai_diagnosis = extract_json(reply.content)
                res.usage = reply.usage
                res.latency_ms = reply.latency_ms
                res.steps.append("AI 增强诊断")
                if progress_callback:
                    progress_callback(80, "AI诊断完成")
            except Exception as ai_exc:  # noqa: BLE001
                # 【改动点】V3.0：AI 调用失败不整体失败——降级为纯规则模式，
                # 保留威科夫三层结果（此前异常被外层 except 捕获导致整单失败）。
                logger.warning("AI 诊断失败，降级纯规则模式: %s", ai_exc)
                res.ai_diagnosis = None
                res.steps.append(f"AI 诊断失败，降级纯规则模式（{str(ai_exc)[:60]}）")
                if progress_callback:
                    progress_callback(80, "AI诊断降级")
        elif with_ai and not settings.provider.api_key:
            res.steps.append("AI 诊断(纯规则模式：未配置 API Key)")
        elif not with_ai:
            res.steps.append("AI 诊断(跳过)")

    except Exception as exc:
        logger.exception("WKF 分析失败")
        res.error = str(exc)

    res.latency_ms = (time.monotonic() - t0) * 1000
    return res


def _build_frame(
    symbol: str,
    timeframe: str,
    bars: list,
    settings: Settings,
    *,
    fetch_ticks: bool = True,
) -> tuple[KlineFrame, WyckoffAnalysis | None]:
    """由 K线 bars 构建 frame（指标 + 订单流 + 威科夫）。

    【改动点】从 fetch_frame_only 抽出公共构建逻辑，供磁盘缓存命中路径复用
    （fetch_ticks=False 时跳过 tick 拉取，秒级出图；首次完整拉取时 fetch_ticks=True）。
    """
    ind_cfg = settings.indicators
    ind = compute_indicators(
        bars,
        rsi_period=ind_cfg.rsi_period,
        bollinger_period=ind_cfg.bollinger_period,
        bollinger_std=ind_cfg.bollinger_std,
        ema_period=ind_cfg.ema_period,
        atr_period=ind_cfg.atr_period,
    )
    frame = KlineFrame(
        symbol=symbol, timeframe=timeframe,
        bars=tuple(bars), indicators=ind,
    )
    frame = enrich_frame_with_orderflow(
        frame, va_pct=ind_cfg.value_area_pct, fetch_ticks=fetch_ticks,
    )
    wa = analyze(
        frame,
        va_pct=ind_cfg.value_area_pct,
        swing_window=ind_cfg.swing_window,
        footprint_threshold=ind_cfg.footprint_threshold,
    )
    return frame, wa


def fetch_frame_only(
    symbol: str,
    timeframe: str,
    *,
    bar_count: int = 100,
    settings: Settings | None = None,
) -> tuple[KlineFrame, WyckoffAnalysis | None, str]:
    """仅获取数据+指标+订单流+威科夫分析（不调用 AI，速度快）。

    Returns
    -------
    (frame, wyckoff, error) — error 为空串表示成功。
    """
    from wkf.config.settings import load_settings

    settings = settings or load_settings()
    try:
        bars = _fetch_bars_via_source(symbol, timeframe, bar_count, settings)
        if not bars:
            return None, None, "数据源返回空 K 线数据"
        frame, wa = _build_frame(symbol, timeframe, bars, settings)
        return frame, wa, ""
    except Exception as exc:
        logger.exception("WKF 数据获取失败")
        return None, None, str(exc)


def fetch_frame_cached(
    symbol: str,
    timeframe: str,
    *,
    bar_count: int = 100,
    settings: Settings | None = None,
    use_disk_cache: bool = True,
) -> tuple[KlineFrame, WyckoffAnalysis | None, str, bool]:
    """三级取数（内存缓存由 GUI 层负责）：磁盘缓存 → MT5 网络拉取。

    【改动点】需求2-3：K线磁盘缓存，重复访问同一品种周期直接读缓存跳过接口请求。
    【涉及文件】wkf/orchestrator/runner.py + wkf/data/cache_manager.py
    【验证方式】首次拉取后再次访问同品种周期：磁盘命中（返回 from_cache=True），
               秒级出图；cache/kline_*.json 文件生成。
    Returns
    -------
    (frame, wyckoff, error, from_cache)
    """
    from wkf.config.settings import load_settings
    from wkf.data.cache_manager import disk_cache_get, disk_cache_put

    settings = settings or load_settings()
    try:
        if use_disk_cache:
            bars = disk_cache_get(symbol, timeframe)
            if bars:
                # 磁盘命中：跳过数据源与 tick 拉取，秒级出图
                frame, wa = _build_frame(
                    symbol, timeframe, bars, settings, fetch_ticks=False
                )
                return frame, wa, "", True
        bars = _fetch_bars_via_source(symbol, timeframe, bar_count, settings)
        if not bars:
            return None, None, "数据源返回空 K 线数据", False
        frame, wa = _build_frame(symbol, timeframe, bars, settings)
        if use_disk_cache:
            disk_cache_put(symbol, timeframe, bars)
        return frame, wa, "", False
    except Exception as exc:
        logger.exception("WKF 数据获取失败")
        return None, None, str(exc), False


def get_latest_bar_ts(symbol: str, timeframe: str) -> int:
    """获取最新已收盘 K 线的 ts_open（用于检测新 K 线收盘）。

    返回 -1 表示获取失败。
    注意：此处 close_confirm=False 保留最新（可能未收盘）K 线，
    供 K 线倒计时与「新 K 线开始」检测使用；分析取数才按收线确认剔除。
    """
    try:
        bars = _fetch_bars_via_source(symbol, timeframe, 2, None, close_confirm=False)
        if bars:
            return bars[0].ts_open
        return -1
    except Exception:
        return -1

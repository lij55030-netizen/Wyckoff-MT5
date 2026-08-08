"""DeepSeek AI 客户端（OpenAI 兼容协议）。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from wkf.config.settings import ProviderSettings

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI as _OpenAI
except ImportError:
    _OpenAI = None


@dataclass
class AIReply:
    content: str
    reasoning_content: str = ""
    usage: dict = None  # type: ignore[assignment]
    latency_ms: float = 0.0


class DeepSeekClient:
    def __init__(self, settings: ProviderSettings, logger_: Any = None) -> None:
        self._settings = settings
        self._log = logger_ or logger

    def chat(
        self,
        messages: list[dict],
        *,
        thinking: bool | None = None,
        timeout_s: float = 300.0,
        stream_callback=None,
    ) -> AIReply:
        if _OpenAI is None:
            raise RuntimeError("openai 包未安装")

        client = _OpenAI(
            base_url=self._settings.base_url,
            api_key=self._settings.api_key,
        )
        use_thinking = self._settings.thinking if thinking is None else thinking

        kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "timeout": timeout_s,
            # 思考(thinking)模式下 reasoning 会占用输出预算；8192/16384 均曾被思考耗尽
            # 导致正式回答被截断为空（实测 reasoning_tokens=16384 时 content 为空）。
            # 提高到 32768（API 接受上限内），保证思考之后仍有空间输出正式诊断。
            "max_tokens": 32768,
        }
        if use_thinking and "deepseek" in (self._settings.base_url or "").lower():
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        t0 = time.monotonic()
        if stream_callback is not None:
            # 【改动点】V3.1：流式输出——边生成边回调 (reasoning, content)，
            # 供界面实时展示 AI 推理过程（不等待全部收尾一次性返回）。
            kwargs["stream"] = True
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            stream = client.chat.completions.create(**kwargs)
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                c = getattr(delta, "content", None) or ""
                r = getattr(delta, "reasoning_content", None) or ""
                if c:
                    content_parts.append(c)
                if r:
                    reasoning_parts.append(r)
                if c or r:
                    stream_callback(r, c)
            elapsed = (time.monotonic() - t0) * 1000
            return AIReply(
                content="".join(content_parts),
                reasoning_content="".join(reasoning_parts),
                usage=None,
                latency_ms=elapsed,
            )

        resp = client.chat.completions.create(**kwargs)
        elapsed = (time.monotonic() - t0) * 1000

        msg = resp.choices[0].message
        content = getattr(msg, "content", "") or ""
        reasoning = getattr(msg, "reasoning_content", "") or ""
        usage_raw = None
        if getattr(resp, "usage", None) is not None:
            usage_raw = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
                "reasoning_tokens": getattr(resp.usage, "completion_tokens_details", None) and getattr(
                    resp.usage.completion_tokens_details, "reasoning_tokens", None
                ) or 0,
            }

        return AIReply(
            content=content,
            reasoning_content=reasoning,
            usage=usage_raw,
            latency_ms=elapsed,
        )

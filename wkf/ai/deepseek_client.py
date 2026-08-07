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
            "max_tokens": 8192,
        }
        if use_thinking and "deepseek" in (self._settings.base_url or "").lower():
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        t0 = time.monotonic()
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

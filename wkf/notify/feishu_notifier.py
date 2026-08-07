"""飞书机器人通知（webhook 发消息，不依赖 lark-cli）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Any

from wkf.config.settings import Settings

logger = logging.getLogger(__name__)

_HOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook"
_TIMEOUT_S = 12


def _gen_sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def _config(settings: Settings | None) -> dict:
    if settings is not None:
        return settings.feishu.model_dump()
    from wkf.config.settings import load_settings

    return load_settings().feishu.model_dump()


def send_text(
    text: str,
    *,
    settings: Settings | None = None,
) -> bool:
    """发送纯文本消息到飞书群。"""
    cfg = _config(settings)
    if not cfg.get("enabled", True):
        return False
    webhook = (cfg.get("webhook_url") or "").strip()
    if not webhook:
        logger.warning("飞书 webhook_url 未配置")
        return False

    try:
        import requests
    except ImportError:
        logger.warning("requests 未安装")
        return False

    payload: dict[str, Any] = {"msg_type": "text", "content": {"text": text}}
    secret = (cfg.get("secret") or "").strip()
    if secret:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = _gen_sign(secret, ts)

    try:
        resp = requests.post(webhook, json=payload, headers={"Content-Type": "application/json"},
                             timeout=_TIMEOUT_S)
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            return True
        logger.warning("飞书返回错误: %s", result)
        return False
    except Exception as exc:
        logger.warning("飞书发送异常: %s", exc)
        return False


def send_analysis_notice(
    *,
    symbol: str,
    timeframe: str,
    bias: str = "",
    trigger: str = "",
    invalidation: str = "",
    summary: str = "",
    settings: Settings | None = None,
) -> bool:
    """发送威科夫分析完成通知。"""
    lines = [
        "📊 WKF 威科夫分析完成",
        f"品种：{symbol}　周期：{timeframe}",
    ]
    if bias:
        lines.append(f"倾向：{bias}")
    if trigger:
        lines.append(f"入场触发：{trigger}")
    if invalidation:
        lines.append(f"失效条件：{invalidation}")
    if summary:
        lines.append(f"\n{summary}")
    return send_text("\n".join(lines), settings=settings)

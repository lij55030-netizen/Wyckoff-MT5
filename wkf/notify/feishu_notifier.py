"""飞书机器人通知（webhook 发消息，不依赖 lark-cli）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from wkf.config.settings import Settings

logger = logging.getLogger(__name__)

_HOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook"
_TIMEOUT_S = 12
# 同品种推送防抖：记录最近一次推送时间（秒）
_last_push: dict[str, float] = {}
# 推送日志文件（本地留存，便于排查）
PUSH_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "push_log.txt"


def _gen_sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def _config(settings: Settings | None) -> dict:
    if settings is not None:
        return settings.feishu.model_dump()
    from wkf.config.settings import load_settings

    return load_settings().feishu.model_dump()


def _log_push(symbol: str, ok: bool, detail: str = "") -> None:
    """本地留存推送日志（追加写 output/push_log.txt）。"""
    try:
        PUSH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with PUSH_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {symbol} {'成功' if ok else '失败'} {detail}\n")
    except Exception:
        pass


def _send_payload(payload: dict, cfg: dict) -> bool:
    """发送 payload 到飞书 webhook（统一签名/异常/日志处理）。"""
    webhook = (cfg.get("webhook_url") or "").strip()
    if not webhook or "__需要用户" in webhook:
        logger.warning("飞书 webhook_url 未配置或不完整")
        return False
    try:
        import requests
    except ImportError:
        logger.warning("requests 未安装")
        return False
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


def send_text(
    text: str,
    *,
    settings: Settings | None = None,
) -> bool:
    """发送纯文本消息到飞书群。"""
    cfg = _config(settings)
    if not cfg.get("enabled", True):
        return False
    payload: dict[str, Any] = {"msg_type": "text", "content": {"text": text}}
    return _send_payload(payload, cfg)


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


def push_analysis_notice(
    *,
    symbol: str,
    timeframe: str,
    analysis_time: str = "",
    prob: dict | None = None,
    bias_zh: str = "",
    price: float | None = None,
    va_text: str = "",
    of_text: str = "",
    settings: Settings | None = None,
) -> bool:
    """分析完成推送（增强版）：
      · 仅分析完成触发，软件闲置不发消息（notify_enabled 开关）
      · 同品种防抖：push_dedup_minutes 分钟内不重复推送
      · 行情概率 ≥ push_prob_threshold 时，核心字段红色加粗（post 富文本）
      · 本地留存推送日志 output/push_log.txt
    """
    cfg = _config(settings)
    if not cfg.get("notify_enabled", True) or not cfg.get("enabled", True):
        return False
    webhook = (cfg.get("webhook_url") or "").strip()
    if not webhook:
        logger.warning("飞书 webhook_url 未配置，跳过推送")
        return False

    # 同品种防抖
    dedup_min = int(cfg.get("push_dedup_minutes", 3) or 3)
    now = time.time()
    last = _last_push.get(symbol, 0.0)
    if last > 0 and (now - last) < dedup_min * 60:
        logger.info("飞书推送防抖生效：%s %s 分钟内已推送", symbol, dedup_min)
        return False
    _last_push[symbol] = now

    # 行情概率：多头/空头任一达到阈值 → 核心字段红色加粗
    threshold = float(cfg.get("push_prob_threshold", 66.5) or 66.5)
    prob = prob or {}
    long_p = int(prob.get("long", 0))
    short_p = int(prob.get("short", 0))
    highlight = max(long_p, short_p) >= threshold

    lines: list[list[dict]] = []
    title = f"📊 WKF 威科夫分析完成 · {symbol} {timeframe}"
    if analysis_time:
        title += f"（{analysis_time}）"

    def _t(text: str, color: str | None = None) -> dict:
        item: dict = {"tag": "text", "text": text}
        if color:
            item["style"] = {"color": color}
        return item

    rows = [
        [{"tag": "text", "text": f"品种：{symbol}　周期：{timeframe}"}],
    ]
    if analysis_time:
        rows.append([{"tag": "text", "text": f"分析时间：{analysis_time}"}])
    if price is not None:
        rows.append([_t(f"现价：{price:,.2f}")])
    # 概率行：高概率时红色加粗
    prob_color = "red" if highlight else None
    prob_bold = {"tag": "text", "text": f"行情概率：多头 {long_p}% ／ 空头 {short_p}% ／ 震荡 {prob.get('neutral', 0)}%"}
    if highlight:
        prob_bold["style"] = {"color": "red", "bold": True}
    rows.append([prob_bold])
    if bias_zh:
        rows.append([_t(f"倾向：{bias_zh}", "red" if highlight else None)])
    if va_text:
        rows.append([_t(va_text)])
    if of_text:
        rows.append([_t(of_text)])
    rows.append([_t("以上仅为分析参考，不构成投资建议。", "grey")])
    # 【改动点】飞书推送固定附注订单流风险提示（与 GUI/HTML/文件头同文案）
    # 【涉及文件】wkf/notify/feishu_notifier.py
    # 【验证方式】分析完成推送的飞书消息末尾可见订单流 Tick 近似换算风险提示
    rows.append([_t("⚠ 订单流由 MT5 Tick 数据近似换算生成，并非交易所原始盘口订单流，仅用于威科夫结构定性研判，不建议作为高频短线交易依据。", "grey")])

    payload: dict[str, Any] = {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": title, "content": rows}}},
    }
    ok = _send_payload(payload, cfg)
    _log_push(symbol, ok, f"{timeframe} 概率多{long_p}/空{short_p} 高亮={highlight}")
    return ok

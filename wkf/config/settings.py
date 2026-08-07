"""WKF 配置模型与路径。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_JSON_PATH = CONFIG_DIR / "settings.json"
PROMPT_DIR = PROJECT_ROOT / "prompt_engineering"


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "deepseek-v4-pro"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    thinking: bool = True
    reasoning_effort: str = "high"
    context_window: int = 2000000


class GeneralSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    analysis_bar_count: int = 48  # 图表默认时间级别 = 48小时窗口；此为根数下限
    # 【改动点】默认品种 XAU/USD(GC1!)、默认周期 5 分钟（覆盖原 NQ1!/15m 默认）
    # 【涉及文件】wkf/config/settings.py（对应 config_manager.py 默认配置）
    # 【验证方式】首次启动品种=GC1!、周期=5分
    last_symbol: str = "GC1!"
    last_timeframe: str = "5m"
    # 【改动点】「品种-周期」独立记忆键值对：切换品种恢复该品种上次周期，
    #           切换周期立即写回；重启记忆不丢失。
    # 【涉及文件】wkf/config/settings.py
    # 【验证方式】GC1! 选30分→切XAU选5分→切回GC1!恢复30分；重启保留
    per_symbol_timeframe: dict[str, str] = Field(default_factory=dict)
    # K线明细表格渲染样式: "new"=表格UI(默认) / "old"=旧版纯文本(一键回滚)
    table_style: str = "new"
    # 首次启动标志：用于启动时弹窗引导基础配置（AI Key / 飞书 Webhook）
    first_run: bool = True


class IndicatorSettings(BaseModel):
    """分析指标参数（用户可在「其他设置」菜单调整）。"""

    model_config = ConfigDict(extra="ignore")

    rsi_period: int = 14
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    ema_period: int = 20
    atr_period: int = 14
    value_area_pct: float = 0.682  # 威科夫价值区域占比（±1σ）
    footprint_threshold: float = 2.0  # 足迹图失衡最低倍数
    swing_window: int = 40  # 背景判定摆动窗口


class FeishuSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    webhook_url: str = ""
    secret: str = ""
    app_id: str = ""
    app_secret: str = ""
    # 分析完成推送开关（仅行情分析完成触发，软件闲置不发消息）
    notify_enabled: bool = True
    # 同品种推送防抖分钟数（默认 3 分钟，避免重复推送）
    push_dedup_minutes: int = 3
    # 行情概率达到该阈值时，核心字段使用红色加粗推送（%）
    push_prob_threshold: float = 66.5


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    indicators: IndicatorSettings = Field(default_factory=IndicatorSettings)
    feishu: FeishuSettings = Field(default_factory=FeishuSettings)


def load_settings(path: Path | str | None = None) -> Settings:
    """加载 settings.json，并用 config.ini 覆盖（config.ini 优先级更高）。"""
    p = Path(path) if path else SETTINGS_JSON_PATH
    if not p.exists():
        settings = Settings()
    else:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            settings = Settings.model_validate(raw)
        except Exception:
            settings = Settings()

    # config.ini 覆盖（DeepSeek Key / Webhook / Secret / 模型）
    ini = p.parent / "config.ini"
    if ini.exists():
        overrides = _parse_config_ini(ini)
        if overrides.get("api_key"):
            settings.provider.api_key = overrides["api_key"]
        if overrides.get("model"):
            settings.provider.model = overrides["model"]
        if overrides.get("base_url"):
            settings.provider.base_url = overrides["base_url"]
        if overrides.get("webhook_url"):
            settings.feishu.webhook_url = overrides["webhook_url"]
        if overrides.get("secret"):
            settings.feishu.secret = overrides["secret"]
    return settings


def _parse_config_ini(ini: Path) -> dict[str, str]:
    """解析简单 INI（[section] key=value），返回扁平键值。"""
    out: dict[str, str] = {}
    try:
        import configparser

        cp = configparser.ConfigParser()
        cp.read(ini, encoding="utf-8")
        for section in cp.sections():
            for k, v in cp.items(section):
                out[f"{section}.{k}"] = v.strip()
    except Exception:
        pass
    # 兼容扁平写法
    flat: dict[str, str] = {}
    try:
        lines = ini.read_text(encoding="utf-8").splitlines()
    except Exception:
        return flat
    cur_section = ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur_section = line[1:-1].strip().lower()
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            key = (cur_section + "." if cur_section else "") + k.strip().lower()
            flat[key] = v.strip()
    # 映射到配置键
    mapping = {
        "api_key": "provider.api_key", "deepseek_api_key": "provider.api_key",
        "model": "provider.model", "deepseek_model": "provider.model",
        "base_url": "provider.base_url",
        "webhook": "feishu.webhook_url", "webhook_url": "feishu.webhook_url",
        "feishu_webhook": "feishu.webhook_url",
        "secret": "feishu.secret", "feishu_secret": "feishu.secret",
    }
    result: dict[str, str] = {}
    for ini_key, target in mapping.items():
        for k, v in flat.items():
            if k.endswith(ini_key) or k == ini_key:
                result[target.split(".")[-1]] = v
                break
    return result


def save_settings(settings: Settings, path: Path | str | None = None) -> None:
    p = Path(path) if path else SETTINGS_JSON_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

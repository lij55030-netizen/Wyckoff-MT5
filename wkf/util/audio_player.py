"""简易音频提示工具：高概率行情预警铃声（本地，无音频文件静默不报错）。"""
from __future__ import annotations

import math
import struct
import time
import wave
from pathlib import Path

# 【改动点】高概率提示音：判定规则「行情综合概率 > 60% 播放单次提示音」，
#           30 秒内同一品种不重复响铃（防抖，持续跟踪模式不循环爆音）。
#           60% = 本地铃声预警；66.5% = 飞书重点消息推送（push_prob_threshold），
#           两处阈值独立各司其职。
# 【涉及文件】wkf/util/audio_player.py（新增，对应假设文件 audio_player.py）
# 【验证方式】构造 62% 概率行情执行分析听到提示音；30 秒内再次分析同品种无二次铃声

# 同品种最近一次响铃时间（秒）
_last_alert: dict[str, float] = {}
# 同品种防抖窗口（秒）
ALERT_DEDUP_S = 30

# 内置提示音路径（随打包发布；不存在则静默）
_ALERT_WAV = Path(__file__).resolve().parent.parent.parent / "assets" / "alert.wav"


def ensure_alert_wav() -> Path | None:
    """内置 wav 提示音不存在时自动生成（双音正弦波，约 0.6s）。"""
    if _ALERT_WAV.exists():
        return _ALERT_WAV
    try:
        _ALERT_WAV.parent.mkdir(parents=True, exist_ok=True)
        rate = 22050
        frames = []
        # 两个短音：880Hz(0.18s) + 停顿(0.05s) + 660Hz(0.25s)
        for freq, dur in ((880.0, 0.18), (0.0, 0.05), (660.0, 0.25)):
            n = int(rate * dur)
            for i in range(n):
                if freq <= 0:
                    frames.append(0)
                else:
                    env = min(1.0, i / (rate * 0.01), (n - i) / (rate * 0.01))
                    frames.append(int(32767 * env * math.sin(2 * math.pi * freq * i / rate)))
        with wave.open(str(_ALERT_WAV), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(struct.pack(f"<{len(frames)}h", *frames))
        return _ALERT_WAV
    except Exception:
        return None


def play_alert(symbol: str | None = None, dedup_s: float = ALERT_DEDUP_S) -> bool:
    """播放提示音（同品种防抖）。

    - symbol 传入时：dedup_s 秒内同一品种不重复响铃。
    - 无 wav 文件 / 播放异常：静默返回 False，不抛错。
    """
    now = time.time()
    if symbol:
        last = _last_alert.get(symbol, 0.0)
        if now - last < dedup_s:
            return False
        _last_alert[symbol] = now
    try:
        wav = ensure_alert_wav()
        if wav is None:
            return False
        if _is_windows():
            from winsound import SND_ASYNC, SND_FILENAME, PlaySound

            PlaySound(str(wav), SND_FILENAME | SND_ASYNC)
            return True
        # 非 Windows：尝试系统播放器（失败静默）
        import subprocess

        subprocess.Popen(["start", str(wav)], shell=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _is_windows() -> bool:
    import sys

    return sys.platform == "win32"

"""WKF 飞书指令监听器（完整版）。

支持指令：
  1. 单品种单周期:    分析 NQ 15m / 报告 ES 1h / 查一下 XAU 5m
  2. 全周期复盘:      NQ 全周期复盘 / ES 全周期复盘 / XAU 全周期复盘
  3. 三品种汇总:      三品种全周期汇总
  4. 定向精简查询:    XAU 关键价位 30m / ES 订单流拐点 5m / NQ 多空定性 15m
  5. HTML 报告:       推送最新html行情报告
  6. 帮助:            帮助 / help / 指令

启动:
  python tools/feishu_commander.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

LARK_CLI = r"C:\Users\可乐\.workbuddy\binaries\node\cli-connector-packages\lark-cli.cmd"
PYTHON = sys.executable
CLI_SCRIPT = _PROJECT_ROOT / "cli.py"

SYMBOLS = ["NQ", "ES", "XAU"]
TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]

# 指令模式
CMD_SINGLE = re.compile(
    r"(?:分析|报告|查一下|analyze|report)\s*[:：]?\s*"
    r"(NQ|ES|GC|XAU|GOLD|纳斯达克|纳指|标普|黄金|gold|nasdaq|sp500)\s*"
    r"(\d+\s*(?:m|min|分钟|h|hour|小时)?)",
    re.IGNORECASE,
)
CMD_REVIEW = re.compile(r"(NQ|ES|GC|XAU|GOLD|纳斯达克|纳指|标普|黄金)\s*全周期复盘", re.IGNORECASE)
CMD_ALL_REVIEW = re.compile(r"三品种\s*(?:全周期)?\s*(?:汇总|复盘)", re.IGNORECASE)
CMD_KEY_LEVELS = re.compile(
    r"(NQ|ES|GC|XAU|GOLD|纳斯达克|纳指|标普|黄金)\s*关键价位\s*(\d+\s*(?:m|min|h|hour)?)",
    re.IGNORECASE,
)
CMD_OF_PIVOT = re.compile(
    r"(NQ|ES|GC|XAU|GOLD|纳斯达克|纳指|标普|黄金)\s*订单流拐点\s*(\d+\s*(?:m|min|h|hour)?)",
    re.IGNORECASE,
)
CMD_BIAS = re.compile(
    r"(NQ|ES|GC|XAU|GOLD|纳斯达克|纳指|标普|黄金)\s*(?:多空定性|一句话结论|定性)\s*(\d+\s*(?:m|min|h|hour)?)?",
    re.IGNORECASE,
)
CMD_HTML = re.compile(r"(?:推送|发|查看)?\s*(?:最新)?\s*html\s*(?:行情)?\s*(?:报告|分析)?", re.IGNORECASE)

SYMBOL_ALIAS = {
    "NQ": "NQ1!", "纳斯达克": "NQ1!", "纳指": "NQ1!", "nasdaq": "NQ1!",
    "ES": "ES1!", "标普": "ES1!", "sp500": "ES1!",
    "GC": "GC1!", "XAU": "GC1!", "GOLD": "GC1!", "黄金": "GC1!", "gold": "GC1!",
}

TF_ALIAS = {
    "5m": "5m", "5min": "5m", "10m": "10m", "10min": "10m",
    "15m": "15m", "15min": "15m", "30m": "30m", "30min": "30m",
    "1h": "1h", "60m": "1h", "1hour": "1h",
}


def _cli_env() -> dict:
    env = dict(os.environ)
    env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    return env


def run_cli(args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [LARK_CLI, *args],
            capture_output=True, text=True, timeout=timeout,
            env=_cli_env(), encoding="utf-8", errors="replace",
        )
        return proc.returncode, proc.stdout
    except Exception as exc:
        return -1, str(exc)


def send_message(chat_id: str, text: str) -> bool:
    code, out = run_cli(
        ["im", "+messages-send", "--chat-id", chat_id, "--msg-type", "text",
         "--text", text, "--as", "bot", "--json"],
        timeout=30,
    )
    return code == 0 and '"ok": true' in out


def _send_split(chat_id: str, text: str, limit: int = 3800) -> None:
    """超长文本分段发送。"""
    if len(text) <= limit:
        send_message(chat_id, text)
        return
    for i in range(0, len(text), limit):
        send_message(chat_id, text[i : i + limit])


def _run_in_thread(chat_id: str, fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _analyze_single(chat_id: str, symbol: str, timeframe: str) -> None:
    send_message(chat_id, f"⏳ WKF 分析 {symbol} {timeframe} 中...")

    def _work() -> None:
        try:
            proc = subprocess.run(
                [PYTHON, str(CLI_SCRIPT), symbol, timeframe],
                capture_output=True, text=True, timeout=600,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode == 0 and proc.stdout.strip():
                _send_split(chat_id, proc.stdout.strip())
            else:
                err = (proc.stderr or proc.stdout or "").strip()[:300]
                send_message(chat_id, f"❌ 分析失败: {err or '未知错误'}")
        except Exception as exc:
            send_message(chat_id, f"❌ 分析异常: {exc}")

    _run_in_thread(chat_id, _work)


def _run_batch(chat_id: str, render_fn, with_ai: bool = True) -> None:
    send_message(chat_id, f"⏳ 批量分析中（约 {3 if '三品种' in render_fn.__name__ else 5} 个周期）...")

    def _work() -> None:
        try:
            text = render_fn()
            _send_split(chat_id, text)
        except Exception as exc:
            send_message(chat_id, f"❌ 批量分析失败: {exc}")

    _run_in_thread(chat_id, _work)


def _render_review(symbol: str):
    from wkf.orchestrator.batch_analyzer import (
        render_full_review,
        run_full_review,
    )

    results = run_full_review(symbol, with_ai=True)
    return render_full_review(symbol, results)


def _render_all_summary():
    from wkf.orchestrator.batch_analyzer import (
        render_all_summary,
        run_all_symbols_review,
    )

    data = run_all_symbols_review(with_ai=True)
    return render_all_summary(data)


def _render_key_levels(symbol: str, tf: str):
    from wkf.orchestrator.batch_analyzer import render_key_levels
    from wkf.orchestrator.runner import run_analysis

    res = run_analysis(symbol, tf, bar_count=80, with_ai=True)
    return render_key_levels(res)


def _render_of_pivot(symbol: str, tf: str):
    from wkf.orchestrator.batch_analyzer import render_orderflow_pivot
    from wkf.orchestrator.runner import run_analysis

    res = run_analysis(symbol, tf, bar_count=80, with_ai=True)
    return render_orderflow_pivot(res)


def _render_bias(symbol: str, tf: str):
    from wkf.orchestrator.batch_analyzer import render_one_line_bias
    from wkf.orchestrator.runner import run_analysis

    res = run_analysis(symbol, tf, bar_count=80, with_ai=True)
    return render_one_line_bias(res)


def _push_latest_html(chat_id: str) -> None:
    from wkf.orchestrator.batch_analyzer import OUTPUT_DIR

    html_files = sorted(OUTPUT_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not html_files:
        send_message(chat_id, "❌ 暂无 HTML 报告，请先执行一次分析")
        return
    latest = html_files[0]
    send_message(chat_id, f"📄 最新报告: {latest.name}\n{latest}")

    # 尝试上传图片格式的图表（如有 PNG）或直接发文本摘要
    try:
        from wkf.config.settings import load_settings

        settings = load_settings()
        proc = subprocess.run(
            [PYTHON, str(CLI_SCRIPT), "NQ", "15m"],
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            _send_split(chat_id, proc.stdout.strip())
    except Exception:
        pass


def handle_message(chat_id: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        return

    # 帮助
    if text in ("帮助", "help", "指令", "/help"):
        send_message(chat_id, (
            "📖 WKF 指令手册：\n"
            "1️⃣ 单品种分析: 分析 NQ 15m（NQ/ES/XAU × 5m/10m/15m/30m/1h）\n"
            "2️⃣ 全周期复盘: NQ 全周期复盘 / ES 全周期复盘 / XAU 全周期复盘\n"
            "3️⃣ 三品种汇总: 三品种全周期汇总\n"
            "4️⃣ 定向查询:\n"
            "   · XAU 关键价位 30m\n"
            "   · ES 订单流拐点 5m\n"
            "   · NQ 多空定性 15m\n"
            "5️⃣ 推送最新html行情报告"
        ))
        return

    # HTML 报告推送
    if CMD_HTML.search(text) and "html" in text.lower():
        send_message(chat_id, "⏳ 正在生成最新分析报告...")
        _run_in_thread(chat_id, lambda: _push_latest_html(chat_id))
        return

    # 三品种全周期汇总
    if CMD_ALL_REVIEW.search(text):
        send_message(chat_id, "⏳ 三品种全周期汇总中（15 次分析，约 3-6 分钟）...")
        _run_in_thread(chat_id, lambda: _send_split(chat_id, _render_all_summary()))
        return

    # 单品种全周期复盘
    m = CMD_REVIEW.search(text)
    if m:
        sym_key = m.group(1)
        symbol = SYMBOL_ALIAS.get(sym_key.lower() if sym_key.isascii() else sym_key)
        if not symbol:
            symbol = SYMBOL_ALIAS.get(sym_key)
        if symbol:
            send_message(chat_id, f"⏳ {symbol} 全周期复盘（5 个周期）中...")
            _run_in_thread(chat_id, lambda s=symbol: _send_split(chat_id, _render_review(s)))
            return

    # 关键价位
    m = CMD_KEY_LEVELS.search(text)
    if m:
        sym_key, tf_raw = m.group(1), m.group(2)
        symbol = SYMBOL_ALIAS.get(sym_key.lower() if sym_key.isascii() else sym_key) or SYMBOL_ALIAS.get(sym_key)
        tf = TF_ALIAS.get(tf_raw.lower(), "15m")
        if symbol:
            send_message(chat_id, f"⏳ 查询 {symbol} {tf} 关键价位...")
            _run_in_thread(chat_id, lambda s=symbol, t=tf: _send_split(chat_id, _render_key_levels(s, t)))
            return

    # 订单流拐点
    m = CMD_OF_PIVOT.search(text)
    if m:
        sym_key, tf_raw = m.group(1), m.group(2)
        symbol = SYMBOL_ALIAS.get(sym_key.lower() if sym_key.isascii() else sym_key) or SYMBOL_ALIAS.get(sym_key)
        tf = TF_ALIAS.get(tf_raw.lower(), "15m")
        if symbol:
            send_message(chat_id, f"⏳ 查询 {symbol} {tf} 订单流拐点...")
            _run_in_thread(chat_id, lambda s=symbol, t=tf: _send_split(chat_id, _render_of_pivot(s, t)))
            return

    # 多空定性
    m = CMD_BIAS.search(text)
    if m:
        sym_key, tf_raw = m.group(1), (m.group(2) or "")
        symbol = SYMBOL_ALIAS.get(sym_key.lower() if sym_key.isascii() else sym_key) or SYMBOL_ALIAS.get(sym_key)
        tf = TF_ALIAS.get(tf_raw.lower(), "15m")
        if symbol:
            send_message(chat_id, f"⏳ 分析 {symbol} {tf} 多空定性...")
            _run_in_thread(chat_id, lambda s=symbol, t=tf: _send_split(chat_id, _render_bias(s, t)))
            return

    # 单品种单周期
    m = CMD_SINGLE.search(text)
    if m:
        sym_key, tf_raw = m.group(1), m.group(2)
        symbol = SYMBOL_ALIAS.get(sym_key.lower() if sym_key.isascii() else sym_key) or SYMBOL_ALIAS.get(sym_key)
        tf = TF_ALIAS.get(tf_raw.lower().replace(" ", ""), "15m")
        if symbol:
            _analyze_single(chat_id, symbol, tf)
            return

    send_message(chat_id, "❓ 未识别的指令。发「帮助」查看全部指令")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    print("=" * 60)
    print("WKF 飞书指令监听器（完整版）")
    print("支持: 单品种分析 / 全周期复盘 / 三品种汇总 / 定向查询 / HTML报告")
    print("按 Ctrl+C 停止", flush=True)

    code, out = run_cli(["auth", "status", "--json"], timeout=20)
    if code != 0:
        print(f"❌ lark-cli 不可用: {out[:200]}")
        return 1
    print("✅ lark-cli 就绪", flush=True)

    env = _cli_env()
    try:
        proc = subprocess.Popen(
            [LARK_CLI, "event", "consume", "im.message.receive_v1",
             "--as", "bot", "--jq",
             '{text: .content, chat_id: .chat_id, message_id: .message_id}'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            env=env, bufsize=1,
        )
    except Exception as exc:
        print(f"❌ 启动事件监听失败: {exc}")
        return 1
    print("✅ 事件监听已启动", flush=True)

    def _drain_stderr() -> None:
        try:
            for line in proc.stderr:
                print(f"[event] {line.rstrip()}", file=sys.stderr)
        except Exception:
            pass

    threading.Thread(target=_drain_stderr, daemon=True).start()

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            chat_id = evt.get("chat_id", "")
            text = evt.get("text", "")
            if not chat_id or not text:
                continue
            print(f"[消息] from {chat_id}: {text[:60]}", flush=True)
            handle_message(chat_id, text)
    except KeyboardInterrupt:
        print("\n停止监听")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())

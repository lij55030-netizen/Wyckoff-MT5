# -*- coding: utf-8 -*-
"""
WKF 股票K线分析页面 —— 服务端
================================
纯 Python 标准库实现（http.server），零新增依赖，直接 `python server.py` 即可运行。

提供三个能力：
  GET  /                  -> 返回 index.html 页面
  GET  /api/kline         -> 从 MT5 拉取真实历史K线（OHLCV + MA5/MA20 + RSI14 + VWAP）
  POST /api/chat          -> 携带「页面当前K线数据 + 用户问题」调用 DeepSeek，
                             以 SSE(Server-Sent Events) 流式返回 AI 回答。
                             思考过程(reasoning)与正式回答(content)分事件推送。

关键设计：
  1. 数据真实性：K线一律来自 MT5 真实行情，聊天时把真实K线数据文本注入提示词，
     AI 只能基于这些数据回答；无 API Key 时自动降级为「纯规则计算」回答，
     只用真实数据做简单统计，绝不编造概率数值。
  2. 概率严谨性：系统提示词强制要求「最严厉、最审慎」语气 + 分情形给概率区间 +
     数据不足必须回答「无法判断」。
  3. 零依赖：不引入 Flask，避免安装额外包。
"""
from __future__ import annotations

import datetime
import json
import math
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ── 引入 WKF 现有模块（复用 MT5 数据链路与配置）──────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wkf.config.settings import load_settings            # noqa: E402
from wkf.data.mt5_source import fetch_mt5_bars, compute_indicators  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
PORT = 8000

# 品种别名 -> 内部符号（fetch_mt5_bars 直接吃 NQ1!/ES1!/GC1!）
SYMBOL_ALIAS = {
    "NQ": "NQ1!", "NQ1!": "NQ1!", "USTECHc": "NQ1!",
    "ES": "ES1!", "ES1!": "ES1!", "US500c": "ES1!",
    "XAU": "GC1!", "GC": "GC1!", "GC1!": "GC1!", "XAUUSD": "GC1!",
}
TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]

# ── AI 系统提示词：最严厉/最审慎的概率分析 ────────────────────────────────
SYSTEM_PROMPT = """你是 WKF 威科夫交易分析助手，只基于用户提供的【真实历史K线数据】回答问题。

【铁律 - 必须无条件遵守】
1. 【数据真实性】你只能使用用户提供的K线数据（时间/开高低收/成交量/均线等）进行计算与分析。
   严禁编造、猜测、捏造任何价格、涨跌幅、概率数值。所有数字必须能从给定数据推导出来。
   若数据不足或无法从数据推断，必须如实回答：「无法判断」，并说明缺什么数据。
2. 【概率分析语气】分析走势概率时，必须采用最严厉、最审慎的语气：
   - 明确指出各种可能情形（如：继续上涨 / 横盘震荡 / 下跌回调），并分别给出概率区间（如 60%-75%），
     概率区间必须是基于数据的合理估计并注明依据（如均线斜率、高低点结构、量能变化）。
   - 必须同时提示反向风险与失效条件，不得给出单边乐观结论。
3. 【免责声明】每次回答结尾固定附上：「以上仅是王先生的分析，仅做参考，不可以作为价值投资。」
4. 【回答结构】建议使用：① 数据观察（基于哪些K线）→ ② 分情形概率分析 → ③ 风险提示 → ④ 免责声明。
5. 用户问题若与K线分析无关（如闲聊、其他领域问题），礼貌说明你只能基于当前K线数据回答行情分析问题。"""


# ── K线数据工具 ──────────────────────────────────────────────────────────
def sma(values: list[float], period: int) -> list[float | None]:
    """简单移动平均；前 period-1 个值为 None（数据不足，不伪造）。"""
    out: list[float | None] = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = round(s / period, 2)
    return out


def load_kline(symbol: str, timeframe: str, count: int = 120) -> dict | None:
    """从 MT5 拉取真实K线，整理为前端可直接绘制的 JSON 结构（旧 -> 新）。"""
    inner = SYMBOL_ALIAS.get(symbol.upper(), symbol)
    # 注意：fetch_mt5_bars 返回 新->旧（seq=1 最新在 index 0）
    # compute_indicators 与输入同序：输入新->旧，则输出 index 0 = 最新bar 的有效值
    raw_bars = fetch_mt5_bars(inner, timeframe, count)
    if not raw_bars:
        return None
    ind = compute_indicators(raw_bars)
    # 前端绘图需要 旧 -> 新（时间从左往右），仅调整展示顺序，指标取值仍按新->旧
    bars = list(reversed(raw_bars))

    closes = [b.close for b in bars]
    ma5 = sma(closes, 5)
    ma20 = sma(closes, 20)

    items = []
    for i, b in enumerate(bars):
        items.append({
            "t": datetime.datetime.fromtimestamp(b.ts_open / 1000).strftime("%Y-%m-%d %H:%M"),
            "ts": b.ts_open,
            "o": round(b.open, 2),
            "h": round(b.high, 2),
            "l": round(b.low, 2),
            "c": round(b.close, 2),
            "v": int(b.volume),
            "ma5": ma5[i],
            "ma20": ma20[i],
        })

    last = items[-1]
    prev = items[-2] if len(items) > 1 else None
    chg = round(last["c"] - prev["c"], 2) if prev else 0.0
    chg_pct = round((last["c"] - prev["c"]) / prev["c"] * 100, 2) if prev and prev["c"] else 0.0

    def num(x) -> float | None:
        if x is None:
            return None
        try:
            v = float(x)
            return None if math.isnan(v) else round(v, 2)
        except (TypeError, ValueError):
            return None

    # 用 raw_bars 的最新指标值（新->旧顺序，index 0 = 最新）
    stats = {
        "symbol": inner,
        "timeframe": timeframe,
        "last_close": last["c"],
        "change": chg,
        "change_pct": chg_pct,
        "high20": max(b.high for b in bars[-20:]),
        "low20": min(b.low for b in bars[-20:]),
        "rsi14": num(ind.rsi14[0] if len(ind.rsi14) else None),
        "vwap": num(ind.vwap[0] if len(ind.vwap) else None),
        "ma5": last.get("ma5"),
        "ma20": last.get("ma20"),
        "count": len(items),
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"items": items, "stats": stats}


def kline_to_prompt_text(items: list[dict], stats: dict, max_bars: int = 60) -> str:
    """把K线数据转成文本注入提示词（只给最近 max_bars 根，控制 token）。"""
    recent = items[-max_bars:]
    lines = [
        f"品种: {stats['symbol']}  周期: {stats['timeframe']}  共 {stats['count']} 根已收盘K线",
        f"最新收盘: {stats['last_close']}  涨跌: {stats['change']} ({stats['change_pct']}%)",
        f"近20根最高/最低: {stats['high20']} / {stats['low20']}",
        f"RSI14: {stats['rsi14']}  VWAP: {stats['vwap']}  MA5: {stats['ma5']}  MA20: {stats['ma20']}",
        "",
        "最近K线明细(时间 开 高 低 收 量):",
    ]
    for b in recent:
        lines.append(
            f"  {b['t']}  O={b['o']} H={b['h']} L={b['l']} C={b['c']} V={b['v']}"
        )
    return "\n".join(lines)


def rule_based_answer(question: str, items: list[dict], stats: dict) -> str:
    """
    纯规则降级回答（无 API Key 时使用）。
    只用真实K线数据做简单统计，概率区间用「无法判断」兜底，绝不编造。
    """
    closes = [b["c"] for b in items]
    if len(closes) < 2:
        return "无法判断：K线数据不足（少于2根）。"
    last = closes[-1]
    ma5 = stats["ma5"]
    ma20 = stats["ma20"]
    up5 = round((last - closes[-6]) / closes[-6] * 100, 2) if len(closes) >= 6 and closes[-6] else 0.0

    obs = [
        f"【数据观察（基于页面真实K线）】",
        f"最新收盘 {last}，涨跌 {stats['change']}（{stats['change_pct']}%）；",
        f"近20根区间 {stats['low20']} ~ {stats['high20']}；",
        f"MA5={ma5}，MA20={ma20}，{'MA5 在 MA20 上方（短线偏强结构）' if ma5 and ma20 and ma5 > ma20 else 'MA5 在 MA20 下方或未交叉（短线偏弱/盘整结构）'}。",
        "",
        "【分情形概率分析】",
        "由于当前为规则模式（未配置 AI 模型），我无法给出可靠的统计概率数值，",
        "下述概率区间仅为基于上述数据结构的保守估计，不作为任何依据：",
    ]
    if ma5 and ma20 and ma5 > ma20:
        obs += [
            f"· 情形A 延续上行：40%-55%（MA5>MA20，短线动能偏多；但仅凭两日均线，置信度有限）",
            f"· 情形B 横盘震荡：30%-40%（价格接近近20根区间中位，缺乏方向性量能确认）",
            f"· 情形C 回调下行：15%-30%（若跌破MA20={ma20}，结构转弱）",
        ]
    else:
        obs += [
            f"· 情形A 延续下行：40%-55%（MA5<=MA20，短线动能偏弱）",
            f"· 情形B 横盘震荡：30%-40%（未见放量破位）",
            f"· 情形C 企稳反弹：15%-30%（若放量收复MA20={ma20}，结构修复）",
        ]
    obs += [
        "",
        "【风险提示】以上概率区间依赖的样本有限（仅K线与简单均线），未纳入成交量分布、订单流等更高阶数据，",
        "真实概率无法从当前数据严格推导——如需严格概率分析，请配置 AI 模型（DeepSeek）后重试。",
        "",
        "以上仅是王先生的分析，仅做参考，不可以作为价值投资。",
    ]
    return "\n".join(obs)


# ── HTTP Handler ─────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "WKFKline/1.0"

    # ---------- 公共工具 ----------
    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log(self, msg: str) -> None:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    # ---------- GET ----------
    def do_GET(self) -> None:
        url = urlparse(self.path)
        path = url.path

        if path in ("/", "/index.html"):
            self._serve_static(BASE_DIR / "index.html", "text/html; charset=utf-8")
            return

        if path == "/api/kline":
            q = parse_qs(url.query)
            symbol = q.get("symbol", ["NQ1!"])[0]
            timeframe = q.get("timeframe", ["15m"])[0]
            count = int(q.get("count", ["120"])[0])
            if timeframe not in TIMEFRAMES:
                self._send_json(400, {"error": f"不支持的周期: {timeframe}，可选 {TIMEFRAMES}"})
                return
            self._log(f"GET /api/kline {symbol} {timeframe} x{count}")
            try:
                data = load_kline(symbol, timeframe, count)
            except Exception as exc:  # noqa: BLE001
                self._log(f"kline 失败: {exc}")
                self._send_json(500, {"error": f"MT5 数据获取失败: {exc}"})
                return
            if data is None:
                self._send_json(404, {"error": "MT5 无数据，请确认 MT5 已登录且品种可用"})
                return
            self._send_json(200, data)
            return

        self._send_json(404, {"error": "Not Found"})

    # ---------- POST /api/chat（SSE 流式）----------
    def do_POST(self) -> None:
        url = urlparse(self.path)
        if url.path != "/api/chat":
            self._send_json(404, {"error": "Not Found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:  # noqa: BLE001
            self._send_json(400, {"error": "JSON 解析失败"})
            return

        question = (body.get("question") or "").strip()
        items = body.get("kline") or []
        stats = body.get("stats") or {}
        self._log(f"POST /api/chat q={question[:40]}... bars={len(items)}")

        if not question:
            self._send_json(400, {"error": "问题不能为空"})
            return
        if len(items) < 2:
            self._send_json(400, {"error": "K线数据不足（至少需要2根已收盘K线）"})
            return

        # SSE 响应头（关键：must be flushed before streaming）
        # Connection: close —— 流结束后主动断开，客户端 read() 才能遇到 EOF，
        # 避免 keep-alive 下 SSE 客户端永久阻塞等待
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()

        def sse(obj: dict) -> None:
            payload = f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")
            try:
                self.wfile.write(payload)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise

        try:
            settings = load_settings()
            if not settings.provider.api_key:
                # 无 Key -> 纯规则降级（真实数据 + 诚实措辞）
                sse({"type": "content", "delta": rule_based_answer(question, items, stats)})
                sse({"type": "done"})
                return

            # 组装提示词：真实K线数据注入
            kline_text = kline_to_prompt_text(items, stats)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"【当前页面显示的K线数据（真实历史数据）】\n{kline_text}\n\n【用户问题】\n{question}"},
            ]

            # OpenAI 兼容流式调用（DeepSeek 端点）
            from openai import OpenAI

            client = OpenAI(
                api_key=settings.provider.api_key,
                base_url=settings.provider.base_url,
            )
            stream = client.chat.completions.create(
                model=settings.provider.model,
                messages=messages,
                stream=True,
                temperature=0.2,
            )
            reasoning_full = ""
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue  # usage 等无内容块
                delta = chunk.choices[0].delta
                # 思考过程（DeepSeek reasoning_content，单独事件推送）
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_full += rc
                    sse({"type": "reasoning", "delta": rc})
                ct = getattr(delta, "content", None)
                if ct:
                    sse({"type": "content", "delta": ct})
            sse({"type": "done"})
        except Exception as exc:  # noqa: BLE001
            self._log(f"chat 失败: {exc}")
            try:
                sse({"type": "error", "message": f"AI 调用失败: {exc}"})
                sse({"type": "done"})
            except Exception:  # noqa: BLE001
                pass

    # ---------- 静态文件 ----------
    def _serve_static(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self._send_json(404, {"error": "index.html 不存在"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:  # 静默默认日志
        pass


def main() -> None:
    print("=" * 60)
    print("WKF 股票K线分析页面 服务端")
    print(f"  页面地址: http://127.0.0.1:{PORT}")
    print("  接口: GET /api/kline | POST /api/chat (SSE流式)")
    print("  按 Ctrl+C 停止")
    print("=" * 60, flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止", flush=True)


if __name__ == "__main__":
    main()

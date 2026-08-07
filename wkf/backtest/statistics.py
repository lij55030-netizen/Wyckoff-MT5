"""轻量化回测推演统计（P1 真实胜率，零依赖只读）。

【改动点】废弃"高概率信号数量占比"伪胜率计算，改为基于历史K线向后推演：
  1. 每笔信号记录入场收盘价与方向（long/short），存档含 ts_open 用于对齐K线；
  2. 向后推演固定根数K线（lookahead，默认10，可配置5/10/15），
     记录最大浮盈 / 最大浮亏 / 末端盈亏；
  3. 多头：后续价格突破入场价 → 盈利；触及预设止损 → 亏损；空头反之；
  4. 输出：真实交易胜率 / 整体盈亏比 / 最大连续亏损 / 净值曲线 / 逐笔明细导出。

仅做历史信号复盘统计，禁止修改历史分析结论；不含实盘撮合与资金曲线之外的交易行为。
【涉及文件】wkf/backtest/statistics.py + wkf/backtest/archive.py + wkf/gui/widgets/backtest_panel.py
【验证方式】tests/test_backtest.py 构造含 ts_open 的样本存档 + 样本K线 →
            手算胜率/盈亏比/连亏/净值一致。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field


@dataclass
class TradeResult:
    """单笔信号推演结果（盈亏百分比口径，与品种价格量级无关）。"""

    symbol: str
    timeframe: str
    analysis_time: str
    direction: str            # long / short
    entry_price: float
    entry_ts_open: int
    stop_price: float
    max_favorable: float      # 最大浮盈 %
    max_adverse: float        # 最大浮亏 %（负数）
    end_pnl: float            # 窗口末端相对入场 %
    pnl: float                # 最终盈亏 %（按平仓规则）
    outcome: str              # win / loss / flat
    exit_reason: str          # 触及止损 / 突破入场价 / 跌破入场价 / 窗口结束
    lookahead: int


@dataclass
class BacktestSummary:
    total_records: int = 0
    evaluated_trades: int = 0     # 完成推演的 long/short 单数
    wins: int = 0
    losses: int = 0
    flats: int = 0
    skipped: int = 0
    win_rate: float = 0.0         # 真实胜率 = wins / (wins + losses)
    avg_win: float = 0.0          # 平均盈利 %
    avg_loss: float = 0.0         # 平均亏损 %（负数）
    profit_factor: float = 0.0    # 整体盈亏比 = 平均盈利 / |平均亏损|
    max_consecutive_losses: int = 0
    total_pnl: float = 0.0        # 累计盈亏 %
    equity_curve: list[float] = field(default_factory=list)  # 累计净值序列（%）
    trades: list[TradeResult] = field(default_factory=list)
    by_symbol: dict[str, int] = field(default_factory=dict)
    by_timeframe: dict[str, int] = field(default_factory=dict)
    by_direction: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _locate_signal_index(bars, ts_open: int) -> int:
    """在 K 线（新→旧）中定位信号触发 bar 的索引；找不到返回 -1。"""
    for i, b in enumerate(bars):
        if int(b.ts_open) == int(ts_open):
            return i
    return -1


def simulate_trade(
    record: dict,
    bars,
    *,
    lookahead: int = 10,
    stop_pct: float = 0.005,
) -> TradeResult | None:
    """对单条存档记录做固定周期K线推演（纯函数，可复现）。

    record 需含 ts_open / entry_price（或 price）/ direction（或 bias）。
    bars: KlineBar 列表（新→旧）。无法对齐或方向非多空时返回 None。
    """
    symbol = str(record.get("symbol", "?"))
    timeframe = str(record.get("timeframe", "?"))
    analysis_time = str(record.get("analysis_time", ""))
    direction = str(record.get("direction") or record.get("bias") or "neutral")
    raw_entry = record.get("entry_price", record.get("price"))
    ts_open = record.get("ts_open")

    if direction not in ("long", "short") or raw_entry is None or not ts_open:
        return None
    entry = float(raw_entry)
    if entry <= 0 or not bars:
        return None

    idx = _locate_signal_index(bars, int(ts_open))
    if idx < 0 or idx + 1 >= len(bars):
        return None

    window = bars[idx + 1: idx + 1 + lookahead]
    if not window:
        return None

    stop_price = entry * (1 - stop_pct) if direction == "long" else entry * (1 + stop_pct)

    # 最大浮盈 / 最大浮亏（%）
    max_favorable = 0.0
    max_adverse = 0.0
    for b in window:
        if direction == "long":
            fav = (b.high - entry) / entry * 100.0
            adv = (b.low - entry) / entry * 100.0
        else:
            fav = (entry - b.low) / entry * 100.0
            adv = (entry - b.high) / entry * 100.0
        max_favorable = max(max_favorable, fav)
        max_adverse = min(max_adverse, adv)

    # 平仓规则：止损优先 → 突破入场价确认 → 否则窗口结束
    outcome, exit_price, exit_reason = "flat", window[-1].close, "窗口结束"
    for b in window:
        if direction == "long" and b.low <= stop_price:
            outcome, exit_price, exit_reason = "loss", stop_price, "触及止损"
            break
        if direction == "short" and b.high >= stop_price:
            outcome, exit_price, exit_reason = "loss", stop_price, "触及止损"
            break
        if direction == "long" and b.high >= entry:
            outcome, exit_price, exit_reason = "win", b.close, "突破入场价"
            break
        if direction == "short" and b.low <= entry:
            outcome, exit_price, exit_reason = "win", b.close, "跌破入场价"
            break

    if direction == "long":
        pnl = (exit_price - entry) / entry * 100.0
        end_pnl = (window[-1].close - entry) / entry * 100.0
    else:
        pnl = (entry - exit_price) / entry * 100.0
        end_pnl = (entry - window[-1].close) / entry * 100.0

    return TradeResult(
        symbol=symbol,
        timeframe=timeframe,
        analysis_time=analysis_time,
        direction=direction,
        entry_price=round(entry, 4),
        entry_ts_open=int(ts_open),
        stop_price=round(stop_price, 4),
        max_favorable=round(max_favorable, 4),
        max_adverse=round(max_adverse, 4),
        end_pnl=round(end_pnl, 4),
        pnl=round(pnl, 4),
        outcome=outcome,
        exit_reason=exit_reason,
        lookahead=lookahead,
    )


def _fetch_bars(symbol: str, timeframe: str, n_bars: int = 800) -> list:
    """按当前数据源拉取历史K线（只读，供回测对齐推演）。"""
    from wkf.data.datasource import get_data_source

    return get_data_source().fetch_bars(symbol, timeframe, n_bars)


def compute_backtest(
    records: list[dict],
    *,
    lookahead: int = 10,
    stop_pct: float = 0.005,
    bars_map: dict | None = None,
) -> BacktestSummary:
    """按历史K线推演每笔信号，统计真实胜率/盈亏比/最大连亏/净值曲线。

    records: 存档记录列表（含 ts_open/entry_price/direction）。
    lookahead: 向后推演K线根数（可配置 5/10/15）。
    stop_pct: 预设止损比例（默认 0.5%），触及即判定亏损。
    bars_map: {(symbol, timeframe): bars} 可选注入（测试/离线）；缺省时按需拉取。
    """
    s = BacktestSummary()
    s.total_records = len(records)
    cache: dict = dict(bars_map or {})
    streak = 0
    # 按分析时间排序，保证连亏/净值曲线顺序正确
    ordered = sorted(records, key=lambda r: str(r.get("analysis_time", "")))

    for r in ordered:
        symbol = str(r.get("symbol", "?"))
        timeframe = str(r.get("timeframe", "?"))
        key = (symbol, timeframe)
        if key not in cache:
            try:
                cache[key] = _fetch_bars(symbol, timeframe)
            except Exception as exc:
                cache[key] = []
                s.errors.append(f"{symbol} {timeframe} K线获取失败: {exc}")

        tr = simulate_trade(r, cache[key], lookahead=lookahead, stop_pct=stop_pct)
        if tr is None:
            s.skipped += 1
            continue

        s.trades.append(tr)
        s.by_symbol[symbol] = s.by_symbol.get(symbol, 0) + 1
        s.by_timeframe[timeframe] = s.by_timeframe.get(timeframe, 0) + 1
        s.by_direction[tr.direction] = s.by_direction.get(tr.direction, 0) + 1

        if tr.outcome == "win":
            s.wins += 1
            streak = 0
        elif tr.outcome == "loss":
            s.losses += 1
            streak += 1
            s.max_consecutive_losses = max(s.max_consecutive_losses, streak)
        elif tr.outcome == "flat":
            s.flats += 1
        else:
            s.skipped += 1

    s.evaluated_trades = s.wins + s.losses + s.flats
    if s.wins + s.losses > 0:
        s.win_rate = round(s.wins / (s.wins + s.losses) * 100.0, 2)

    win_pnls = [t.pnl for t in s.trades if t.outcome == "win"]
    loss_pnls = [t.pnl for t in s.trades if t.outcome == "loss"]
    if win_pnls:
        s.avg_win = round(sum(win_pnls) / len(win_pnls), 4)
    if loss_pnls:
        s.avg_loss = round(sum(loss_pnls) / len(loss_pnls), 4)
    if loss_pnls and s.avg_win > 0 and s.avg_loss < 0:
        s.profit_factor = round(s.avg_win / abs(s.avg_loss), 2)

    cum = 0.0
    for t in s.trades:
        if t.outcome in ("win", "loss", "flat"):
            cum += t.pnl
            s.equity_curve.append(round(cum, 4))
    if s.equity_curve:
        s.total_pnl = round(s.equity_curve[-1], 4)

    return s


def export_trades(trades: list[TradeResult], path: str) -> int:
    """逐笔交易明细导出 CSV（供复盘核验）。返回导出条数。"""
    fieldnames = [
        "symbol", "timeframe", "analysis_time", "direction", "entry_price",
        "stop_price", "max_favorable", "max_adverse", "end_pnl", "pnl",
        "outcome", "exit_reason", "lookahead",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in trades:
            writer.writerow({k: getattr(t, k) for k in fieldnames})
    return len(trades)


def render_summary_text(s: BacktestSummary) -> str:
    """渲染回测推演统计为文本（供 GUI 表格/日志展示）。"""
    lines = [
        "=== WKF 回测推演统计（真实胜率）===",
        f"存档信号总数: {s.total_records}　|　可推演: {s.evaluated_trades}　|　跳过: {s.skipped}",
        f"真实交易胜率: {s.win_rate}% （赢 {s.wins} / 输 {s.losses} / 平 {s.flats}）",
        f"整体盈亏比: {s.profit_factor} （平均盈利 +{s.avg_win}% / 平均亏损 {s.avg_loss}%）",
        f"最大连续亏损: {s.max_consecutive_losses} 笔",
        f"累计净值: {s.total_pnl:+.2f}%",
        "",
        "── 净值曲线（累计盈亏%）──",
        " → ".join(f"{v:+.2f}" for v in s.equity_curve[:40])
        + (" ..." if len(s.equity_curve) > 40 else ""),
        "",
        "── 按品种 ──",
        *[f"{k}: {v}" for k, v in sorted(s.by_symbol.items())],
        "",
        "── 按周期 ──",
        *[f"{k}: {v}" for k, v in sorted(s.by_timeframe.items())],
        "",
        "── 按方向 ──",
        *[f"{k}: {v}" for k, v in sorted(s.by_direction.items())],
        "",
        "⚠ 仅历史信号复盘推演，不构成投资建议；推演按固定止损比例与突破入场价规则模拟，非实盘成交。",
    ]
    if s.errors:
        lines.append("")
        lines.append("── 数据获取告警 ──")
        lines.extend(f"· {e}" for e in s.errors[:5])
    return "\n".join(lines)

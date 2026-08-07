"""WKF 命令行入口。

用法:
    python cli.py NQ 15m
    python cli.py ES 1h
    python cli.py XAU 15m --no-ai
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SYMBOL_ALIAS = {
    "NQ": "NQ1!", "ES": "ES1!", "GC": "GC1!",
    "XAU": "GC1!", "GOLD": "GC1!", "纳斯达克": "NQ1!", "标普": "ES1!", "黄金": "GC1!",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="WKF 威科夫交易分析")
    parser.add_argument("symbol", help="品种: NQ / ES / GC(XAU)")
    parser.add_argument("timeframe", nargs="?", default="15m",
                        help="周期: 5m/10m/15m/30m/1h (默认 15m)")
    parser.add_argument("--bars", type=int, default=100, help="K线数量 (默认 100)")
    parser.add_argument("--no-ai", action="store_true", help="跳过 AI 诊断")
    args = parser.parse_args()

    symbol = SYMBOL_ALIAS.get(args.symbol.upper(), args.symbol.upper())
    if not symbol.endswith("1!"):
        symbol = f"{symbol}1!"

    from wkf.orchestrator.runner import run_analysis

    print(f"⏳ 分析 {symbol} {args.timeframe} ...", file=sys.stderr)
    res = run_analysis(
        symbol,
        args.timeframe,
        bar_count=args.bars,
        with_ai=not args.no_ai,
    )
    print(res.to_report())
    print()
    print("步骤: " + " → ".join(res.steps) if res.steps else "")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse

from rich.table import Table

from .optimize_amb_vs_baseline import run_tournament
from .report import console


def _print_top(rows: list[dict], top_n: int) -> None:
    top = rows[:top_n]
    if not top:
        console.print("[yellow]No valid results.[/yellow]")
        return

    t = Table(title=f"[bold cyan]AMB vs Baseline Top {len(top)}[/bold cyan]", show_lines=False)
    t.add_column("#", width=3)
    t.add_column("Pass", width=5)
    t.add_column("Beat", width=6)
    t.add_column("MinCal", width=8, justify="right")
    t.add_column("AvgCal", width=8, justify="right")
    t.add_column("WorstDD", width=8, justify="right")
    t.add_column("Slow", width=6, justify="right")
    t.add_column("Fast", width=6, justify="right")
    t.add_column("L", width=4, justify="right")
    t.add_column("S", width=4, justify="right")
    t.add_column("SL", width=4, justify="right")

    for i, r in enumerate(top, 1):
        t.add_row(
            str(i),
            "Y" if r["hard_pass"] else "N",
            f"{r['beat_both_count']}/{r['n_periods']}",
            f"{r['min_calmar']:.3f}",
            f"{r['mean_calmar']:.3f}",
            f"{r['worst_dd']:.2f}",
            str(r["slow_ma_len"]),
            str(r["fast_ma_len"]),
            f"{r['leverage_long']}",
            f"{r['leverage_short']}",
            f"{r['sl_risk_pct']}",
        )
    console.print(t)


def main() -> None:
    parser = argparse.ArgumentParser(description="AMB tournament vs baseline defaults")
    parser.add_argument("--ticker", default="BTC-USD")
    parser.add_argument("--source", default="bybit", choices=["yfinance", "bybit"])
    parser.add_argument(
        "--mode",
        default="btc_quick",
        choices=["quick", "full", "btc_quick", "btc_full", "equity_quick", "equity_full", "atr_quick", "atr_full"],
    )
    parser.add_argument("--min-trades", type=int, default=8)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--max-combos", type=int, default=0, help="0 = all")
    parser.add_argument("--periods", default="", help="Optional comma-separated period names")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    periods = [p.strip() for p in args.periods.split(",") if p.strip()] if args.periods else None
    max_combos = None if args.max_combos <= 0 else args.max_combos

    console.print(
        f"\n[bold]AMB vs Baseline Tournament[/bold] "
        f"[cyan]{args.ticker}[/cyan] [magenta]{args.source}[/magenta] mode={args.mode}"
    )

    rows, csv_path = run_tournament(
        ticker=args.ticker,
        source=args.source,
        mode=args.mode,
        periods=periods,
        min_trades=args.min_trades,
        refresh=args.refresh,
        max_combos=max_combos,
    )
    _print_top(rows, args.top)
    console.print(f"\n[dim]Saved: {csv_path}[/dim]")


if __name__ == "__main__":
    main()

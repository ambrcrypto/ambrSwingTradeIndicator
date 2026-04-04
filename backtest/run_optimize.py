"""
run_optimize.py – Grid search optimization entry point.

Usage examples:
    # Quick run: BTC, all available periods, sort by Calmar
    python -m backtest.run_optimize --ticker BTC-USD

    # All tickers, specific period
    python -m backtest.run_optimize --ticker all --period 2021_default

    # Full grid, show top 20
    python -m backtest.run_optimize --ticker BTC-USD --mode full --top 20

    # Cross-period robustness check on best params
    python -m backtest.run_optimize --ticker BTC-USD --period 2021_default --cross-check

    # Sort by P/L instead of Calmar
    python -m backtest.run_optimize --ticker BTC-USD --sort pl_pct
"""

import argparse
import json
from pathlib import Path
from rich.console import Console

from .data import get_periods, TICKER_MAP
from .strategy_amb import AMBParams
from .strategy_amb import run_strategy
from .engine import compute_metrics
from .optimize import run_period, run_all, cross_period_check, GRIDS
from .montecarlo import run_montecarlo
from .report import (
    console,
    print_top_results,
    print_cross_period,
    print_montecarlo,
    print_best_summary,
)

ALL_TICKERS = ["BTC-USD", "ETH-USD", "VOO"]


def main() -> None:
    parser = argparse.ArgumentParser(description="AMB grid search optimizer")
    parser.add_argument("--ticker",  default="BTC-USD",
                        help=f"Ticker or 'all'. Known: {ALL_TICKERS}")
    parser.add_argument("--period",  default=None,
                        help="Period name or 'all' (default). E.g. 2021_default")
    parser.add_argument("--mode",    default="quick",
                        choices=["quick", "full", "equity_quick", "equity_full"],
                        help="Grid size: quick/full (crypto) or equity_quick/equity_full (ETFs/stocks)")
    parser.add_argument("--sort",    default="calmar",
                        choices=["calmar", "pl_pct", "ann_return", "sharpe_trade"],
                        help="Primary ranking metric")
    parser.add_argument("--top",     type=int, default=15,
                        help="Show top N results per period")
    parser.add_argument("--min-trades", type=int, default=5,
                        help="Minimum trades to include result")
    parser.add_argument("--cross-check", action="store_true",
                        help="After optimization, test best params across all periods")
    parser.add_argument("--mc",      type=int, default=500,
                        help="Monte Carlo sims on best result (0 = skip)")
    parser.add_argument("--refresh", action="store_true",
                        help="Force data re-download")
    args = parser.parse_args()

    # ── Resolve tickers ───────────────────────────────────────────────────
    tickers = ALL_TICKERS if args.ticker == "all" else [args.ticker]

    # ── Resolve periods ───────────────────────────────────────────────────
    periods = None if (args.period is None or args.period == "all") else [args.period]

    # ── Grid size info ────────────────────────────────────────────────────
    g = GRIDS[args.mode]
    n_slow  = len(g["slow_ma_len"])
    n_fast  = len(g["fast_ma_len"])
    n_sl    = len(g["sl_configs"])
    n_lev   = len(g["leverage_long"]) * len(g["leverage_short"])
    n_shrt  = len(g["allow_shorts"])
    n_fma   = len(g.get("use_fast_ma", [True]))
    n_tf    = len(g.get("signal_tf",   ["D"]))
    approx  = n_slow * n_fast * n_sl * n_lev * n_shrt * n_fma * n_tf
    console.print(
        f"\n[bold cyan]AMB Optimizer[/bold cyan]  "
        f"mode=[yellow]{args.mode}[/yellow]  "
        f"sort=[yellow]{args.sort}[/yellow]  "
        f"~[yellow]{approx}[/yellow] combos/period (before fast>=slow filter)"
    )

    # ── Run ───────────────────────────────────────────────────────────────
    if args.ticker == "all" or periods is None:
        # Multi-ticker / multi-period run
        all_results = run_all(
            tickers     = tickers,
            periods     = periods,
            mode        = args.mode,
            min_trades  = args.min_trades,
            sort_by     = args.sort,
            top_n       = args.top,
        )
        print_best_summary(all_results, sort_by=args.sort)

        # Detailed tables per ticker/period
        for ticker, period_results in all_results.items():
            for pname, rows in period_results.items():
                if rows:
                    print_top_results(rows, ticker, pname, top_n=args.top, sort_by=args.sort)

    else:
        # Single ticker + period
        ticker = tickers[0]
        pname  = periods[0]
        avail  = get_periods(ticker)
        if pname not in avail:
            console.print(f"[red]Period '{pname}' not available for {ticker}[/red]")
            console.print(f"Available: {list(avail.keys())}")
            return
        start, end = avail[pname]

        rows = run_period(
            ticker      = ticker,
            period_name = pname,
            start       = start,
            end         = end,
            mode        = args.mode,
            min_trades  = args.min_trades,
            sort_by     = args.sort,
        )
        print_top_results(rows, ticker, pname, top_n=args.top, sort_by=args.sort)

        # ── Cross-period check on best params ─────────────────────────────
        if args.cross_check and rows:
            best_row = rows[0]
            best_params = AMBParams(
                slow_ma_len    = int(best_row["slow_ma_len"]),
                slow_ma_type   = best_row["slow_ma_type"],
                fast_ma_len    = int(best_row["fast_ma_len"]),
                fast_ma_type   = best_row["fast_ma_type"],
                use_fast_ma    = best_row.get("use_fast_ma", True) in (True, "True"),
                allow_longs    = best_row["allow_longs"] in (True, "True"),
                allow_shorts   = best_row["allow_shorts"] in (True, "True"),
                leverage_long  = float(best_row["leverage_long"]),
                leverage_short = float(best_row["leverage_short"]),
                sl_enable      = best_row["sl_enable"] in (True, "True"),
                sl_risk_pct    = float(best_row["sl_risk_pct"]),
            )
            console.print(
                f"\n[bold]Cross-Period Check[/bold]  "
                f"[dim]Best params from {pname} tested on all periods[/dim]"
            )
            cross = cross_period_check(ticker, best_params)
            print_cross_period(cross, ticker, best_params)

        # ── Monte Carlo on best params ────────────────────────────────────
        if args.mc > 0 and rows:
            best_row = rows[0]
            best_params = AMBParams(
                slow_ma_len    = int(best_row["slow_ma_len"]),
                slow_ma_type   = best_row["slow_ma_type"],
                fast_ma_len    = int(best_row["fast_ma_len"]),
                fast_ma_type   = best_row["fast_ma_type"],
                use_fast_ma    = best_row.get("use_fast_ma", True) in (True, "True"),
                allow_longs    = best_row["allow_longs"] in (True, "True"),
                allow_shorts   = best_row["allow_shorts"] in (True, "True"),
                leverage_long  = float(best_row["leverage_long"]),
                leverage_short = float(best_row["leverage_short"]),
                sl_enable      = best_row["sl_enable"] in (True, "True"),
                sl_risk_pct    = float(best_row["sl_risk_pct"]),
            )
            from .data import get_slice
            import pandas as pd
            df     = get_slice(ticker, start, end, warmup=True)
            trades = run_strategy(df, best_params,
                                  trade_start=pd.Timestamp(start) if start else None)
            if len(trades) >= 5:
                mc = run_montecarlo(trades, best_params, n_simulations=args.mc)
                print_montecarlo(mc, ticker, best_params)

    console.print(
        f"\n[dim]Results saved to: backtest/results/[/dim]\n"
        f"[dim]Best params JSON: backtest/results/best_*.json[/dim]"
    )


if __name__ == "__main__":
    main()

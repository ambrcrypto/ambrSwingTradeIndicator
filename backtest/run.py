"""
run.py – Single backtest run with full output.

Usage examples:
    python -m backtest.run --ticker BTC-USD --period 2021_default
    python -m backtest.run --ticker BTC-USD --period 2021_default \
        --slow 130 --fast 44 --llong 3.0 --lshort 1.25 --sl 9
    python -m backtest.run --ticker ETH-USD --period bear_2022 \
        --slow 130 --fast 44 --llong 3.0 --lshort 1.25 --no-shorts
"""

import argparse
from .data import get_slice, get_periods
from .strategy_amb import AMBParams, run_strategy
from .engine import compute_metrics
from .montecarlo import run_montecarlo
from .report import console, print_trades, print_metrics, print_montecarlo


def main() -> None:
    parser = argparse.ArgumentParser(description="AMB single backtest run")
    parser.add_argument("--ticker",   default="BTC-USD", help="Ticker symbol")
    parser.add_argument("--period",   default="2021_default",
                        help="Period name or 'custom'")
    parser.add_argument("--start",    default=None, help="Custom start YYYY-MM-DD")
    parser.add_argument("--end",      default=None, help="Custom end   YYYY-MM-DD")
    parser.add_argument("--slow",     type=int,   default=130,  help="Slow MA length")
    parser.add_argument("--slow-type",default="SMA", choices=["SMA","EMA"])
    parser.add_argument("--fast",     type=int,   default=44,   help="Fast MA length")
    parser.add_argument("--fast-type",default="SMA", choices=["SMA","EMA"])
    parser.add_argument("--llong",    type=float, default=3.0,  help="Leverage Long")
    parser.add_argument("--lshort",   type=float, default=1.25, help="Leverage Short")
    parser.add_argument("--sl",       type=float, default=None,
                        help="SL risk % (omit = SL off)")
    parser.add_argument("--no-shorts",action="store_true", help="Disable short trades")
    parser.add_argument("--capital",  type=float, default=1000.0)
    parser.add_argument("--mc",       type=int,   default=1000,
                        help="Monte Carlo simulations (0 = skip)")
    parser.add_argument("--trades",   action="store_true", help="Show trade list")
    parser.add_argument("--refresh",  action="store_true", help="Force data refresh")
    args = parser.parse_args()

    # ── Resolve date range ────────────────────────────────────────────────
    if args.period == "custom":
        start = args.start
        end   = args.end
    else:
        periods = get_periods(args.ticker)
        if args.period not in periods:
            available = list(periods.keys())
            print(f"Period '{args.period}' not found. Available: {available}")
            return
        start, end = periods[args.period]

    # ── Build params ──────────────────────────────────────────────────────
    params = AMBParams(
        slow_ma_len    = args.slow,
        slow_ma_type   = args.slow_type,
        fast_ma_len    = args.fast,
        fast_ma_type   = args.fast_type,
        allow_longs    = True,
        allow_shorts   = not args.no_shorts,
        leverage_long  = args.llong,
        leverage_short = args.lshort,
        sl_enable      = args.sl is not None,
        sl_risk_pct    = args.sl if args.sl else 2.0,
        start_capital  = args.capital,
    )

    # ── Load data ─────────────────────────────────────────────────────────
    df = get_slice(args.ticker, start, end, force_refresh=args.refresh)
    console.print(
        f"\n[bold]AMB Backtest[/bold]  "
        f"[cyan]{args.ticker}[/cyan]  "
        f"[yellow]{args.period}[/yellow]  "
        f"{start} → {end}  ({len(df)} bars)"
    )
    console.print(f"  Params: [dim]{params.label()}[/dim]")

    # ── Run strategy ──────────────────────────────────────────────────────
    trades  = run_strategy(df, params)
    metrics = compute_metrics(trades, params, start, end)

    # ── Output ───────────────────────────────────────────────────────────
    if args.trades:
        print_trades(trades, params, args.ticker, args.period)

    print_metrics(metrics, args.ticker, args.period)

    if args.mc > 0 and len(trades) >= 5:
        mc = run_montecarlo(trades, params, n_simulations=args.mc)
        print_montecarlo(mc, args.ticker, params)


if __name__ == "__main__":
    main()

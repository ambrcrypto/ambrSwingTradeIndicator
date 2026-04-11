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
import pandas as pd
from .data import get_slice, get_periods
from .strategy_amb import AMBParams, run_strategy
from .engine import compute_metrics
from .montecarlo import run_montecarlo
from .report import console, print_trades, print_metrics, print_montecarlo
from .ticker_config import get_ticker_params


def main() -> None:
    parser = argparse.ArgumentParser(description="AMB single backtest run")
    parser.add_argument("--ticker",   default="BTC-USD", help="Ticker symbol")
    parser.add_argument("--source",   default="yfinance", choices=["yfinance", "bybit"],
                        help="Data source")
    parser.add_argument("--period",   default="2021_default",
                        help="Period name or 'custom'")
    parser.add_argument("--start",    default=None, help="Custom start YYYY-MM-DD")
    parser.add_argument("--end",      default=None, help="Custom end   YYYY-MM-DD")
    # Params – default=None means "use ticker config default"
    parser.add_argument("--slow",     type=int,   default=None, help="Slow MA length")
    parser.add_argument("--slow-type",default=None, choices=["SMA","EMA"])
    parser.add_argument("--fast",     type=int,   default=None, help="Fast MA length")
    parser.add_argument("--fast-type",default=None, choices=["SMA","EMA"])
    parser.add_argument("--llong",    type=float, default=None, help="Leverage Long")
    parser.add_argument("--lshort",   type=float, default=None, help="Leverage Short")
    parser.add_argument("--sl",       type=float, default=None,
                        help="SL risk %% (0 = SL off, omit = use ticker config)")
    parser.add_argument("--signal-tf",default=None, choices=["D","W","M"],
                        help="Signal timeframe: D=daily W=weekly M=monthly")
    parser.add_argument("--no-shorts",action="store_true", help="Disable short trades")
    parser.add_argument("--no-fast-ma",action="store_true",
                        help="Disable Fast MA: Slow MA only (no re-entry, no fast-exit)")
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
        periods = get_periods(args.ticker, source=args.source)
        if args.period not in periods:
            available = list(periods.keys())
            print(f"Period '{args.period}' not found. Available: {available}")
            return
        start, end = periods[args.period]

    # ── Build params: ticker config as base, CLI overrides on top ────────
    base = get_ticker_params(args.ticker)

    # SL: explicit --sl 0 turns off, --sl N sets risk%, omit = use config
    if args.sl is None:
        sl_enable  = base.sl_enable
        sl_risk    = base.sl_risk_pct
    elif args.sl == 0:
        sl_enable  = False
        sl_risk    = base.sl_risk_pct
    else:
        sl_enable  = True
        sl_risk    = args.sl

    params = AMBParams(
        slow_ma_len    = args.slow      if args.slow      is not None else base.slow_ma_len,
        slow_ma_type   = args.slow_type if args.slow_type is not None else base.slow_ma_type,
        fast_ma_len    = args.fast      if args.fast      is not None else base.fast_ma_len,
        fast_ma_type   = args.fast_type if args.fast_type is not None else base.fast_ma_type,
        use_fast_ma    = False if args.no_fast_ma else base.use_fast_ma,
        allow_longs    = True,
        allow_shorts   = not args.no_shorts,
        leverage_long  = args.llong     if args.llong     is not None else base.leverage_long,
        leverage_short = args.lshort    if args.lshort    is not None else base.leverage_short,
        sl_enable      = sl_enable,
        sl_risk_pct    = sl_risk,
        start_capital  = args.capital,
        signal_tf      = args.signal_tf if args.signal_tf is not None else base.signal_tf,
    )

    # ── Load data (full history for MA warmup; trades filtered by start) ──
    df = get_slice(args.ticker, start, end, force_refresh=args.refresh, warmup=True, source=args.source)
    n_window = len(df[df.index >= pd.Timestamp(start)]) if start else len(df)
    console.print(
        f"\n[bold]AMB Backtest[/bold]  "
        f"[cyan]{args.ticker}[/cyan]  "
        f"[magenta]{args.source}[/magenta]  "
        f"[yellow]{args.period}[/yellow]  "
        f"{start} -> {end}  ({n_window} bars)"
    )
    console.print(f"  Params: [dim]{params.label()}[/dim]")

    # ── Run strategy ──────────────────────────────────────────────────────
    trade_start = pd.Timestamp(start) if start else None
    trades  = run_strategy(df, params, trade_start=trade_start)
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

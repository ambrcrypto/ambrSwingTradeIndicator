"""
run_hmm_comparison.py – Baseline AMB vs. HMM-Enhanced AMB vs. Buy & Hold.

Computes a walk-forward HMM regime filter on the full BTC history (2021+)
and compares three strategies on identical data.

Usage:
    python -m backtest.run_hmm_comparison
    python -m backtest.run_hmm_comparison --source bybit --start 2021-01-01
    python -m backtest.run_hmm_comparison --source yfinance --show-trades
    python -m backtest.run_hmm_comparison --no-html      # console only

Output:
    • Console: regime diagnostics + side-by-side metrics table
    • HTML:    backtest/results/backtest_hmm_comparison.html
              (equity curves, regime overlay, monthly heatmaps)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# Windows cmd/PowerShell may use cp1252 – force UTF-8 so Unicode console
# output (arrows, tick marks, etc.) does not crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from .data         import get_slice
from .strategy_amb import AMBParams, Trade, run_strategy
from .engine       import compute_metrics
from .ticker_config import get_ticker_params
from .strategy_amb_hmm import (
    compute_hmm_regimes, run_strategy_hmm, HMMResult,
    BULL, SIDEWAYS, BEAR,
)

RESULTS_DIR = Path(__file__).parent / "results"


# ─────────────────────────────────────────────────────────────────────────────
# Equity curve builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_equity_curve(
    trades:        list[Trade],
    all_dates:     pd.DatetimeIndex,
    start_capital: float,
) -> pd.Series:
    """
    Build a daily equity curve from a list of closed trades.

    Capital changes at trade exit date.  Forward-filled between trades.
    Returns pd.Series with DatetimeIndex aligned to all_dates.
    """
    exit_caps: dict[pd.Timestamp, float] = {}
    cap = start_capital
    for t in sorted(trades, key=lambda x: x.exit_date):
        cap *= (1.0 + t.pct / 100.0)
        exit_caps[t.exit_date] = cap

    eq = pd.Series(np.nan, index=all_dates, name="equity", dtype=float)
    eq.iloc[0] = start_capital
    for date, c in exit_caps.items():
        if date in eq.index:
            eq[date] = c
    eq = eq.ffill()
    return eq


# ─────────────────────────────────────────────────────────────────────────────
# Monthly return heatmap builder
# ─────────────────────────────────────────────────────────────────────────────

def _monthly_returns(equity: pd.Series) -> pd.DataFrame:
    """
    Derive monthly return (%) from a daily equity curve.

    Returns a DataFrame with rows = year, columns = month (1-12).
    """
    monthly = equity.resample("ME").last().ffill()
    monthly_ret = monthly.pct_change() * 100.0
    df = monthly_ret.to_frame("ret")
    df["year"]  = df.index.year
    df["month"] = df.index.month
    pivot = df.pivot(index="year", columns="month", values="ret")
    # Ensure all 12 months are present
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = np.nan
    pivot = pivot[sorted(pivot.columns)]
    return pivot


# ─────────────────────────────────────────────────────────────────────────────
# Console output
# ─────────────────────────────────────────────────────────────────────────────

_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _print_metrics_table(results: dict[str, dict]) -> None:
    """Print side-by-side metrics for all variants."""
    labels   = list(results.keys())
    metrics  = [
        ("Trades",       "trades",        "d",   False),
        ("Total P/L %",  "pl_pct",        ".2f", False),
        ("Ann. Return %","ann_return",     ".2f", False),
        ("Max DD %",     "max_dd",        ".2f", True),
        ("Calmar",       "calmar",        ".3f", False),
        ("Win Rate %",   "win_rate",      ".2f", False),
        ("Expectancy %", "expectancy",    ".2f", False),
        ("Profit Factor","profit_factor", ".3f", False),
        ("Sharpe (trade)","sharpe_trade", ".3f", False),
        ("SL Hits",      "sl_hits",       "d",   True),
        ("SL Hit Rate %","sl_hit_rate",   ".1f", True),
        ("End Capital $","end_capital",   ".2f", False),
    ]

    # ── Header ────────────────────────────────────────────────────────────
    col_w = 22
    lbl_w = 20
    print("\n" + "═" * (lbl_w + col_w * len(labels)))
    print(f"  {'Metric':<{lbl_w}}", end="")
    for lbl in labels:
        print(f"  {lbl:>{col_w - 2}}", end="")
    print()
    print("─" * (lbl_w + col_w * len(labels)))

    for display, key, fmt, lower_better in metrics:
        print(f"  {display:<{lbl_w}}", end="")
        values = [r.get(key, 0) for r in results.values()]
        best = min(values) if lower_better else max(values)
        for v in values:
            mark = " *" if v == best and len(labels) > 1 else "  "
            if fmt == "d":
                cell = f"{v:>6d}"
            else:
                cell = f"{v:>{col_w - 4}{fmt}}"
            print(f"  {cell}{mark}", end="")
        print()

    print("═" * (lbl_w + col_w * len(labels)))
    print("  * = best value for that metric\n")


def _print_filtered_trades_summary(
    baseline_trades: list[Trade],
    hmm_trades:      list[Trade],
) -> None:
    """Show which baseline trades were filtered by HMM."""
    base_entries  = {t.entry_date for t in baseline_trades}
    hmm_entries   = {t.entry_date for t in hmm_trades}
    filtered_dates = sorted(base_entries - hmm_entries)

    if not filtered_dates:
        print("  HMM filter: no baseline trades were blocked.\n")
        return

    filtered_trades = [t for t in baseline_trades if t.entry_date in filtered_dates]
    n_filtered = len(filtered_trades)
    n_total    = len(baseline_trades)
    pl_filtered = sum(t.pct for t in filtered_trades)

    print(f"\n── HMM-Filtered Trades ({n_filtered}/{n_total} = "
          f"{n_filtered / n_total * 100:.1f}%) ────────────────────────────")
    print(f"  Cumulative P/L avoided: {pl_filtered:+.2f}%  "
          f"({'saved' if pl_filtered < 0 else 'missed'})")
    print(f"\n  {'Entry':12s} {'Exit':12s} {'Dir':5s} {'P/L%':>8s}  {'ExitType':10s}")
    print("  " + "-" * 58)
    for t in sorted(filtered_trades, key=lambda x: x.entry_date):
        dir_str = "Long" if t.direction == 1 else "Short"
        print(f"  {str(t.entry_date.date()):12s} {str(t.exit_date.date()):12s} "
              f"{dir_str:5s} {t.pct:+8.2f}%  {t.exit_type}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# HTML Dashboard
# ─────────────────────────────────────────────────────────────────────────────

def _build_html_dashboard(
    df:               pd.DataFrame,
    equity_baseline:  pd.Series,
    equity_hmm:       pd.Series,
    equity_bh:        pd.Series,
    hmm_result:       HMMResult,
    results:          dict[str, dict],
    trade_start:      pd.Timestamp,
    output_path:      Path,
) -> None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("  plotly not installed – skipping HTML dashboard.")
        print("  Install with:  pip install plotly")
        return

    # ── Slice data to trade window ─────────────────────────────────────────
    plot_df        = df.loc[df.index >= trade_start]
    plot_dates     = plot_df.index
    regime_window  = hmm_result.regimes[df.index >= trade_start]
    eq_base        = equity_baseline.loc[equity_baseline.index >= trade_start]
    eq_hmm         = equity_hmm.loc[equity_hmm.index >= trade_start]
    eq_bh          = equity_bh.loc[equity_bh.index >= trade_start]

    # ── Monthly return heatmaps ────────────────────────────────────────────
    mr_base = _monthly_returns(eq_base)
    mr_hmm  = _monthly_returns(eq_hmm)

    # ── Regime color bands ─────────────────────────────────────────────────
    _regime_colors = {
        BULL:     "rgba(0,200,100,0.15)",
        SIDEWAYS: "rgba(200,200,0,0.15)",
        BEAR:     "rgba(220,50,50,0.15)",
    }

    def _regime_shapes(dates: pd.DatetimeIndex, regimes: np.ndarray) -> list[dict]:
        """Build plotly shape list for regime background bands."""
        shapes = []
        prev_r = None
        band_start = None
        for dt, r in zip(dates, regimes):
            if np.isnan(r):
                if prev_r is not None:
                    shapes.append(dict(
                        type="rect", xref="x2", yref="y2 domain",
                        x0=str(band_start.date()), x1=str(dt.date()),
                        fillcolor=_regime_colors.get(int(prev_r), "rgba(0,0,0,0)"),
                        line_width=0, layer="below",
                        y0=0, y1=1,
                    ))
                prev_r = None; band_start = None
                continue
            ri = int(r)
            if ri != prev_r:
                if prev_r is not None:
                    shapes.append(dict(
                        type="rect", xref="x2", yref="y2 domain",
                        x0=str(band_start.date()), x1=str(dt.date()),
                        fillcolor=_regime_colors.get(prev_r, "rgba(0,0,0,0)"),
                        line_width=0, layer="below",
                        y0=0, y1=1,
                    ))
                band_start = dt
                prev_r = ri
        if prev_r is not None and band_start is not None and len(dates) > 0:
            shapes.append(dict(
                type="rect", xref="x2", yref="y2 domain",
                x0=str(band_start.date()), x1=str(dates[-1].date()),
                fillcolor=_regime_colors.get(prev_r, "rgba(0,0,0,0)"),
                line_width=0, layer="below",
                y0=0, y1=1,
            ))
        return shapes

    regime_shapes = _regime_shapes(plot_dates, regime_window)

    # ── Build subplots: 4 rows ─────────────────────────────────────────────
    fig = make_subplots(
        rows=4, cols=1,
        row_heights=[0.35, 0.25, 0.20, 0.20],
        shared_xaxes=False,
        vertical_spacing=0.07,
        subplot_titles=(
            "Equity Curves (compounded, $1 000 start)",
            "BTC Price with HMM Regime Overlay",
            "Monthly Returns — Baseline AMB (%)",
            "Monthly Returns — HMM-Enhanced AMB (%)",
        ),
    )

    # Row 1: Equity curves ─────────────────────────────────────────────────
    for eq, name, color, dash in [
        (eq_base, "Baseline AMB",   "#4A90E2", "solid"),
        (eq_hmm,  "HMM-Enhanced",   "#27AE60", "solid"),
        (eq_bh,   "Buy & Hold",     "#E67E22", "dash"),
    ]:
        fig.add_trace(go.Scatter(
            x=eq.index, y=eq.values, name=name,
            line=dict(color=color, dash=dash, width=2),
            hovertemplate="%{x|%Y-%m-%d}  $%{y:.0f}<extra>" + name + "</extra>",
        ), row=1, col=1)

    # Metrics annotation box ───────────────────────────────────────────────
    def _r(key: str, label: str, fmt: str = ".1f") -> str:
        vals = [f"{label}"]
        for v in results.values():
            vals.append(f"{v.get(key, 0):{fmt}}")
        return "  ".join(f"{x:>10}" for x in vals)

    annotation_lines = [
        "  ".join(["Metric".rjust(16)] + [k.rjust(16) for k in results.keys()]),
        "─" * (16 + 18 * len(results)),
        _r("pl_pct",        "Total P/L %"),
        _r("ann_return",    "Ann. Return %"),
        _r("max_dd",        "Max DD %"),
        _r("calmar",        "Calmar",        fmt=".3f"),
        _r("win_rate",      "Win Rate %"),
        _r("expectancy",    "Expectancy %"),
        _r("trades",        "Trades",        fmt="d"),
        _r("sl_hit_rate",   "SL Hit Rate %"),
    ]
    fig.add_annotation(
        xref="paper", yref="paper", x=0.01, y=0.99,
        text="<br>".join(annotation_lines),
        showarrow=False, align="left",
        font=dict(family="monospace", size=11, color="#CCCCCC"),
        bgcolor="rgba(30,33,48,0.85)", bordercolor="#555", borderwidth=1,
        borderpad=6,
    )

    # Row 2: BTC Price + Regime overlay ───────────────────────────────────
    fig.add_trace(go.Scatter(
        x=plot_df.index, y=plot_df["close"].values,
        name="BTC Close", line=dict(color="#E0E0E0", width=1.5),
        hovertemplate="%{x|%Y-%m-%d}  $%{y:,.0f}<extra>BTC Close</extra>",
        showlegend=False,
    ), row=2, col=1)

    # Regime legend traces (invisible, just for legend)
    for regime_val, label, color in [
        (BULL,     "Bull",     "rgba(0,200,100,0.5)"),
        (SIDEWAYS, "Sideways", "rgba(200,200,0,0.5)"),
        (BEAR,     "Bear",     "rgba(220,50,50,0.5)"),
    ]:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=12, color=color, symbol="square"),
            name=label, showlegend=True,
        ), row=2, col=1)

    # Add regime shapes to figure
    for shape in regime_shapes:
        fig.add_shape(shape)

    # Rows 3 & 4: Monthly heatmaps ─────────────────────────────────────────
    heatmap_kwargs = dict(
        colorscale=[
            [0.0,  "#8B0000"],
            [0.35, "#CC3333"],
            [0.5,  "#1e2130"],
            [0.65, "#2E8B57"],
            [1.0,  "#00AA44"],
        ],
        zmid=0,
        hoverongaps=False,
        colorbar=dict(len=0.22, thickness=12),
    )

    for row, pivot, label in [(3, mr_base, "Baseline"), (4, mr_hmm, "HMM-Enhanced")]:
        z     = pivot.values
        years = [str(y) for y in pivot.index.tolist()]
        months = _MONTH_ABBR

        z_round = [[round(v, 1) if v == v else None for v in row_] for row_ in z.tolist()]
        fig.add_trace(go.Heatmap(
            z=z, x=months, y=years,
            text=z_round,
            texttemplate="%{text}",
            name=label,
            zmin=-15, zmax=15,
            showscale=(row == 3),
            **heatmap_kwargs,
        ), row=row, col=1)

    # ── Layout ────────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text="AMB Strategy — HMM Regime Filter Comparison",
            font=dict(size=20, color="#FFFFFF"),
            x=0.5,
        ),
        template="plotly_dark",
        height=1400,
        legend=dict(
            orientation="h", y=1.03, x=0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=12),
        ),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#1e2130",
        font=dict(color="#CCCCCC"),
        hovermode="x unified",
    )

    # ── Y-axes ────────────────────────────────────────────────────────────
    fig.update_yaxes(title_text="Capital ($)", row=1, col=1, tickprefix="$")
    fig.update_yaxes(title_text="BTC Price ($)", row=2, col=1, tickprefix="$")

    # ── Save ──────────────────────────────────────────────────────────────
    RESULTS_DIR.mkdir(exist_ok=True)
    fig.write_html(str(output_path), include_plotlyjs="cdn")
    print(f"  HTML dashboard saved → {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="AMB: Baseline vs HMM-Enhanced comparison")
    parser.add_argument("--ticker",      default="BTCUSDT")
    parser.add_argument("--source",      default="yfinance", choices=["yfinance", "bybit"])
    parser.add_argument("--start",       default="2021-01-01",
                        help="Trade-start date (warmup data loaded automatically)")
    parser.add_argument("--show-trades", action="store_true",
                        help="Print filtered trade list")
    parser.add_argument("--no-html",     action="store_true",
                        help="Skip HTML dashboard generation")
    parser.add_argument("--refresh",     action="store_true", help="Force data refresh")
    parser.add_argument("--output",      default=None,
                        help="Custom HTML output path (default: results/backtest_hmm_comparison.html)")
    parser.add_argument("--confidence",  type=float, default=0.0,
                        help="Posterior probability threshold for regime activation "
                             "(0=hard label, e.g. 0.70 = require P≥70%% to enter). "
                             "Ignored when --scan is used.")
    parser.add_argument("--scan",        action="store_true",
                        help="Grid-scan confidence thresholds [0.50..0.85] and print comparison table")
    args = parser.parse_args()

    trade_start = pd.Timestamp(args.start)

    # ── Load data (full history for MA + HMM warmup) ───────────────────────
    print(f"\nLoading {args.ticker} via {args.source} (full history for warmup)…")
    df = get_slice(
        args.ticker,
        start=None, end=None,
        warmup=True,
        force_refresh=args.refresh,
        source=args.source,
    )
    print(f"  Loaded {len(df)} bars  [{df.index[0].date()} → {df.index[-1].date()}]")
    print(f"  Trade window starts: {trade_start.date()}")

    # ── Strategy params ────────────────────────────────────────────────────
    ticker_key = "BTC-USD" if args.ticker.upper() in ("BTCUSDT", "BTC", "BTC-USD") else args.ticker
    params = get_ticker_params(ticker_key)

    # ── Baseline AMB ───────────────────────────────────────────────────────
    print("\nRunning Baseline AMB…")
    baseline_trades = run_strategy(df, params, trade_start=trade_start)
    baseline_metrics = compute_metrics(
        baseline_trades, params,
        period_start=str(trade_start.date()),
        period_end=str(df.index[-1].date()),
    )
    print(f"  {len(baseline_trades)} trades  P/L {baseline_metrics['pl_pct']:+.2f}%")

    # ── HMM regime classification ──────────────────────────────────────────
    print("\nComputing HMM regimes (walk-forward, expanding window)…")
    hmm_result = compute_hmm_regimes(df, force_recompute=args.refresh)
    hmm_result.print_summary()

    # Sanity check: regime distribution
    for lbl, pct in hmm_result.regime_pct.items():
        if pct > 75:
            print(f"  ⚠  WARNING: '{lbl}' dominates with {pct}% — model may be degenerate.")

    # ── HMM-Enhanced AMB ──────────────────────────────────────────────────
    print("Running HMM-Enhanced AMB…")
    hmm_trades = run_strategy_hmm(df, params, hmm_result, trade_start=trade_start,
                                  conf_threshold=args.confidence)
    hmm_metrics = compute_metrics(
        hmm_trades, params,
        period_start=str(trade_start.date()),
        period_end=str(df.index[-1].date()),
    )
    print(f"  {len(hmm_trades)} trades  P/L {hmm_metrics['pl_pct']:+.2f}%")

    # ── Confidence grid-scan (optional) ───────────────────────────────────
    if args.scan:
        thresholds = [0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
        print("\n── Confidence Threshold Grid-Scan ──────────────────────────────")
        hdr = f"  {'Threshold':>10}  {'Trades':>7}  {'P/L %':>8}  {'Sharpe':>7}  {'MaxDD %':>8}  {'PF':>6}  {'SL%':>6}"
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for thr in thresholds:
            t_trades = run_strategy_hmm(df, params, hmm_result,
                                        trade_start=trade_start, conf_threshold=thr)
            t_m = compute_metrics(t_trades, params,
                                  period_start=str(trade_start.date()),
                                  period_end=str(df.index[-1].date()))
            label = "hard-label" if thr == 0.0 else f"≥{thr:.0%}"
            print(
                f"  {label:>10}  {t_m['trades']:>7}  {t_m['pl_pct']:>+8.2f}"
                f"  {t_m['sharpe_trade']:>7.3f}  {t_m['max_dd']:>8.2f}"
                f"  {t_m['profit_factor']:>6.3f}  {t_m['sl_hit_rate']:>6.1f}"
            )
        print()

    # ── Buy & Hold ─────────────────────────────────────────────────────────
    df_window  = df.loc[df.index >= trade_start]
    bh_start   = float(df_window["close"].iloc[0])
    bh_end     = float(df_window["close"].iloc[-1])
    bh_pl_pct  = (bh_end - bh_start) / bh_start * 100.0
    bh_days    = (df_window.index[-1] - df_window.index[0]).days
    bh_years   = max(bh_days / 365.25, 0.1)
    bh_ann     = bh_pl_pct / bh_years
    bh_end_cap = params.start_capital * (1 + bh_pl_pct / 100.0)

    # Build minimal bh metrics dict for table
    bh_metrics: dict = {
        "trades": 1, "pl_pct": round(bh_pl_pct, 2),
        "ann_return": round(bh_ann, 2), "end_capital": round(bh_end_cap, 2),
        "max_dd": 0.0, "calmar": 0.0,
        "win_rate": 100.0, "profit_factor": 0.0, "expectancy": round(bh_pl_pct, 2),
        "sharpe_trade": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "max_win": round(bh_pl_pct, 2), "max_loss": 0.0,
        "sl_hits": 0, "sl_hit_rate": 0.0,
    }

    # ── Console output ─────────────────────────────────────────────────────
    results = {
        "Baseline AMB":   baseline_metrics,
        "HMM-Enhanced":   hmm_metrics,
        "Buy & Hold":     bh_metrics,
    }
    _print_metrics_table(results)

    if args.show_trades:
        _print_filtered_trades_summary(baseline_trades, hmm_trades)

    # ── HTML dashboard ─────────────────────────────────────────────────────
    if not args.no_html:
        all_dates = df.loc[df.index >= trade_start].index

        equity_base = _build_equity_curve(baseline_trades, all_dates, params.start_capital)
        equity_hmm  = _build_equity_curve(hmm_trades,      all_dates, params.start_capital)

        # Buy & Hold equity curve
        close_window  = df_window["close"]
        equity_bh     = params.start_capital * (close_window / close_window.iloc[0])

        output_path = Path(args.output) if args.output else RESULTS_DIR / "backtest_hmm_comparison.html"

        print("\nGenerating HTML dashboard…")
        _build_html_dashboard(
            df            = df,
            equity_baseline = equity_base,
            equity_hmm      = equity_hmm,
            equity_bh       = equity_bh,
            hmm_result      = hmm_result,
            results         = results,
            trade_start     = trade_start,
            output_path     = output_path,
        )


if __name__ == "__main__":
    main()

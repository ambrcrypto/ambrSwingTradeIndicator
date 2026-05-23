"""
run_filter_comparison.py – Baseline vs HMM-Enhanced vs ADX+ATR vs Buy&Hold.

Four strategies on identical data, identical capital, identical trade parameters.

Usage:
    python -m backtest.run_filter_comparison
    python -m backtest.run_filter_comparison --source bybit --start 2021-01-01
    python -m backtest.run_filter_comparison --no-html
    python -m backtest.run_filter_comparison --refresh

Output:
    • Console: filter statistics + side-by-side metrics table
    • HTML:    backtest/results/backtest_filter_comparison.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from .data              import get_slice
from .strategy_amb      import AMBParams, Trade, run_strategy
from .engine            import compute_metrics
from .ticker_config     import get_ticker_params
from .strategy_amb_hmm  import compute_hmm_regimes, run_strategy_hmm, HMMResult, BULL, SIDEWAYS, BEAR
from .strategy_amb_adxatr import (
    run_strategy_adxatr, ADXATRFilterStats,
    ADX_PERIOD, ADX_THRESHOLD, ATR_PERIOD, ATR_MULTIPLIER,
)

RESULTS_DIR = Path(__file__).parent / "results"

_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (copied from run_hmm_comparison to stay self-contained)
# ─────────────────────────────────────────────────────────────────────────────

def _build_equity_curve(
    trades:        list[Trade],
    all_dates:     pd.DatetimeIndex,
    start_capital: float,
) -> pd.Series:
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


def _monthly_returns(equity: pd.Series) -> pd.DataFrame:
    monthly     = equity.resample("ME").last().ffill()
    monthly_ret = monthly.pct_change() * 100.0
    df          = monthly_ret.to_frame("ret")
    df["year"]  = df.index.year
    df["month"] = df.index.month
    pivot = df.pivot(index="year", columns="month", values="ret")
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = np.nan
    return pivot[sorted(pivot.columns)]


# ─────────────────────────────────────────────────────────────────────────────
# Console output
# ─────────────────────────────────────────────────────────────────────────────

def _print_metrics_table(results: dict[str, dict]) -> None:
    labels  = list(results.keys())
    metrics = [
        ("Trades",        "trades",        "d",   False),
        ("Total P/L %",   "pl_pct",        ".2f", False),
        ("Ann. Return %", "ann_return",    ".2f", False),
        ("Max DD %",      "max_dd",        ".2f", True),
        ("Calmar",        "calmar",        ".3f", False),
        ("Win Rate %",    "win_rate",      ".2f", False),
        ("Expectancy %",  "expectancy",    ".2f", False),
        ("Profit Factor", "profit_factor", ".3f", False),
        ("Sharpe (trade)","sharpe_trade",  ".3f", False),
        ("SL Hits",       "sl_hits",       "d",   True),
        ("SL Hit Rate %", "sl_hit_rate",   ".1f", True),
        ("End Capital $", "end_capital",   ".2f", False),
    ]
    col_w = 20
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
        best   = min(values) if lower_better else max(values)
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


# ─────────────────────────────────────────────────────────────────────────────
# HTML Dashboard
# ─────────────────────────────────────────────────────────────────────────────

def _build_html_dashboard(
    df:            pd.DataFrame,
    equity_base:   pd.Series,
    equity_hmm:    pd.Series,
    equity_adx:    pd.Series,
    equity_bh:     pd.Series,
    hmm_result:    HMMResult,
    adx_stats:     ADXATRFilterStats,
    results:       dict[str, dict],
    trade_start:   pd.Timestamp,
    output_path:   Path,
) -> None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("  plotly not installed – skipping HTML dashboard.")
        return

    # ── Slice to trade window ──────────────────────────────────────────────
    plot_df       = df.loc[df.index >= trade_start]
    plot_dates    = plot_df.index
    regime_window = hmm_result.regimes[df.index >= trade_start]

    eq_base_w = equity_base.loc[equity_base.index >= trade_start]
    eq_hmm_w  = equity_hmm.loc[equity_hmm.index  >= trade_start]
    eq_adx_w  = equity_adx.loc[equity_adx.index  >= trade_start]
    eq_bh_w   = equity_bh.loc[equity_bh.index   >= trade_start]

    # ── Monthly heatmaps ────────────────────────────────────────────────────
    mr_base = _monthly_returns(eq_base_w)
    mr_hmm  = _monthly_returns(eq_hmm_w)
    mr_adx  = _monthly_returns(eq_adx_w)

    # ── Regime colour bands ─────────────────────────────────────────────────
    _regime_colors = {
        BULL:     "rgba(0,200,100,0.15)",
        SIDEWAYS: "rgba(200,200,0,0.15)",
        BEAR:     "rgba(220,50,50,0.15)",
    }

    def _regime_shapes(dates: pd.DatetimeIndex, regimes: np.ndarray) -> list[dict]:
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
                        line_width=0, layer="below", y0=0, y1=1,
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
                        line_width=0, layer="below", y0=0, y1=1,
                    ))
                band_start = dt
                prev_r = ri
        if prev_r is not None and band_start is not None and len(dates) > 0:
            shapes.append(dict(
                type="rect", xref="x2", yref="y2 domain",
                x0=str(band_start.date()), x1=str(dates[-1].date()),
                fillcolor=_regime_colors.get(prev_r, "rgba(0,0,0,0)"),
                line_width=0, layer="below", y0=0, y1=1,
            ))
        return shapes

    regime_shapes = _regime_shapes(plot_dates, regime_window)

    # ── Build subplots: 5 rows ─────────────────────────────────────────────
    fig = make_subplots(
        rows=5, cols=1,
        row_heights=[0.30, 0.20, 0.17, 0.17, 0.16],
        shared_xaxes=False,
        vertical_spacing=0.06,
        subplot_titles=(
            "Equity Curves — $1,000 start (compounded)",
            "BTC Price with HMM Regime Overlay",
            "Monthly Returns — Baseline AMB (%)",
            "Monthly Returns — HMM-Enhanced (%)",
            "Monthly Returns — ADX+ATR (%)",
        ),
    )

    # Row 1: Equity curves ──────────────────────────────────────────────────
    for eq, name, color, dash in [
        (eq_base_w, "Baseline AMB",  "#4A90E2", "solid"),
        (eq_hmm_w,  "HMM-Enhanced",  "#27AE60", "solid"),
        (eq_adx_w,  "ADX+ATR",       "#E91E8C", "solid"),
        (eq_bh_w,   "Buy & Hold",    "#E67E22", "dash"),
    ]:
        fig.add_trace(go.Scatter(
            x=eq.index, y=eq.values, name=name,
            line=dict(color=color, dash=dash, width=2),
            hovertemplate="%{x|%Y-%m-%d}  $%{y:.0f}<extra>" + name + "</extra>",
        ), row=1, col=1)

    # Metrics annotation ────────────────────────────────────────────────────
    def _r(key: str, label: str, fmt: str = ".1f") -> str:
        vals = [f"{label}"]
        for v in results.values():
            vals.append(f"{v.get(key, 0):{fmt}}")
        return "  ".join(f"{x:>12}" for x in vals)

    annotation_lines = [
        "  ".join(["Metric".rjust(18)] + [k.rjust(14) for k in results.keys()]),
        "─" * (18 + 16 * len(results)),
        _r("pl_pct",       "Total P/L %"),
        _r("ann_return",   "Ann. Return %"),
        _r("max_dd",       "Max DD %"),
        _r("calmar",       "Calmar",        fmt=".3f"),
        _r("win_rate",     "Win Rate %"),
        _r("trades",       "Trades",        fmt="d"),
        _r("sl_hit_rate",  "SL Hit Rate %"),
    ]
    fig.add_annotation(
        xref="paper", yref="paper", x=0.01, y=0.99,
        text="<br>".join(annotation_lines),
        showarrow=False, align="left",
        font=dict(family="monospace", size=10, color="#CCCCCC"),
        bgcolor="rgba(30,33,48,0.88)", bordercolor="#555", borderwidth=1,
        borderpad=6,
    )

    # ADX+ATR filter stats annotation ───────────────────────────────────────
    adx_pct = adx_stats.pct_filtered_adx
    atr_pct = adx_stats.pct_filtered_atr
    filter_lines = [
        "<b>ADX+ATR Filter Stats</b>",
        f"Total signals : {adx_stats.total_signals}",
        f"Passed        : {adx_stats.passed}",
        f"ADX filtered  : {adx_stats.filtered_adx_only + adx_stats.filtered_both}  ({adx_pct:.1f}%)",
        f"ATR filtered  : {adx_stats.filtered_atr_only + adx_stats.filtered_both}  ({atr_pct:.1f}%)",
        f"ADX≥{ADX_THRESHOLD}  ATR×{ATR_MULTIPLIER}",
    ]
    fig.add_annotation(
        xref="paper", yref="paper", x=0.99, y=0.99,
        text="<br>".join(filter_lines),
        showarrow=False, align="right",
        font=dict(family="monospace", size=10, color="#CCCCCC"),
        bgcolor="rgba(30,33,48,0.88)", bordercolor="#E91E8C", borderwidth=1,
        borderpad=6,
    )

    # Row 2: BTC Price + HMM Regime overlay ─────────────────────────────────
    fig.add_trace(go.Scatter(
        x=plot_df.index, y=plot_df["close"].values,
        name="BTC Close", line=dict(color="#E0E0E0", width=1.5),
        hovertemplate="%{x|%Y-%m-%d}  $%{y:,.0f}<extra>BTC Close</extra>",
        showlegend=False,
    ), row=2, col=1)
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
    for shape in regime_shapes:
        fig.add_shape(shape)

    # Rows 3–5: Monthly heatmaps ─────────────────────────────────────────────
    heatmap_kwargs = dict(
        colorscale=[
            [0.0,  "#8B0000"],
            [0.35, "#CC3333"],
            [0.5,  "#1e2130"],
            [0.65, "#2E8B57"],
            [1.0,  "#00AA44"],
        ],
        zmid=0,
        zmin=-15, zmax=15,
        hoverongaps=False,
        colorbar=dict(len=0.17, thickness=12),
    )
    for row, pivot, label, show_scale in [
        (3, mr_base, "Baseline",    True),
        (4, mr_hmm,  "HMM-Enhanced", False),
        (5, mr_adx,  "ADX+ATR",     False),
    ]:
        z      = pivot.values
        years  = [str(y) for y in pivot.index.tolist()]
        z_text = [[round(v, 1) if v == v else None for v in row_] for row_ in z.tolist()]
        fig.add_trace(go.Heatmap(
            z=z, x=_MONTH_ABBR, y=years,
            text=z_text,
            texttemplate="%{text}",
            name=label,
            showscale=show_scale,
            **heatmap_kwargs,
        ), row=row, col=1)

    # ── Layout ────────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text="AMB Strategy Filter Comparison — Baseline / HMM / ADX+ATR",
            font=dict(size=18, color="#FFFFFF"),
            x=0.5,
        ),
        template="plotly_dark",
        height=1600,
        legend=dict(
            orientation="h", y=1.025, x=0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=12),
        ),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#1e2130",
        font=dict(color="#CCCCCC"),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Capital ($)", row=1, col=1, tickprefix="$")
    fig.update_yaxes(title_text="BTC Price ($)", row=2, col=1, tickprefix="$")

    RESULTS_DIR.mkdir(exist_ok=True)
    fig.write_html(str(output_path), include_plotlyjs="cdn")
    print(f"  HTML dashboard saved → {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AMB: Baseline vs HMM-Enhanced vs ADX+ATR vs Buy&Hold"
    )
    parser.add_argument("--ticker",  default="BTCUSDT")
    parser.add_argument("--source",  default="yfinance", choices=["yfinance", "bybit"])
    parser.add_argument("--start",   default="2021-01-01",
                        help="Trade-start date (warmup loaded automatically)")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip HTML dashboard generation")
    parser.add_argument("--refresh", action="store_true",
                        help="Force data + HMM cache refresh")
    parser.add_argument("--output",  default=None,
                        help="Custom output path (default: results/backtest_filter_comparison.html)")
    args = parser.parse_args()

    trade_start = pd.Timestamp(args.start)

    # ── Load data ─────────────────────────────────────────────────────────
    print(f"\nLoading {args.ticker} via {args.source} (full history for warmup)…")
    df = get_slice(
        args.ticker,
        start=None, end=None,
        warmup=True,
        force_refresh=args.refresh,
        source=args.source,
    )
    print(f"  {len(df)} bars  [{df.index[0].date()} → {df.index[-1].date()}]")
    print(f"  Trade window starts : {trade_start.date()}")
    print(f"  Data source         : {args.source}")

    # ── Strategy params ───────────────────────────────────────────────────
    ticker_key = "BTC-USD" if args.ticker.upper() in ("BTCUSDT", "BTC", "BTC-USD") else args.ticker
    params = get_ticker_params(ticker_key)

    # ── Baseline AMB ──────────────────────────────────────────────────────
    print("\nRunning Baseline AMB…")
    base_trades  = run_strategy(df, params, trade_start=trade_start)
    base_metrics = compute_metrics(
        base_trades, params,
        period_start=str(trade_start.date()),
        period_end=str(df.index[-1].date()),
    )
    print(f"  {len(base_trades)} trades  P/L {base_metrics['pl_pct']:+.2f}%")

    # ── HMM regime classification ─────────────────────────────────────────
    print("\nComputing HMM regimes (walk-forward, expanding window)…")
    hmm_result = compute_hmm_regimes(df, force_recompute=args.refresh)
    hmm_result.print_summary()
    for lbl, pct in hmm_result.regime_pct.items():
        if pct > 75:
            print(f"  ⚠  WARNING: '{lbl}' dominates with {pct}% — model may be degenerate.")

    print("Running HMM-Enhanced AMB…")
    hmm_trades  = run_strategy_hmm(df, params, hmm_result, trade_start=trade_start)
    hmm_metrics = compute_metrics(
        hmm_trades, params,
        period_start=str(trade_start.date()),
        period_end=str(df.index[-1].date()),
    )
    print(f"  {len(hmm_trades)} trades  P/L {hmm_metrics['pl_pct']:+.2f}%")

    # ── ADX+ATR filtered AMB ──────────────────────────────────────────────
    print(f"\nRunning ADX+ATR filtered AMB  "
          f"(ADX>{ADX_THRESHOLD}, ATR×{ATR_MULTIPLIER} from slow-MA)…")
    adx_trades, adx_stats = run_strategy_adxatr(df, params, trade_start=trade_start)
    adx_metrics = compute_metrics(
        adx_trades, params,
        period_start=str(trade_start.date()),
        period_end=str(df.index[-1].date()),
    )
    print(f"  {len(adx_trades)} trades  P/L {adx_metrics['pl_pct']:+.2f}%")
    adx_stats.print_summary()

    # ── Buy & Hold ────────────────────────────────────────────────────────
    df_window = df.loc[df.index >= trade_start]
    bh_start  = float(df_window["close"].iloc[0])
    bh_end    = float(df_window["close"].iloc[-1])
    bh_pl_pct = (bh_end - bh_start) / bh_start * 100.0
    bh_days   = (df_window.index[-1] - df_window.index[0]).days
    bh_years  = max(bh_days / 365.25, 0.1)
    bh_ann    = bh_pl_pct / bh_years
    bh_end_cap = params.start_capital * (1 + bh_pl_pct / 100.0)
    bh_metrics: dict = {
        "trades": 1, "pl_pct": round(bh_pl_pct, 2),
        "ann_return": round(bh_ann, 2), "end_capital": round(bh_end_cap, 2),
        "max_dd": 0.0, "calmar": 0.0,
        "win_rate": 100.0, "profit_factor": 0.0, "expectancy": round(bh_pl_pct, 2),
        "sharpe_trade": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "max_win": round(bh_pl_pct, 2), "max_loss": 0.0,
        "sl_hits": 0, "sl_hit_rate": 0.0,
    }

    # ── Console summary ───────────────────────────────────────────────────
    results = {
        "Baseline AMB": base_metrics,
        "HMM-Enhanced": hmm_metrics,
        "ADX+ATR":      adx_metrics,
        "Buy & Hold":   bh_metrics,
    }
    _print_metrics_table(results)

    # ── HTML dashboard ────────────────────────────────────────────────────
    if not args.no_html:
        all_dates  = df.loc[df.index >= trade_start].index
        close_win  = df_window["close"]

        eq_base = _build_equity_curve(base_trades, all_dates, params.start_capital)
        eq_hmm  = _build_equity_curve(hmm_trades,  all_dates, params.start_capital)
        eq_adx  = _build_equity_curve(adx_trades,  all_dates, params.start_capital)
        eq_bh   = params.start_capital * (close_win / close_win.iloc[0])

        output_path = (
            Path(args.output) if args.output
            else RESULTS_DIR / "backtest_filter_comparison.html"
        )
        print("\nGenerating HTML dashboard…")
        _build_html_dashboard(
            df           = df,
            equity_base  = eq_base,
            equity_hmm   = eq_hmm,
            equity_adx   = eq_adx,
            equity_bh    = eq_bh,
            hmm_result   = hmm_result,
            adx_stats    = adx_stats,
            results      = results,
            trade_start  = trade_start,
            output_path  = output_path,
        )


if __name__ == "__main__":
    main()

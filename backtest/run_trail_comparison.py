"""
run_trail_comparison.py – Baseline vs ATR Trailing Stop grid scan.

25-combination grid: trail_activate_pct × trail_atr_factor.
The 3 spec highlight variants are marked with [★] in the table.

Usage:
    python -m backtest.run_trail_comparison
    python -m backtest.run_trail_comparison --source bybit --start 2021-01-01
    python -m backtest.run_trail_comparison --no-html
    python -m backtest.run_trail_comparison --ticker ETH

Output:
    • Console: 25-row grid table (Sharpe, Sortino, CAGR, MaxDD, Trades, TSL-Exits, Re-Entries)
    • HTML:    backtest/results/backtest_trail_comparison.html
              (equity curves for Baseline + 3 highlights, monthly heatmaps, grid table)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from .data          import get_slice
from .strategy_amb  import AMBParams, Trade, run_strategy
from .engine        import compute_metrics
from .ticker_config import get_ticker_params

RESULTS_DIR = Path(__file__).parent / "results"

_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Grid dimensions
ACTIVATE_PCTS = [3, 5, 8, 10, 15]
ATR_FACTORS   = [1.0, 1.5, 2.0, 2.5, 3.0]

# Spec highlight variants (marked with ★ in output)
HIGHLIGHTS = {(5, 2.0), (10, 1.5), (15, 3.0)}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_equity_curve(
    trades: list[Trade], all_dates: pd.DatetimeIndex, start_capital: float,
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
    return eq.ffill()


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


def _sortino(percs: list[float]) -> float:
    if len(percs) < 2:
        return 0.0
    mu = float(np.mean(percs))
    down = [p for p in percs if p < 0]
    if not down:
        return float("inf")
    dd = float(np.sqrt(np.mean([p ** 2 for p in down])))
    return mu / dd if dd > 0 else 0.0


def _tsl_stats(trades: list[Trade]) -> tuple[int, int]:
    """Return (tsl_exits, trail_reentries)."""
    tsl_exits = sum(1 for t in trades if t.exit_type in ("TSL", "TSS"))
    # Heuristic: trade entered in same direction right after a TSL/TSS exit
    trail_reentries = 0
    for i in range(1, len(trades)):
        prev, curr = trades[i - 1], trades[i]
        if (prev.exit_type in ("TSL", "TSS")
                and curr.direction == prev.direction
                and curr.entry_date >= prev.exit_date):
            trail_reentries += 1
    return tsl_exits, trail_reentries


# ─────────────────────────────────────────────────────────────────────────────
# Console grid table
# ─────────────────────────────────────────────────────────────────────────────

def _print_grid(grid_results: list[dict], baseline: dict) -> None:
    W = 108
    print("=" * W)
    print(f"  {'Act%':>4}  {'ATRx':>4}  {'Sharpe':>7}  {'Sortino':>7}  "
          f"{'CAGR%':>7}  {'MaxDD%':>7}  {'Trades':>6}  {'TSL':>4}  "
          f"{'ReEntr':>6}  {'EndCap':>9}  ")
    print("-" * W)

    # Baseline row
    b = baseline
    print(f"  {'BASE':>4}  {'—':>4}  {b['sharpe_trade']:>7.3f}  {b['sortino']:>7.3f}  "
          f"{b['ann_return']:>7.2f}  {b['max_dd']:>7.2f}  {b['trades']:>6d}  "
          f"{'—':>4}  {'—':>6}  {b['end_capital']:>9.2f}  ")
    print("-" * W)

    for r in grid_results:
        star = " ★" if (r["activate_pct"], r["atr_factor"]) in HIGHLIGHTS else "  "
        print(f"{star} {r['activate_pct']:>4}  {r['atr_factor']:>4.1f}  "
              f"{r['sharpe_trade']:>7.3f}  {r['sortino']:>7.3f}  "
              f"{r['ann_return']:>7.2f}  {r['max_dd']:>7.2f}  "
              f"{r['trades']:>6d}  {r['tsl_exits']:>4d}  "
              f"{r['trail_reentries']:>6d}  {r['end_capital']:>9.2f}  ")

    print("=" * W)
    print("  ★ = Handover spec highlight variants")


# ─────────────────────────────────────────────────────────────────────────────
# HTML dashboard
# ─────────────────────────────────────────────────────────────────────────────

def _build_html(
    highlight_curves: dict[str, pd.Series],
    highlight_heatmaps: dict[str, pd.DataFrame],
    grid_results: list[dict],
    baseline_metrics: dict,
    ticker: str,
    out_path: Path,
) -> None:
    def _eq_traces(curves: dict) -> str:
        colours = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
        lines   = []
        for (label, eq), col in zip(curves.items(), colours):
            xs = [str(d.date()) for d in eq.index]
            ys = [f"{v:.2f}" for v in eq.values]
            lines.append(
                f"{{x:[{','.join(repr(x) for x in xs)}],"
                f"y:[{','.join(ys)}],"
                f"mode:'lines',name:{repr(label)},"
                f"line:{{color:{repr(col)},width:2}}}}"
            )
        return ",".join(lines)

    def _heatmap_html(label: str, pivot: pd.DataFrame) -> str:
        rows = ""
        for year in sorted(pivot.index):
            cells = f"<td class='ylbl'>{year}</td>"
            for m in range(1, 13):
                v = pivot.loc[year, m] if m in pivot.columns else np.nan
                if np.isnan(v):
                    cells += "<td class='na'>—</td>"
                else:
                    cls = "pos" if v >= 0 else "neg"
                    cells += f"<td class='{cls}'>{v:+.1f}</td>"
            rows += f"<tr>{cells}</tr>"
        header = "<tr><th></th>" + "".join(f"<th>{a}</th>" for a in _MONTH_ABBR) + "</tr>"
        return f"<h3>{label}</h3><table class='hmap'>{header}{rows}</table>"

    def _grid_table_html() -> str:
        hdr = ("<tr><th>Act%</th><th>ATRx</th><th>Sharpe</th><th>Sortino</th>"
               "<th>CAGR%</th><th>MaxDD%</th><th>Trades</th>"
               "<th>TSL</th><th>ReEntr</th><th>EndCap</th></tr>")
        rows = ""
        for r in grid_results:
            star = "★ " if (r["activate_pct"], r["atr_factor"]) in HIGHLIGHTS else ""
            hl   = " class='highlight'" if star else ""
            rows += (f"<tr{hl}><td>{star}{r['activate_pct']}</td><td>{r['atr_factor']:.1f}</td>"
                     f"<td>{r['sharpe_trade']:.3f}</td><td>{r['sortino']:.3f}</td>"
                     f"<td>{r['ann_return']:.2f}</td><td>{r['max_dd']:.2f}</td>"
                     f"<td>{r['trades']}</td><td>{r['tsl_exits']}</td>"
                     f"<td>{r['trail_reentries']}</td><td>{r['end_capital']:.2f}</td></tr>")
        return f"<table class='grid'>{hdr}{rows}</table>"

    eq_traces = _eq_traces(highlight_curves)
    heatmaps  = "".join(_heatmap_html(lbl, piv)
                        for lbl, piv in highlight_heatmaps.items())
    grid_tbl  = _grid_table_html()
    b = baseline_metrics

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Trail SL Comparison – {ticker}</title>
<script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 20px; background: #f8f9fa; color: #222; }}
  h1   {{ color: #333; }}
  h3   {{ color: #555; margin-top: 24px; }}
  .section {{ background: #fff; border-radius: 8px; padding: 16px 20px;
              box-shadow: 0 1px 4px rgba(0,0,0,.12); margin-bottom: 24px; }}
  table.hmap td, table.hmap th {{ padding: 3px 7px; text-align: right; font-size: 0.82em;
                                   border: 1px solid #ddd; }}
  table.hmap .ylbl {{ font-weight: bold; color: #444; }}
  table.hmap .pos  {{ background: #c8f0c8; }}
  table.hmap .neg  {{ background: #f5c5c5; }}
  table.hmap .na   {{ color: #aaa; }}
  table.grid       {{ border-collapse: collapse; width: 100%; font-size: 0.88em; }}
  table.grid th    {{ background: #3c5a8a; color: #fff; padding: 6px 10px; }}
  table.grid td    {{ padding: 5px 10px; border-bottom: 1px solid #e0e0e0; text-align: right; }}
  table.grid tr:hover td {{ background: #f0f4ff; }}
  table.grid tr.highlight td {{ background: #fff8e1; font-weight: bold; }}
  .baseline-box    {{ border: 2px solid #1f77b4; border-radius: 6px; padding: 10px 16px;
                      display: inline-block; margin-bottom: 16px; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>ATR Trailing Stop Comparison – {ticker}</h1>

<div class="section">
  <div class="baseline-box">
    <b>Baseline (no trail)</b> &nbsp;|&nbsp;
    Trades: {b['trades']} &nbsp;|&nbsp;
    P/L: {b['pl_pct']:+.2f}% &nbsp;|&nbsp;
    CAGR: {b['ann_return']:.2f}% &nbsp;|&nbsp;
    Sharpe: {b['sharpe_trade']:.3f} &nbsp;|&nbsp;
    MaxDD: {b['max_dd']:.2f}%
  </div>
  <div id="eq-chart" style="height:420px"></div>
</div>

<div class="section">
  <h3>Monthly Returns – Highlight Variants</h3>
  {heatmaps}
</div>

<div class="section">
  <h3>25-Kombination Grid (Act% × ATR-Factor) — ★ = Spec-Highlights</h3>
  {grid_tbl}
</div>

<script>
Plotly.newPlot('eq-chart', [{eq_traces}], {{
  title: 'Equity Curves (Baseline + Highlights)',
  xaxis: {{title: 'Date', showgrid: true}},
  yaxis: {{title: 'Capital ($)', showgrid: true}},
  legend: {{orientation: 'h', y: -0.15}},
  margin: {{t: 40, b: 60}},
  hovermode: 'x unified',
}}, {{responsive: true}});
</script>
</body>
</html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"  HTML dashboard saved → {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Trail SL grid comparison")
    ap.add_argument("--ticker",  default="BTCUSDT")
    ap.add_argument("--source",  default="yfinance", choices=["yfinance", "bybit"])
    ap.add_argument("--start",   default="2021-01-01")
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--output",  default=None)
    args = ap.parse_args()

    ticker_params = get_ticker_params(args.ticker)
    params_base   = ticker_params  # AMBParams object, trail disabled by default

    # ── Load data ──────────────────────────────────────────────────────────
    print(f"\nLoading {args.ticker} via {args.source} (full history for warmup)…")
    df = get_slice(args.ticker, source=args.source)
    trade_start = pd.Timestamp(args.start)

    td = df[df.index >= trade_start]
    print(f"  {len(df)} bars  [{df.index[0].date()} → {df.index[-1].date()}]")
    print(f"  Trade window starts : {args.start}")
    print(f"  Data source         : {args.source}\n")

    # ── Baseline ──────────────────────────────────────────────────────────
    print("Running Baseline AMB (trail_sl_enable=False)…")
    baseline_trades = run_strategy(df, params_base, trade_start=trade_start)
    baseline_m = compute_metrics(
        baseline_trades, params_base,
        str(trade_start.date()), str(df.index[-1].date()),
    )
    baseline_m["sortino"] = _sortino([t.pct for t in baseline_trades])
    print(f"  {baseline_m['trades']} trades  P/L {baseline_m['pl_pct']:+.2f}%\n")

    # ── Grid scan ─────────────────────────────────────────────────────────
    print(f"Grid scan: {len(ACTIVATE_PCTS)} × {len(ATR_FACTORS)} = "
          f"{len(ACTIVATE_PCTS)*len(ATR_FACTORS)} combinations…")

    grid_results: list[dict] = []
    for act_pct in ACTIVATE_PCTS:
        for atr_f in ATR_FACTORS:
            import dataclasses
            p = dataclasses.replace(
                params_base,
                trail_sl_enable=True,
                trail_activate_pct=float(act_pct),
                trail_atr_factor=atr_f,
            )
            trades = run_strategy(df, p, trade_start=trade_start)
            m = compute_metrics(trades, p,
                                str(trade_start.date()), str(df.index[-1].date()))
            tsl_ex, trail_re = _tsl_stats(trades)
            row = {
                "activate_pct":    act_pct,
                "atr_factor":      atr_f,
                "sharpe_trade":    m["sharpe_trade"],
                "sortino":         _sortino([t.pct for t in trades]),
                "ann_return":      m["ann_return"],
                "max_dd":          m["max_dd"],
                "trades":          m["trades"],
                "tsl_exits":       tsl_ex,
                "trail_reentries": trail_re,
                "end_capital":     m["end_capital"],
                "_trades":         trades,   # keep for equity curves
            }
            grid_results.append(row)

    # ── Console table ─────────────────────────────────────────────────────
    print()
    _print_grid(grid_results, baseline_m)

    # ── HTML ──────────────────────────────────────────────────────────────
    if not args.no_html:
        print("\nGenerating HTML dashboard…")
        all_dates = df[df.index >= trade_start].index

        # Equity curves: Baseline + 3 highlights
        highlight_curves: dict[str, pd.Series] = {
            "Baseline": _build_equity_curve(baseline_trades, all_dates,
                                            params_base.start_capital),
        }
        for r in grid_results:
            if (r["activate_pct"], r["atr_factor"]) in HIGHLIGHTS:
                lbl = f"Trail {r['activate_pct']}% / {r['atr_factor']:.1f}×"
                highlight_curves[lbl] = _build_equity_curve(
                    r["_trades"], all_dates, params_base.start_capital)

        # Heatmaps: Baseline + highlights
        highlight_heatmaps: dict[str, pd.DataFrame] = {
            "Baseline": _monthly_returns(highlight_curves["Baseline"]),
        }
        for lbl, eq in highlight_curves.items():
            if lbl != "Baseline":
                highlight_heatmaps[lbl] = _monthly_returns(eq)

        # Strip internal _trades key before passing to HTML builder
        grid_clean = [{k: v for k, v in r.items() if k != "_trades"}
                      for r in grid_results]

        out_path = Path(args.output) if args.output else (
            RESULTS_DIR / "backtest_trail_comparison.html")
        _build_html(highlight_curves, highlight_heatmaps, grid_clean,
                    baseline_m, args.ticker, out_path)


if __name__ == "__main__":
    main()

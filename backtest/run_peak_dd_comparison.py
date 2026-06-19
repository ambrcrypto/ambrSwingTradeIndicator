"""
run_peak_dd_comparison.py – Grid-Scan für Peak-Drawdown Stop

Vergleicht 16 Kombinationen (4 activate_pct × 4 peak_dd_pct) gegen Baseline.
Optional: Regime-Overlay (EMA130-Slope) für adaptive PD-Schwelle.

Usage:
    python -m backtest.run_peak_dd_comparison [--ticker BTCUSDT] [--source yfinance]
                                              [--start 2021-01-01] [--no-html]
                                              [--output results/backtest_peak_dd_comparison.html]
"""
from __future__ import annotations
import argparse, math, dataclasses
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

from backtest.data        import get_all
from backtest.strategy_amb import AMBParams, run_strategy, Trade
from backtest.ticker_config import get_ticker_params
from backtest.engine       import compute_metrics

# ─────────────────────────────────────────────────────────────────────────────
# Grid definition
# ─────────────────────────────────────────────────────────────────────────────
ACTIVATE_PCTS = [2.0, 3.0, 5.0, 8.0]   # min unrealised gain before PD activates
PEAK_DD_PCTS  = [1.5, 2.0, 3.0, 4.0]   # max % drop from peak_close before exit

HIGHLIGHTS = {(3.0, 2.0), (5.0, 3.0)}  # mark these in output

# ─────────────────────────────────────────────────────────────────────────────
# Equity helper
# ─────────────────────────────────────────────────────────────────────────────
def _equity_curve(trades: list[Trade], start_cap: float) -> list[float]:
    capital = start_cap
    curve   = [capital]
    for t in trades:
        capital *= (1.0 + t.pct / 100.0)
        curve.append(capital)
    return curve


# ─────────────────────────────────────────────────────────────────────────────
# Metrics helpers
# ─────────────────────────────────────────────────────────────────────────────
def _sortino(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    arr  = np.array(returns, dtype=float)
    mean = arr.mean()
    down = arr[arr < 0]
    if len(down) == 0:
        return float('inf')
    dd   = math.sqrt(np.mean(down ** 2))
    return mean / dd if dd > 0 else 0.0


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=float)
    std = arr.std(ddof=1)
    return arr.mean() / std if std > 0 else 0.0


def _cagr(equity: list[float], start_cap: float, n_years: float) -> float:
    if n_years <= 0 or equity[-1] <= 0:
        return 0.0
    return ((equity[-1] / start_cap) ** (1.0 / n_years) - 1.0) * 100.0


def _max_dd(equity: list[float]) -> float:
    peak = equity[0]
    dd   = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = max(dd, (peak - v) / peak * 100.0)
    return dd


def _pd_stats(trades: list[Trade]) -> int:
    """Count PD-exits."""
    return sum(1 for t in trades if t.exit_type == "PD")


def _run_metrics(trades: list[Trade], params: AMBParams, trade_start: pd.Timestamp,
                 n_years: float) -> dict:
    pcts   = [t.pct for t in trades]
    equity = _equity_curve(trades, params.start_capital)

    return {
        "sharpe":   _sharpe(pcts),
        "sortino":  _sortino(pcts),
        "cagr":     _cagr(equity, params.start_capital, n_years),
        "maxdd":    _max_dd(equity),
        "trades":   len(trades),
        "pd_exits": _pd_stats(trades),
        "end_cap":  equity[-1],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Console output
# ─────────────────────────────────────────────────────────────────────────────
def _print_grid(base_m: dict, grid_results: list[tuple]) -> None:
    W = 112
    print()
    print("=" * W)
    print(f"  {'Act%':>5}  {'DDx':>5}   {'Sharpe':>7}  {'Sortino':>8}  {'CAGR%':>8}  "
          f"{'MaxDD%':>7}  {'Trades':>7}  {'PD':>5}  {'EndCap':>12}")
    print("-" * W)
    print(f"  {'BASE':>5}  {'—':>5}   {base_m['sharpe']:>7.3f}  {base_m['sortino']:>8.3f}  "
          f"{base_m['cagr']:>8.2f}  {base_m['maxdd']:>7.2f}  {base_m['trades']:>7}  "
          f"{'—':>5}  {base_m['end_cap']:>12.2f}")
    print("-" * W)
    for act, dd, m, hi in grid_results:
        star = " ★" if hi else "  "
        print(f"{star} {act:>5.0f}  {dd:>5.1f}   {m['sharpe']:>7.3f}  {m['sortino']:>8.3f}  "
              f"{m['cagr']:>8.2f}  {m['maxdd']:>7.2f}  {m['trades']:>7}  "
              f"{m['pd_exits']:>5}  {m['end_cap']:>12.2f}")
    print("=" * W)
    print("  ★ = highlighted variants")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# HTML output
# ─────────────────────────────────────────────────────────────────────────────
def _build_html(ticker: str, source: str, trade_start: str,
                base_m: dict, grid_results: list[tuple],
                output_path: Path) -> None:
    def _td_color(val: float, ref: float, higher_is_better: bool = True) -> str:
        if higher_is_better:
            color = "#2d6a2d" if val > ref * 1.02 else ("#6a2d2d" if val < ref * 0.98 else "#2b2b3b")
        else:
            color = "#2d6a2d" if val < ref * 0.98 else ("#6a2d2d" if val > ref * 1.02 else "#2b2b3b")
        return f'style="background:{color}"'

    rows = ""
    for act, dd, m, hi in grid_results:
        star  = "★ " if hi else ""
        ro    = f'style="background:#1e1e30"' if not hi else 'style="background:#1e2e1e"'
        rows += (
            f"<tr {ro}>"
            f"<td>{star}{act:.0f}%</td>"
            f"<td>{dd:.1f}%</td>"
            f"<td {_td_color(m['sharpe'],  base_m['sharpe'])}>{m['sharpe']:.3f}</td>"
            f"<td {_td_color(m['sortino'], base_m['sortino'])}>{m['sortino']:.3f}</td>"
            f"<td {_td_color(m['cagr'],    base_m['cagr'])}>{m['cagr']:.2f}%</td>"
            f"<td {_td_color(m['maxdd'],   base_m['maxdd'], higher_is_better=False)}>{m['maxdd']:.2f}%</td>"
            f"<td>{m['trades']}</td>"
            f"<td>{m['pd_exits']}</td>"
            f"<td>{m['end_cap']:,.2f}</td>"
            f"</tr>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Peak-DD Comparison – {ticker}</title>
<style>
  body  {{ background:#12121f; color:#d0d0e0; font-family:monospace; padding:20px }}
  h1,h2 {{ color:#7090ff }}
  table {{ border-collapse:collapse; width:100%; margin-top:12px }}
  th    {{ background:#1a1a2e; color:#8899cc; padding:6px 10px; text-align:right }}
  td    {{ padding:5px 10px; text-align:right; border-bottom:1px solid #2a2a3a }}
  .baseline td {{ background:#252540 !important; color:#ffdd88 }}
  .note {{ color:#8888aa; font-size:0.85em; margin-top:10px }}
</style>
</head>
<body>
<h1>Peak-Drawdown Stop – Grid Scan</h1>
<h2>{ticker} | {source} | trade window: {trade_start} → today</h2>
<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<table>
<thead>
<tr>
  <th>Act%</th><th>DD%</th>
  <th>Sharpe</th><th>Sortino</th><th>CAGR%</th>
  <th>MaxDD%</th><th>Trades</th><th>PD exits</th><th>EndCap $</th>
</tr>
</thead>
<tbody>
<tr class="baseline">
  <td>BASE</td><td>—</td>
  <td>{base_m['sharpe']:.3f}</td>
  <td>{base_m['sortino']:.3f}</td>
  <td>{base_m['cagr']:.2f}%</td>
  <td>{base_m['maxdd']:.2f}%</td>
  <td>{base_m['trades']}</td>
  <td>—</td>
  <td>{base_m['end_cap']:,.2f}</td>
</tr>
{rows}
</tbody>
</table>

<p class="note">
  Act% = min unrealised gain before PD activates (unleveraged) |
  DD% = max allowed drop from peak_close |
  ★ = highlighted variants |
  PD exits = trades closed via Peak-Drawdown stop
</p>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"HTML saved → {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker",  default="BTCUSDT")
    parser.add_argument("--source",  default="yfinance", choices=["yfinance", "bybit"])
    parser.add_argument("--start",   default="2021-01-01")
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--output",  default="results/backtest_peak_dd_comparison.html")
    args = parser.parse_args()

    ticker      = args.ticker
    source      = args.source
    trade_start = pd.Timestamp(args.start)

    # ── Load data ────────────────────────────────────────────────────────
    print(f"\nLoading {ticker} via {source} (full history for warmup)…")
    df = get_all(ticker, source=source)
    print(f"  {len(df)} bars  [{df.index[0].date()} → {df.index[-1].date()}]")
    print(f"  Trade window starts : {trade_start.date()}")
    print(f"  Data source         : {source}")

    # ── Base params ──────────────────────────────────────────────────────
    params_base = get_ticker_params(ticker)
    n_years = (df.index[-1] - trade_start).days / 365.25

    # ── Baseline ─────────────────────────────────────────────────────────
    print(f"\nRunning Baseline AMB (peak_dd_enable=False)…")
    base_trades = run_strategy(df, params_base, trade_start=trade_start)
    print(f"  {len(base_trades)} trades  P/L {_equity_curve(base_trades, params_base.start_capital)[-1]/params_base.start_capital*100-100:.2f}%")
    base_m = _run_metrics(base_trades, params_base, trade_start, n_years)

    # ── Grid scan ────────────────────────────────────────────────────────
    n_combos = len(ACTIVATE_PCTS) * len(PEAK_DD_PCTS)
    print(f"\nGrid scan: {len(ACTIVATE_PCTS)} × {len(PEAK_DD_PCTS)} = {n_combos} combinations…")

    grid_results: list[tuple] = []
    for act in ACTIVATE_PCTS:
        for dd in PEAK_DD_PCTS:
            p = dataclasses.replace(
                params_base,
                peak_dd_enable       = True,
                peak_dd_activate_pct = act,
                peak_dd_pct          = dd,
            )
            trades = run_strategy(df, p, trade_start=trade_start)
            m      = _run_metrics(trades, p, trade_start, n_years)
            hi     = (act, dd) in HIGHLIGHTS
            grid_results.append((act, dd, m, hi))

    # ── Print ────────────────────────────────────────────────────────────
    _print_grid(base_m, grid_results)

    # ── HTML ─────────────────────────────────────────────────────────────
    if not args.no_html:
        out = Path(__file__).parent / args.output
        _build_html(ticker, source, str(trade_start.date()),
                    base_m, grid_results, out)


if __name__ == "__main__":
    main()

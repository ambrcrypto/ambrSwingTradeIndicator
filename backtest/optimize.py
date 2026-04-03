"""
optimize.py – Grid search over AMBParams parameter space.

Runs all combinations, saves every result row to CSV so nothing is lost.
Results can be filtered/sorted later.

Two modes:
  "quick"  – focused grid, ~300–800 combos per ticker/period
  "full"   – extended grid, ~3000–6000 combos per ticker/period

Primary sort: Calmar ratio (Annualized Return / MaxDD)
              → maximises return while controlling drawdown
              → liquidation-risk runs are flagged and ranked last

Filter: min_trades >= 5 (exclude single-trade wonders)
"""

from __future__ import annotations
import itertools
import csv
import json
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
import pandas as pd

from .strategy_amb import AMBParams
from .engine import backtest
from .data import get_slice, get_periods

BASE_DIR    = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Parameter grids
# ─────────────────────────────────────────────────────────────────────────────

# (sl_enable, sl_risk_pct) combinations
_SL_QUICK = [
    (False, 2.0),
    (True,  4.0),
    (True,  6.0),
    (True,  9.0),
    (True,  12.0),
]

_SL_FULL = [
    (False, 2.0),
    (True,  2.0),
    (True,  4.0),
    (True,  6.0),
    (True,  8.0),
    (True,  9.0),
    (True,  12.0),
    (True,  15.0),
]

GRIDS: dict[str, dict] = {
    "quick": {
        "slow_ma_len":    [100, 130, 160],
        "slow_ma_type":   ["SMA"],
        "fast_ma_len":    [30, 44, 60],
        "fast_ma_type":   ["SMA"],
        "allow_longs":    [True],
        "allow_shorts":   [True, False],
        "leverage_long":  [2.0, 3.0, 4.0],
        "leverage_short": [1.0, 1.25, 2.0],
        "sl_configs":     _SL_QUICK,
    },
    "full": {
        "slow_ma_len":    [80, 100, 120, 130, 150, 180],
        "slow_ma_type":   ["SMA", "EMA"],
        "fast_ma_len":    [20, 30, 44, 50, 60],
        "fast_ma_type":   ["SMA", "EMA"],
        "allow_longs":    [True],
        "allow_shorts":   [True, False],
        "leverage_long":  [1.0, 2.0, 3.0, 4.0, 5.0],
        "leverage_short": [1.0, 1.25, 1.5, 2.0],
        "sl_configs":     _SL_FULL,
    },
}


def _grid_params(mode: str = "quick") -> list[AMBParams]:
    """Generate all AMBParams combinations for the given grid mode."""
    g = GRIDS[mode]
    combos = []
    for (
        slow_len, slow_type,
        fast_len, fast_type,
        allow_l, allow_s,
        lev_l, lev_s,
        (sl_en, sl_risk),
    ) in itertools.product(
        g["slow_ma_len"], g["slow_ma_type"],
        g["fast_ma_len"], g["fast_ma_type"],
        g["allow_longs"], g["allow_shorts"],
        g["leverage_long"], g["leverage_short"],
        g["sl_configs"],
    ):
        # Skip if fast MA >= slow MA (meaningless)
        if fast_len >= slow_len:
            continue
        combos.append(AMBParams(
            slow_ma_len    = slow_len,
            slow_ma_type   = slow_type,
            fast_ma_len    = fast_len,
            fast_ma_type   = fast_type,
            allow_longs    = allow_l,
            allow_shorts   = allow_s,
            leverage_long  = lev_l,
            leverage_short = lev_s,
            sl_enable      = sl_en,
            sl_risk_pct    = sl_risk,
        ))
    return combos


# ─────────────────────────────────────────────────────────────────────────────
# Single period optimization
# ─────────────────────────────────────────────────────────────────────────────

def run_period(
    ticker:      str,
    period_name: str,
    start:       str,
    end:         str,
    mode:        str = "quick",
    min_trades:  int = 5,
    sort_by:     str = "calmar",  # "calmar" | "pl_pct" | "sharpe_trade"
) -> list[dict]:
    """
    Run full grid for one ticker + period.
    Returns list of result dicts, sorted by sort_by (best first).
    Saves full CSV to results/.
    Liquidation-risk runs (MaxDD >= 80%) are always ranked last.
    """
    df = get_slice(ticker, start, end, warmup=True)
    # Count bars in trade window for reporting (warmup data is excluded)
    n_window = len(df[df.index >= pd.Timestamp(start)]) if start else len(df)
    if n_window < 60:
        print(f"  ⚠ Not enough data for {ticker} / {period_name} ({n_window} bars in window)")
        return []

    params_list = _grid_params(mode)
    results: list[dict] = []

    desc = f"{ticker:<8} {period_name:<22}"
    for params in tqdm(params_list, desc=desc, ncols=90, leave=False):
        row = backtest(df, params, start, end, trade_start=start)
        row["ticker"]      = ticker
        row["period_name"] = period_name
        row["mode"]        = mode
        results.append(row)

    # ── Filter minimum trades ──────────────────────────────────────────────
    results = [r for r in results if r["trades"] >= min_trades]

    # ── Sort: liq_risk last, then by metric descending ────────────────────
    results.sort(key=lambda r: (r["liq_risk"], -r.get(sort_by, 0)))

    # ── Save CSV ──────────────────────────────────────────────────────────
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_t = ticker.replace("-", "_").replace("/", "_")
    csv_path = RESULTS_DIR / f"{safe_t}_{period_name}_{mode}_{ts}.csv"
    _save_csv(results, csv_path)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Multi-period / multi-ticker optimization
# ─────────────────────────────────────────────────────────────────────────────

def run_all(
    tickers:    list[str],
    periods:    list[str] | None = None,    # None = all available
    mode:       str = "quick",
    min_trades: int = 5,
    sort_by:    str = "calmar",
    top_n:      int = 10,
) -> dict[str, dict[str, list[dict]]]:
    """
    Run optimization for all tickers × periods.

    Returns nested dict: results[ticker][period_name] = top_n rows
    Also saves per-ticker best-params JSON for easy Pine Script transfer.
    """
    all_results: dict[str, dict[str, list[dict]]] = {}

    for ticker in tickers:
        avail = get_periods(ticker)
        target_periods = periods or list(avail.keys())
        all_results[ticker] = {}

        for pname in target_periods:
            if pname not in avail:
                continue
            start, end = avail[pname]
            rows = run_period(ticker, pname, start, end, mode, min_trades, sort_by)
            all_results[ticker][pname] = rows[:top_n]

        # ── Save best params JSON per ticker ──────────────────────────────
        _save_best_json(ticker, all_results[ticker], sort_by)

    return all_results


# ─────────────────────────────────────────────────────────────────────────────
# Cross-period robustness check
# ─────────────────────────────────────────────────────────────────────────────

def cross_period_check(
    ticker:  str,
    params:  AMBParams,
    mode:    str = "quick",
) -> dict[str, dict]:
    """
    Given a specific set of params, run them across ALL available periods
    for a ticker and return metrics per period.
    Useful to test whether a 'best' param set is robust across market regimes.
    """
    avail = get_periods(ticker)
    result = {}
    for pname, (start, end) in avail.items():
        df = get_slice(ticker, start, end, warmup=True)
        if len(df) < 60:
            continue
        result[pname] = backtest(df, params, start, end, trade_start=start)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# CSV / JSON helpers
# ─────────────────────────────────────────────────────────────────────────────

def _save_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _save_best_json(
    ticker: str,
    period_results: dict[str, list[dict]],
    sort_by: str,
) -> None:
    """Save the #1 result per period as a JSON file for Pine Script reference."""
    best: dict[str, dict] = {}
    for pname, rows in period_results.items():
        if rows:
            best[pname] = rows[0]   # already sorted

    safe_t = ticker.replace("-", "_").replace("/", "_")
    json_path = RESULTS_DIR / f"best_{safe_t}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2, default=str)


def load_results(csv_path: str | Path) -> list[dict]:
    """Load a results CSV back into a list of dicts."""
    with open(csv_path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

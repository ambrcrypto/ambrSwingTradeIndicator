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
from .data import get_slice, get_periods, ROBUSTNESS_EXCLUDE

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

# BTC-specific SL configs: sl always enabled (no noSL baseline)
_SL_BTC_QUICK = [
    (True,  4.0),
    (True,  6.0),
    (True,  8.0),   # added: user confirmed 8% > 9%
    (True,  9.0),
    (True,  12.0),
]

_SL_BTC_FULL = [
    (True,  3.0),
    (True,  4.0),
    (True,  6.0),
    (True,  8.0),
    (True,  9.0),
    (True,  12.0),
    (True,  15.0),
]

_SL_EQUITY_QUICK = [
    (False, 2.0),
    (True,  4.0),
    (True,  8.0),
    (True,  12.0),
    (True,  15.0),
]

_SL_EQUITY_FULL = [
    (False, 2.0),
    (True,  4.0),
    (True,  6.0),
    (True,  8.0),
    (True,  12.0),
    (True,  15.0),
]

# ── ATR-based SL configurations: (atr_sl_enable, atr_sl_len, atr_sl_mult) ─────────────────
_ATR_SL_QUICK = [
    (False, 14, 2.5),   # baseline: no SL (control group)
    (True,  7,  2.0),
    (True,  7,  2.5),
    (True,  10, 2.0),
    (True,  10, 2.5),
    (True,  14, 1.5),
    (True,  14, 2.0),
    (True,  14, 2.5),
    (True,  14, 3.0),
    (True,  20, 2.0),
    (True,  20, 2.5),
    (True,  20, 3.0),
    (True,  28, 2.5),
    (True,  28, 3.5),
]

_ATR_SL_FULL = [
    (False, 14, 2.5),
    (True,  5,  1.5),
    (True,  5,  2.0),
    (True,  7,  1.5),
    (True,  7,  2.0),
    (True,  7,  2.5),
    (True,  10, 1.5),
    (True,  10, 2.0),
    (True,  10, 2.5),
    (True,  10, 3.0),
    (True,  14, 1.5),
    (True,  14, 2.0),
    (True,  14, 2.5),
    (True,  14, 3.0),
    (True,  14, 3.5),
    (True,  20, 2.0),
    (True,  20, 2.5),
    (True,  20, 3.0),
    (True,  20, 3.5),
    (True,  28, 2.0),
    (True,  28, 2.5),
    (True,  28, 3.0),
    (True,  28, 3.5),
]

GRIDS: dict[str, dict] = {
    "quick": {
        "slow_ma_len":    [100, 130, 160],
        "slow_ma_type":   ["SMA"],
        "fast_ma_len":    [30, 44, 60],
        "fast_ma_type":   ["SMA"],
        "use_fast_ma":    [True],
        "signal_tf":      ["D"],
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
        "use_fast_ma":    [True],
        "signal_tf":      ["D"],
        "allow_longs":    [True],
        "allow_shorts":   [True, False],
        "leverage_long":  [1.0, 2.0, 3.0, 4.0, 5.0],
        "leverage_short": [1.0, 1.25, 1.5, 2.0],
        "sl_configs":     _SL_FULL,
    },
    # ── Equity / ETF grids: adds use_fast_ma + signal_tf dimensions ────────
    "equity_quick": {
        "slow_ma_len":    [100, 130, 160, 200],
        "slow_ma_type":   ["SMA", "EMA"],
        "fast_ma_len":    [20, 44, 60],
        "fast_ma_type":   ["SMA"],
        "use_fast_ma":    [True, False],   # Dual MA vs. Slow MA only
        "signal_tf":      ["D", "W"],      # Daily vs. weekly signals
        "allow_longs":    [True],
        "allow_shorts":   [True, False],
        "leverage_long":  [2.0, 3.0, 4.0],
        "leverage_short": [1.0],
        "sl_configs":     _SL_EQUITY_QUICK,
    },
    "equity_full": {
        "slow_ma_len":    [80, 100, 130, 160, 200],
        "slow_ma_type":   ["SMA", "EMA"],
        "fast_ma_len":    [20, 44, 60],
        "fast_ma_type":   ["SMA"],
        "use_fast_ma":    [True, False],   # Dual MA vs. Slow MA only
        "signal_tf":      ["D", "W"],      # Daily vs. weekly signals
        "allow_longs":    [True],
        "allow_shorts":   [True, False],
        "leverage_long":  [2.0, 3.0, 4.0],
        "leverage_short": [1.0, 1.25],
        "sl_configs":     _SL_EQUITY_FULL,
    },
    # ── BTC-specific grids: allow_shorts=True, sl=True, use_fast_ma=True fixed ─────
    "btc_quick": {
        "slow_ma_len":    [100, 130, 160],
        "slow_ma_type":   ["SMA"],
        "fast_ma_len":    [30, 44, 60],
        "fast_ma_type":   ["SMA"],
        "use_fast_ma":    [True],
        "signal_tf":      ["D"],
        "allow_longs":    [True],
        "allow_shorts":   [True],          # always True for BTC
        "leverage_long":  [2.0, 3.0, 4.0],
        "leverage_short": [0.5, 1.0, 1.25, 2.0],
        "sl_configs":     _SL_BTC_QUICK,   # sl always enabled
    },
    "btc_full": {
        "slow_ma_len":    [80, 100, 120, 130, 150, 180],
        "slow_ma_type":   ["SMA", "EMA"],
        "fast_ma_len":    [20, 30, 44, 50, 60],
        "fast_ma_type":   ["SMA", "EMA"],
        "use_fast_ma":    [True],
        "signal_tf":      ["D"],
        "allow_longs":    [True],
        "allow_shorts":   [True],          # always True for BTC
        "leverage_long":  [1.0, 2.0, 3.0, 4.0, 5.0],
        "leverage_short": [1.0, 1.25, 1.5, 2.0],
        "sl_configs":     _SL_BTC_FULL,    # sl always enabled
    },
    # ── ATR-SL grids: same MA/leverage space as quick/full, ATR-based stop loss ──────
    "atr_quick": {
        "slow_ma_len":    [100, 130, 160],
        "slow_ma_type":   ["SMA"],
        "fast_ma_len":    [30, 44, 60],
        "fast_ma_type":   ["SMA"],
        "use_fast_ma":    [True],
        "signal_tf":      ["D"],
        "allow_longs":    [True],
        "allow_shorts":   [True, False],
        "leverage_long":  [2.0, 3.0, 4.0],
        "leverage_short": [1.0, 1.25, 2.0],
        "atr_sl_configs": _ATR_SL_QUICK,
    },
    "atr_full": {
        "slow_ma_len":    [80, 100, 120, 130, 150, 180],
        "slow_ma_type":   ["SMA", "EMA"],
        "fast_ma_len":    [20, 30, 44, 50, 60],
        "fast_ma_type":   ["SMA", "EMA"],
        "use_fast_ma":    [True],
        "signal_tf":      ["D"],
        "allow_longs":    [True],
        "allow_shorts":   [True, False],
        "leverage_long":  [1.0, 2.0, 3.0, 4.0, 5.0],
        "leverage_short": [1.0, 1.25, 1.5, 2.0],
        "atr_sl_configs": _ATR_SL_FULL,
    },
}


def _grid_params(mode: str = "quick") -> list[AMBParams]:
    """Generate all AMBParams combinations for the given grid mode."""
    g = GRIDS[mode]
    combos = []

    use_fast_ma_values = g.get("use_fast_ma", [True])
    signal_tf_values   = g.get("signal_tf",   ["D"])
    is_atr_mode        = "atr_sl_configs" in g
    sl_iter            = g["atr_sl_configs"] if is_atr_mode else g["sl_configs"]

    for use_fma in use_fast_ma_values:
        # When Fast MA is disabled, fast_len/fast_type don't affect the strategy.
        # Use a single canonical placeholder to avoid redundant runs.
        if use_fma:
            fast_combos = list(itertools.product(g["fast_ma_len"], g["fast_ma_type"]))
        else:
            fast_combos = [(44, "SMA")]  # placeholder, ignored by run_strategy

        for (
            slow_len, slow_type,
            allow_l, allow_s,
            lev_l, lev_s,
            sl_config,
            signal_tf,
            (fast_len, fast_type),
        ) in itertools.product(
            g["slow_ma_len"], g["slow_ma_type"],
            g["allow_longs"], g["allow_shorts"],
            g["leverage_long"], g["leverage_short"],
            sl_iter,
            signal_tf_values,
            fast_combos,
        ):
            # Skip meaningless combos: fast MA must be shorter than slow MA
            if use_fma and fast_len >= slow_len:
                continue

            if is_atr_mode:
                atr_en, atr_len, atr_mult = sl_config
                combos.append(AMBParams(
                    slow_ma_len    = slow_len,
                    slow_ma_type   = slow_type,
                    fast_ma_len    = fast_len,
                    fast_ma_type   = fast_type,
                    use_fast_ma    = use_fma,
                    allow_longs    = allow_l,
                    allow_shorts   = allow_s,
                    leverage_long  = lev_l,
                    leverage_short = lev_s,
                    sl_enable      = False,  # % SL disabled in ATR mode
                    sl_risk_pct    = 9.0,    # placeholder, not used
                    atr_sl_enable  = atr_en,
                    atr_sl_len     = atr_len,
                    atr_sl_mult    = atr_mult,
                    signal_tf      = signal_tf,
                ))
            else:
                sl_en, sl_risk = sl_config
                combos.append(AMBParams(
                    slow_ma_len    = slow_len,
                    slow_ma_type   = slow_type,
                    fast_ma_len    = fast_len,
                    fast_ma_type   = fast_type,
                    use_fast_ma    = use_fma,
                    allow_longs    = allow_l,
                    allow_shorts   = allow_s,
                    leverage_long  = lev_l,
                    leverage_short = lev_s,
                    sl_enable      = sl_en,
                    sl_risk_pct    = sl_risk,
                    signal_tf      = signal_tf,
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
# Multi-period robustness optimizer
# ─────────────────────────────────────────────────────────────────────────────

def run_robustness(
    ticker:     str,
    mode:       str = "quick",
    min_trades: int = 3,
    periods:    list[str] | None = None,
    sort_by:    str = "min_calmar",   # "min_calmar" | "mean_calmar"
) -> list[dict]:
    """
    Multi-period robustness optimizer.

    Runs every param combo across ALL specified periods (default: all except 'full').
    Scores each combo by its worst-case Calmar – the param set that performs best
    in its weakest period wins.  Only combos with >= min_trades in EVERY period
    are included.

    sort_by:
      "min_calmar"  – maximize worst-case Calmar (most conservative, default)
      "mean_calmar" – maximize average Calmar across periods

    Returns list of dicts sorted best-first, CSV saved to results/.
    Each row: params + min_calmar / mean_calmar / n_positive + per-period calmar/ann/maxdd.
    """
    avail = get_periods(ticker)
    # Default: exclude cumulative/overlapping periods (see ROBUSTNESS_EXCLUDE in data.py)
    if periods is None:
        periods = [p for p in avail.keys() if p not in ROBUSTNESS_EXCLUDE]

    # Load data for all periods upfront (avoid repeated I/O per combo)
    period_data: dict[str, tuple] = {}
    for pname in periods:
        if pname not in avail:
            continue
        start, end = avail[pname]
        df = get_slice(ticker, start, end, warmup=True)
        ref_ts   = pd.Timestamp(start) if start else df.index[0]
        n_window = len(df[df.index >= ref_ts])
        if n_window < 60:
            continue
        period_data[pname] = (start, end, df)

    if not period_data:
        return []

    pnames      = list(period_data.keys())
    params_list = _grid_params(mode)
    results: list[dict] = []

    desc = f"{ticker:<8} robustness ({len(pnames)} periods)"
    for params in tqdm(params_list, desc=desc, ncols=90, leave=False):
        calmars: list[float]      = []
        period_metrics: dict[str, dict] = {}
        skip = False

        for pname in pnames:
            start, end, df = period_data[pname]
            row = backtest(df, params, start, end, trade_start=start)
            if row["trades"] < min_trades:
                skip = True
                break
            period_metrics[pname] = row
            calmars.append(float(row["calmar"]))

        if skip or not calmars:
            continue

        min_calmar  = min(calmars)
        mean_calmar = sum(calmars) / len(calmars)
        n_positive  = sum(1 for c in calmars if c > 0)

        combo_row: dict = {
            "min_calmar":  min_calmar,
            "mean_calmar": mean_calmar,
            "n_positive":  n_positive,
            "n_periods":   len(calmars),
        }
        combo_row.update(params.as_dict())
        for pname, m in period_metrics.items():
            combo_row[f"calmar_{pname}"]  = float(m["calmar"])
            combo_row[f"ann_{pname}"]     = float(m["ann_return"])
            combo_row[f"maxdd_{pname}"]   = float(m["max_dd"])
            combo_row[f"trades_{pname}"]  = int(m["trades"])

        results.append(combo_row)

    # Sort: profitable in most periods first, then by chosen metric
    if sort_by == "mean_calmar":
        results.sort(key=lambda r: (-r["n_positive"], -r["mean_calmar"]))
    else:  # min_calmar (default)
        results.sort(key=lambda r: (-r["n_positive"], -r["min_calmar"]))

    # Save CSV
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_t = ticker.replace("-", "_").replace("/", "_")
    csv_path = RESULTS_DIR / f"{safe_t}_robustness_{mode}_{ts}.csv"
    _save_csv(results, csv_path)

    return results


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

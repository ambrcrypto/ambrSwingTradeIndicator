from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

from .data import get_periods, get_slice
from .engine import compute_metrics
from .optimize import _grid_params
from .strategy_amb import AMBParams, run_strategy


BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def amb_baseline_from_pine() -> AMBParams:
    # Mirrors defaults in AMB Dual MA Signal.pine
    return AMBParams(
        slow_ma_len=130,
        slow_ma_type="EMA",
        fast_ma_len=60,
        fast_ma_type="SMA",
        allow_longs=True,
        allow_shorts=True,
        use_fast_ma=True,
        leverage_long=3.75,
        leverage_short=0.5,
        sl_enable=True,
        sl_risk_pct=3.0,
        atr_sl_enable=False,
        atr_entry_enable=False,
    )


def _default_btc_periods(source: str) -> list[str]:
    periods_all = get_periods("BTC-USD", source=source)
    pref = [
        "btc_p4_bull_2020_2021",
        "btc_p5_bear_2022",
        "btc_p6_bull_2023_2024",
        "btc_p7_current_2025",
    ]
    return [p for p in pref if p in periods_all]


def run_tournament(
    ticker: str = "BTC-USD",
    source: str = "bybit",
    mode: str = "btc_quick",
    periods: list[str] | None = None,
    min_trades: int = 8,
    refresh: bool = False,
    max_combos: int | None = None,
) -> tuple[list[dict], Path]:
    periods_all = get_periods(ticker, source=source)
    period_names = periods or _default_btc_periods(source=source)
    period_names = [p for p in period_names if p in periods_all]
    if not period_names:
        raise ValueError("No valid periods available")

    baseline = amb_baseline_from_pine()

    period_data: dict[str, tuple[pd.DataFrame, str, str, dict]] = {}
    for pname in period_names:
        start, end = periods_all[pname]
        df_warm = get_slice(ticker, start, end, warmup=True, source=source, force_refresh=refresh)
        base_trades = run_strategy(df_warm, baseline, trade_start=pd.Timestamp(start))
        base_metrics = compute_metrics(base_trades, baseline, start, end)
        period_data[pname] = (df_warm, start, end, base_metrics)

    candidates = _grid_params(mode)
    if max_combos is not None:
        candidates = candidates[: max(0, max_combos)]

    rows: list[dict] = []
    for params in candidates:
        per_metrics: dict[str, dict] = {}
        beat_pl_count = 0
        beat_dd_count = 0
        beat_both_count = 0
        valid = True

        for pname in period_names:
            df_warm, start, end, base_m = period_data[pname]
            trades = run_strategy(df_warm, params, trade_start=pd.Timestamp(start))
            m = compute_metrics(trades, params, start, end)
            per_metrics[pname] = m

            if m["trades"] < min_trades:
                valid = False

            beat_pl = m["pl_pct"] > base_m["pl_pct"]
            beat_dd = m["max_dd"] < base_m["max_dd"]
            if beat_pl:
                beat_pl_count += 1
            if beat_dd:
                beat_dd_count += 1
            if beat_pl and beat_dd:
                beat_both_count += 1

        if not valid:
            continue

        min_calmar = min(per_metrics[p]["calmar"] for p in period_names)
        mean_calmar = sum(per_metrics[p]["calmar"] for p in period_names) / len(period_names)
        worst_dd = max(per_metrics[p]["max_dd"] for p in period_names)
        min_pl = min(per_metrics[p]["pl_pct"] for p in period_names)

        row = {
            "ticker": ticker,
            "source": source,
            "mode": mode,
            "n_periods": len(period_names),
            "beat_pl_count": beat_pl_count,
            "beat_dd_count": beat_dd_count,
            "beat_both_count": beat_both_count,
            "hard_pass": beat_both_count == len(period_names),
            "min_calmar": round(min_calmar, 3),
            "mean_calmar": round(mean_calmar, 3),
            "worst_dd": round(worst_dd, 2),
            "min_pl": round(min_pl, 2),
            **params.as_dict(),
        }

        for pname in period_names:
            m = per_metrics[pname]
            bm = period_data[pname][3]
            row[f"pl_{pname}"] = round(m["pl_pct"], 2)
            row[f"maxdd_{pname}"] = round(m["max_dd"], 2)
            row[f"calmar_{pname}"] = round(m["calmar"], 3)
            row[f"trades_{pname}"] = int(m["trades"])
            row[f"base_pl_{pname}"] = round(bm["pl_pct"], 2)
            row[f"base_dd_{pname}"] = round(bm["max_dd"], 2)
            row[f"beat_both_{pname}"] = (m["pl_pct"] > bm["pl_pct"]) and (m["max_dd"] < bm["max_dd"])

        rows.append(row)

    rows.sort(
        key=lambda r: (
            int(r["hard_pass"]),
            r["beat_both_count"],
            r["min_calmar"],
            r["mean_calmar"],
        ),
        reverse=True,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"AMB_vs_BASE_{ticker.replace('-', '_')}_{source}_{mode}_{ts}.csv"
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        best_json = RESULTS_DIR / f"AMB_best_vs_BASE_{ticker.replace('-', '_')}_{source}_{mode}_{ts}.json"
        with best_json.open("w", encoding="utf-8") as f:
            json.dump(_json_safe(rows[0]), f, indent=2)

    return rows, csv_path

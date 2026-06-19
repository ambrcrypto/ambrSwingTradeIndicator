from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import date, datetime
from itertools import product
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from .data import get_all
from .engine import backtest
from .optimize import _grid_params
from .strategy_amb import AMBParams


BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def _window_dates(first_date: pd.Timestamp, last_date: pd.Timestamp) -> list[tuple[str, str, int]]:
	"""
	Build rolling windows anchored at 1-Apr each year:
	[year-1-04-01, year-04-01].
	Returns tuples: (start_iso, end_iso, anchor_year).
	"""
	windows: list[tuple[str, str, int]] = []
	for year in range(first_date.year + 1, last_date.year + 1):
		start = date(year - 1, 4, 1)
		end = date(year, 4, 1)
		if pd.Timestamp(start) >= first_date and pd.Timestamp(end) <= last_date:
			windows.append((start.isoformat(), end.isoformat(), year))
	return windows


def _key_for_sort(metric: str):
	return lambda r: r.get(metric, 0.0)


def _run_grid_for_window(
	ticker: str,
	source: str,
	start: str,
	end: str,
	params_list: list[AMBParams],
	metric: str,
) -> list[dict]:
	df = get_all(ticker, source=source)
	df = df[df.index <= pd.Timestamp(end)].copy()

	rows: list[dict] = []
	for p in params_list:
		row = backtest(df, p, start, end, trade_start=start)
		row["window_start"] = start
		row["window_end"] = end
		rows.append(row)

	rows.sort(key=_key_for_sort(metric), reverse=True)
	return rows


def _uniq_float(vals: list[float], lo: float | None = None) -> list[float]:
	out = sorted({round(v, 4) for v in vals})
	if lo is not None:
		out = [v for v in out if v >= lo]
	return out


def _fine_grid_around(best: AMBParams) -> list[AMBParams]:
	slow_vals = sorted(
		{
			max(20, best.slow_ma_len - 20),
			max(20, best.slow_ma_len - 10),
			best.slow_ma_len,
			best.slow_ma_len + 10,
			best.slow_ma_len + 20,
		}
	)
	fast_vals = sorted(
		{
			max(5, best.fast_ma_len - 10),
			max(5, best.fast_ma_len - 5),
			best.fast_ma_len,
			best.fast_ma_len + 5,
			best.fast_ma_len + 10,
		}
	)
	lev_long_vals = _uniq_float(
		[
			best.leverage_long - 0.5,
			best.leverage_long - 0.25,
			best.leverage_long,
			best.leverage_long + 0.25,
			best.leverage_long + 0.5,
		],
		lo=0.1,
	)
	lev_short_vals = _uniq_float(
		[
			best.leverage_short - 0.5,
			best.leverage_short - 0.25,
			best.leverage_short,
			best.leverage_short + 0.25,
			best.leverage_short + 0.5,
		],
		lo=0.1,
	)
	sl_vals = _uniq_float(
		[
			best.sl_risk_pct - 1.0,
			best.sl_risk_pct - 0.5,
			best.sl_risk_pct,
			best.sl_risk_pct + 0.5,
			best.sl_risk_pct + 1.0,
		],
		lo=0.1,
	)

	params: list[AMBParams] = []
	for slow, fast, ll, ls, sl in product(
		slow_vals,
		fast_vals,
		lev_long_vals,
		lev_short_vals,
		sl_vals,
	):
		if fast >= slow:
			continue
		p = AMBParams(
			slow_ma_len=slow,
			slow_ma_type=best.slow_ma_type,
			fast_ma_len=fast,
			fast_ma_type=best.fast_ma_type,
			allow_longs=best.allow_longs,
			allow_shorts=best.allow_shorts,
			use_fast_ma=best.use_fast_ma,
			leverage_long=ll,
			leverage_short=ls,
			sl_enable=best.sl_enable,
			sl_risk_pct=sl,
			signal_tf=best.signal_tf,
			atr_sl_enable=False,
			atr_entry_enable=False,
			trail_sl_enable=False,
			peak_dd_enable=False,
		)
		params.append(p)
	return params


def _extract_params(row: dict) -> AMBParams:
	return AMBParams(
		slow_ma_len=int(row["slow_ma_len"]),
		slow_ma_type=row["slow_ma_type"],
		fast_ma_len=int(row["fast_ma_len"]),
		fast_ma_type=row["fast_ma_type"],
		allow_longs=bool(row["allow_longs"]),
		allow_shorts=bool(row["allow_shorts"]),
		use_fast_ma=bool(row.get("use_fast_ma", True)),
		leverage_long=float(row["leverage_long"]),
		leverage_short=float(row["leverage_short"]),
		sl_enable=bool(row["sl_enable"]),
		sl_risk_pct=float(row["sl_risk_pct"]),
		signal_tf=row.get("signal_tf", "D"),
		atr_sl_enable=False,
		atr_entry_enable=False,
		trail_sl_enable=False,
		peak_dd_enable=False,
	)


def _write_csv(path: Path, rows: list[dict]) -> None:
	if not rows:
		return
	keys = sorted({k for r in rows for k in r.keys()})
	with path.open("w", newline="", encoding="utf-8") as f:
		w = csv.DictWriter(f, fieldnames=keys)
		w.writeheader()
		w.writerows(rows)


def _append_csv(path: Path, rows: list[dict], all_keys: list[str]) -> None:
	"""Append rows to an existing CSV (or create it with header on first call)."""
	if not rows:
		return
	write_header = not path.exists() or path.stat().st_size == 0
	with path.open("a", newline="", encoding="utf-8") as f:
		w = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
		if write_header:
			w.writeheader()
		w.writerows(rows)


def _drift_summary(best_rows: list[dict]) -> dict:
	if len(best_rows) <= 1:
		return {
			"n_windows": len(best_rows),
			"avg_delta_slow": 0.0,
			"avg_delta_fast": 0.0,
			"avg_delta_ll": 0.0,
			"avg_delta_ls": 0.0,
			"avg_delta_sl": 0.0,
		}

	deltas = {
		"slow": [],
		"fast": [],
		"ll": [],
		"ls": [],
		"sl": [],
	}
	for i in range(1, len(best_rows)):
		prev = best_rows[i - 1]
		cur = best_rows[i]
		deltas["slow"].append(abs(int(cur["slow_ma_len"]) - int(prev["slow_ma_len"])))
		deltas["fast"].append(abs(int(cur["fast_ma_len"]) - int(prev["fast_ma_len"])))
		deltas["ll"].append(abs(float(cur["leverage_long"]) - float(prev["leverage_long"])))
		deltas["ls"].append(abs(float(cur["leverage_short"]) - float(prev["leverage_short"])))
		deltas["sl"].append(abs(float(cur["sl_risk_pct"]) - float(prev["sl_risk_pct"])))

	return {
		"n_windows": len(best_rows),
		"avg_delta_slow": round(sum(deltas["slow"]) / len(deltas["slow"]), 3),
		"avg_delta_fast": round(sum(deltas["fast"]) / len(deltas["fast"]), 3),
		"avg_delta_ll": round(sum(deltas["ll"]) / len(deltas["ll"]), 3),
		"avg_delta_ls": round(sum(deltas["ls"]) / len(deltas["ls"]), 3),
		"avg_delta_sl": round(sum(deltas["sl"]) / len(deltas["sl"]), 3),
	}


def _boolish(v) -> bool:
	if isinstance(v, bool):
		return v
	if isinstance(v, str):
		return v.lower() in {"1", "true", "yes", "y"}
	return bool(v)


def _long_short_sanity(
	ticker: str,
	source: str,
	best_rows: list[dict],
) -> list[dict]:
	checks: list[dict] = []
	for r in best_rows:
		p = _extract_params(r)
		p.allow_shorts = False
		rows = _run_grid_for_window(
			ticker=ticker,
			source=source,
			start=r["window_start"],
			end=r["window_end"],
			params_list=[p],
			metric="pl_pct",
		)
		long_only = rows[0] if rows else {"pl_pct": 0.0}
		checks.append(
			{
				"window_start": r["window_start"],
				"window_end": r["window_end"],
				"best_pl_long_short": r["pl_pct"],
				"same_params_long_only_pl": long_only["pl_pct"],
				"delta_pl": round(float(r["pl_pct"]) - float(long_only["pl_pct"]), 3),
			}
		)
	return checks


def main() -> None:
	ap = argparse.ArgumentParser(description="Rolling Apr-1 optimizer for AMB strategy")
	ap.add_argument("--ticker", default="BTCUSDT")
	ap.add_argument("--source", default="bybit", choices=["bybit", "yfinance"])
	ap.add_argument("--coarse-mode", default="btc_quick", choices=["quick", "full", "btc_quick", "btc_full"])
	ap.add_argument("--metric", default="pl_pct", choices=["pl_pct", "calmar", "ann_return", "sharpe_trade"])
	ap.add_argument("--top-k", type=int, default=3, help="Top coarse candidates kept per window for fine stage")
	ap.add_argument("--refresh", action="store_true")
	args = ap.parse_args()

	ts = datetime.now().strftime("%Y%m%d_%H%M%S")

	# Force cache refresh up-front once if requested.
	if args.refresh:
		_ = get_all(args.ticker, force_refresh=True, source=args.source)

	all_df = get_all(args.ticker, source=args.source)
	first_date = all_df.index[0]
	last_date = all_df.index[-1]

	windows = _window_dates(first_date, last_date)
	if not windows:
		raise SystemExit("No valid 1-Apr rolling windows found in available data.")

	coarse_pool = _grid_params(args.coarse_mode)
	print(
		f"Running rolling optimization for {args.ticker} [{args.source}] with {len(windows)} windows.\n"
		f"Signal assumption: daily checks at fixed 07:00 Europe/Zurich.\n"
		f"Coarse mode={args.coarse_mode}, combos/window={len(coarse_pool)}"
	)

	coarse_best_rows: list[dict] = []
	fine_best_rows: list[dict] = []

	# Determine CSV column schema once from a dry-run combo (no data needed).
	# We derive fieldnames lazily from the first window's results.
	_coarse_keys: list[str] = []
	_fine_keys: list[str] = []

	base = f"APRIL_ROLLING_{args.ticker.replace('-', '_').replace('/', '_')}_{args.source}_{ts}"
	path_coarse_all = RESULTS_DIR / f"{base}_coarse_all.csv"
	path_fine_all = RESULTS_DIR / f"{base}_fine_all.csv"
	path_coarse_best = RESULTS_DIR / f"{base}_coarse_best.csv"
	path_fine_best = RESULTS_DIR / f"{base}_fine_best.csv"
	path_ls = RESULTS_DIR / f"{base}_longshort_check.csv"
	path_summary = RESULTS_DIR / f"{base}_summary.json"
	path_report = RESULTS_DIR / f"{base}_report.html"

	for start, end, anchor_year in tqdm(windows, desc="Apr windows", ncols=90):
		coarse_rows = _run_grid_for_window(
			ticker=args.ticker,
			source=args.source,
			start=start,
			end=end,
			params_list=coarse_pool,
			metric=args.metric,
		)
		for row in coarse_rows:
			row["anchor_year"] = anchor_year
			row["stage"] = "coarse"

		# Build column schema from first window
		if not _coarse_keys and coarse_rows:
			_coarse_keys = sorted({k for r in coarse_rows for k in r.keys()})

		_append_csv(path_coarse_all, coarse_rows, _coarse_keys)

		top = coarse_rows[: max(1, args.top_k)]
		coarse_best = top[0]
		coarse_best_rows.append(coarse_best)
		_append_csv(path_coarse_best, [coarse_best], _coarse_keys)

		fine_pool: list[AMBParams] = []
		for t in top:
			fine_pool.extend(_fine_grid_around(_extract_params(t)))

		# Deduplicate fine params by dict fingerprint.
		seen = set()
		uniq_pool = []
		for p in fine_pool:
			key = json.dumps(asdict(p), sort_keys=True)
			if key not in seen:
				seen.add(key)
				uniq_pool.append(p)

		fine_rows = _run_grid_for_window(
			ticker=args.ticker,
			source=args.source,
			start=start,
			end=end,
			params_list=uniq_pool,
			metric=args.metric,
		)
		for row in fine_rows:
			row["anchor_year"] = anchor_year
			row["stage"] = "fine"

		if not _fine_keys and fine_rows:
			_fine_keys = sorted({k for r in fine_rows for k in r.keys()})

		_append_csv(path_fine_all, fine_rows, _fine_keys)
		fine_best_rows.append(fine_rows[0])
		_append_csv(path_fine_best, [fine_rows[0]], _fine_keys)

	drift = _drift_summary(fine_best_rows)
	ls_checks = _long_short_sanity(args.ticker, args.source, fine_best_rows)
	_write_csv(path_ls, ls_checks)

	summary = {
		"ticker": args.ticker,
		"source": args.source,
		"generated_at": datetime.now().isoformat(),
		"assumption_check_time": "07:00 Europe/Zurich",
		"metric": args.metric,
		"n_windows": len(windows),
		"coarse_mode": args.coarse_mode,
		"coarse_combos_per_window": len(coarse_pool),
		"drift": drift,
		"output_files": {
			"coarse_all": str(path_coarse_all),
			"fine_all": str(path_fine_all),
			"coarse_best": str(path_coarse_best),
			"fine_best": str(path_fine_best),
			"longshort_check": str(path_ls),
		},
		"best_latest_window": fine_best_rows[-1] if fine_best_rows else {},
	}
	def _json_default(obj):
		import numpy as np
		if isinstance(obj, (np.bool_, bool)):
			return bool(obj)
		if isinstance(obj, (np.integer,)):
			return int(obj)
		if isinstance(obj, (np.floating,)):
			return float(obj)
		raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

	with path_summary.open("w", encoding="utf-8") as f:
		json.dump(summary, f, indent=2, default=_json_default)

	# Generate HTML report
	from .generate_report import generate_html_report
	generate_html_report(
		path_coarse_all=path_coarse_all,
		path_fine_best=path_fine_best,
		path_ls=path_ls,
		path_out=path_report,
		ticker=args.ticker,
		source=args.source,
		metric=args.metric,
	)

	print("\nDone.")
	print(f"Summary JSON: {path_summary}")
	print(f"Fine best CSV: {path_fine_best}")
	print(f"HTML Report:  {path_report}")
	print(f"Drift avg deltas: {drift}")


if __name__ == "__main__":
	main()

"""
diagnose_discrepancy.py – Pine Script vs Python Trade-Count Diagnose

Exportiert für BTC-USD v1.6.1:
  1. trades_detail.csv       – alle Trades mit Datum, Preis, Typ, MA-Werten
  2. crossovers.csv          – alle MA-Crossover-Events mit Datum und Preisdaten
  3. ma_daily.csv            – tägl. Close/SlowMA/FastMA (für TradingView-Abgleich)
  4. summary.txt             – Zusammenfassung (Perioden, Trade-Counts, Exit-Typen)

Ausgabe: backtest/results/discrepancy/

Verwendung:
    cd ambrSwingTradeIndicator
    python -m backtest.diagnose_discrepancy
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from .data import get_slice, PERIODS
from .strategy_amb import AMBParams, _calc_ma, _calc_atr, _first_day_mask, Trade, run_strategy
from .ticker_config import TICKER_CONFIG

# ── Config ────────────────────────────────────────────────────────────────────
TICKER   = "BTC-USD"
# Test against both the period from the old BACKTEST_COMPARISON.md and the full current period
PERIODS_TO_TEST = {
    "v1.6.1_2021_to_2023": ("2021-04-14", "2023-10-31"),  # matches old comparison window
    "v1.6.1_2021_to_now":  ("2021-04-14", None),           # full current period
}

OUT_DIR = Path(__file__).parent / "results" / "discrepancy"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _run_with_crossovers(
    df: pd.DataFrame,
    params: AMBParams,
    trade_start: "pd.Timestamp | None" = None,
) -> tuple[list[Trade], pd.DataFrame]:
    """
    Run strategy AND record every crossover event for diagnostic output.
    Returns (trades, crossovers_df).
    """
    close_s = df["close"]
    close   = close_s.to_numpy(dtype=float)
    high    = df["high"].to_numpy(dtype=float)
    low_    = df["low"].to_numpy(dtype=float)
    dates   = df.index
    n       = len(df)

    slow_ma     = _calc_ma(close_s, params.slow_ma_len, params.slow_ma_type)
    fast_ma     = _calc_ma(close_s, params.fast_ma_len, params.fast_ma_type)
    signal_days = _first_day_mask(dates, params.signal_tf)

    crossovers: list[dict] = []

    for i in range(1, n):
        if np.isnan(slow_ma[i]) or np.isnan(fast_ma[i]):
            continue
        if np.isnan(slow_ma[i - 1]) or np.isnan(fast_ma[i - 1]):
            continue

        c  = close[i];  c0 = close[i - 1]
        s  = slow_ma[i]; s0 = slow_ma[i - 1]
        f  = fast_ma[i]; f0 = fast_ma[i - 1]

        if signal_days[i]:
            cross_above_slow = (c > s) and (c0 <= s0)
            cross_above_fast = (c > f) and (c0 <= f0) and (c > s)   # Re-Entry condition
            cross_below_slow = (c < s) and (c0 >= s0)
            cross_below_fast = (c < f) and (c0 >= f0) and (c < s)   # Re-Entry Short
        else:
            cross_above_slow = cross_above_fast = cross_below_slow = cross_below_fast = False

        if cross_above_slow:
            crossovers.append({"date": dates[i], "type": "CROSS_ABOVE_SLOW",
                                "close": c, "slow_ma": s, "fast_ma": f,
                                "dist_to_slow_pct": round((c - s) / s * 100, 3)})
        if cross_above_fast:
            crossovers.append({"date": dates[i], "type": "CROSS_ABOVE_FAST",
                                "close": c, "slow_ma": s, "fast_ma": f,
                                "dist_to_slow_pct": round((c - s) / s * 100, 3)})
        if cross_below_slow:
            crossovers.append({"date": dates[i], "type": "CROSS_BELOW_SLOW",
                                "close": c, "slow_ma": s, "fast_ma": f,
                                "dist_to_slow_pct": round((c - s) / s * 100, 3)})
        if cross_below_fast:
            crossovers.append({"date": dates[i], "type": "CROSS_BELOW_FAST",
                                "close": c, "slow_ma": s, "fast_ma": f,
                                "dist_to_slow_pct": round((c - s) / s * 100, 3)})

    crossovers_df = pd.DataFrame(crossovers).set_index("date") if crossovers else pd.DataFrame()

    # Run the actual strategy through the existing run_strategy function
    trades = run_strategy(df, params, trade_start=trade_start)
    return trades, crossovers_df


def _build_ma_daily(df: pd.DataFrame, params: AMBParams) -> pd.DataFrame:
    """Return daily close / slow_ma / fast_ma for TradingView comparison."""
    close_s  = df["close"]
    slow_ma  = _calc_ma(close_s, params.slow_ma_len, params.slow_ma_type)
    fast_ma  = _calc_ma(close_s, params.fast_ma_len, params.fast_ma_type)
    return pd.DataFrame({
        "close":   close_s.values,
        f"slow_ma_{params.slow_ma_len}{params.slow_ma_type}": slow_ma,
        f"fast_ma_{params.fast_ma_len}{params.fast_ma_type}": fast_ma,
    }, index=df.index)


def _trades_to_df(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    rows = []
    for t in trades:
        rows.append({
            "entry_date":  t.entry_date.date(),
            "exit_date":   t.exit_date.date(),
            "direction":   "LONG" if t.direction == 1 else "SHORT",
            "entry_price": round(t.entry_price, 2),
            "exit_price":  round(t.exit_price, 2),
            "exit_type":   t.exit_type,
            "pct":         round(t.pct, 2),
        })
    return pd.DataFrame(rows)


def _print_summary(period_label: str, trades: list[Trade],
                   crossovers_df: pd.DataFrame, params: AMBParams,
                   start: str, end: str | None) -> str:
    n_long     = sum(1 for t in trades if t.direction == 1)
    n_short    = sum(1 for t in trades if t.direction == -1)
    n_sl       = sum(1 for t in trades if t.exit_type == "SL")
    n_cl       = sum(1 for t in trades if t.exit_type == "CL")
    n_cs       = sum(1 for t in trades if t.exit_type == "CS")
    n_cross_as = len(crossovers_df[crossovers_df["type"] == "CROSS_ABOVE_SLOW"]) if len(crossovers_df) else 0
    n_cross_af = len(crossovers_df[crossovers_df["type"] == "CROSS_ABOVE_FAST"]) if len(crossovers_df) else 0
    n_cross_bs = len(crossovers_df[crossovers_df["type"] == "CROSS_BELOW_SLOW"]) if len(crossovers_df) else 0
    n_cross_bf = len(crossovers_df[crossovers_df["type"] == "CROSS_BELOW_FAST"]) if len(crossovers_df) else 0

    lines = [
        f"\n{'='*60}",
        f"  Period: {period_label}",
        f"  Config: S{params.slow_ma_len}{params.slow_ma_type} / F{params.fast_ma_len}{params.fast_ma_type}"
        f" / LL{params.leverage_long} / LS{params.leverage_short} / SL{params.sl_risk_pct}%",
        f"  Range:  {start} → {end or 'present'}",
        f"{'='*60}",
        f"  Trades total:    {len(trades)}",
        f"  → Long:          {n_long}",
        f"  → Short:         {n_short}",
        f"  Exit breakdown:",
        f"  → CL (close L):  {n_cl}",
        f"  → CS (close S):  {n_cs}",
        f"  → SL:            {n_sl}",
        f"",
        f"  Crossover events (in trade window):",
        f"  → Cross ABOVE SlowMA:  {n_cross_as}  (Long entry trigger)",
        f"  → Cross ABOVE FastMA:  {n_cross_af}  (Long re-entry trigger)",
        f"  → Cross BELOW SlowMA:  {n_cross_bs}  (Short entry trigger)",
        f"  → Cross BELOW FastMA:  {n_cross_bf}  (Short re-entry trigger)",
        f"  Total crossovers:      {n_cross_as + n_cross_af + n_cross_bs + n_cross_bf}",
        f"{'='*60}",
    ]
    text = "\n".join(lines)
    print(text)
    return text


def main() -> None:
    params = TICKER_CONFIG[TICKER]
    all_summary_lines: list[str] = [
        "AMB v1.6.1 BTC-USD – Discrepancy Diagnostic",
        f"Config: S{params.slow_ma_len}{params.slow_ma_type} / F{params.fast_ma_len}{params.fast_ma_type}"
        f" / LL{params.leverage_long} / LS{params.leverage_short} / SL{params.sl_risk_pct}%",
        "",
        "PURPOSE: Identify root cause of Pine Script vs Python trade-count discrepancy.",
        "NOTE: BACKTEST_COMPARISON.md referenced the OLD config (SMA100); v1.6.1 uses SMA130.",
        "",
    ]

    for label, (start, end) in PERIODS_TO_TEST.items():
        print(f"\n[{label}] Loading data …")

        # Load with warmup so MAs are valid from day 1 of trade window
        df_full = get_slice(TICKER, warmup=True)
        trade_start = pd.Timestamp(start)

        end_ts = pd.Timestamp(end) if end else df_full.index[-1]
        df_window = df_full[df_full.index <= end_ts].copy()

        trades, crossovers_df = _run_with_crossovers(df_window, params,
                                                      trade_start=trade_start)

        # Filter crossovers to trade window only
        if len(crossovers_df) > 0:
            mask = (crossovers_df.index >= trade_start) & (crossovers_df.index <= end_ts)
            crossovers_window = crossovers_df[mask]
        else:
            crossovers_window = crossovers_df

        # Filter trades to window
        trades_window = [t for t in trades if t.entry_date >= trade_start]

        # Build MA daily export (filtered to window)
        ma_df = _build_ma_daily(df_window, params)
        ma_window = ma_df[ma_df.index >= trade_start].copy()

        # Summary
        end_str = end or "present"
        summary = _print_summary(label, trades_window, crossovers_window,
                                  params, start, end_str)
        all_summary_lines.append(summary)

        # Save CSVs
        lbl = label.replace(":", "").replace(" ", "_")

        trades_df = _trades_to_df(trades_window)
        trades_df.to_csv(OUT_DIR / f"{lbl}_trades_detail.csv", index=False)
        print(f"  → {OUT_DIR / f'{lbl}_trades_detail.csv'}")

        if len(crossovers_window) > 0:
            crossovers_window.to_csv(OUT_DIR / f"{lbl}_crossovers.csv")
            print(f"  → {OUT_DIR / f'{lbl}_crossovers.csv'}")

        ma_window.to_csv(OUT_DIR / f"{lbl}_ma_daily.csv")
        print(f"  → {OUT_DIR / f'{lbl}_ma_daily.csv'}")

    # Write combined summary
    summary_path = OUT_DIR / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_summary_lines))
    print(f"\n  → {summary_path}")

    print("""
┌─────────────────────────────────────────────────────────────┐
│  NÄCHSTER SCHRITT: TradingView-Abgleich                     │
│                                                             │
│  1. Öffne TradingView mit BTC-USD Daily                     │
│  2. Config: SMA130 + SMA44, kein Repainting                 │
│  3. Prüfe erste 5 Crossover-Daten aus crossovers.csv        │
│     gegen Pine Script Chart                                 │
│  4. Wenn Daten übereinstimmen → Trade-Logik analysieren     │
│  5. Wenn Daten abweichen     → Datenquelle ist das Problem  │
└─────────────────────────────────────────────────────────────┘
""")


if __name__ == "__main__":
    main()

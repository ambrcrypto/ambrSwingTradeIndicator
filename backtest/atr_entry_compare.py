"""
atr_entry_compare.py – Compare baseline vs ATR entry filter on BTC-USD.

Baseline:   LL3/LS0.5/SL6%/SMA130/44 (v1.6.1 live config)
ATR filter: same + atr_entry_enable=True, long_mult=1.7, short_mult=1.5

Usage:
    python -m backtest.atr_entry_compare
"""
import sys
import pandas as pd
from .data import get_slice, get_periods
from .strategy_amb import AMBParams, run_strategy
from .engine import compute_metrics

TICKER      = "BTC-USD"
PERIOD_NAME = "2021_default"

# ── v1.6.1 live config ──────────────────────────────────────────────────────
BASE = AMBParams(
    slow_ma_len=130, slow_ma_type="SMA",
    fast_ma_len=44,  fast_ma_type="SMA",
    use_fast_ma=True,
    leverage_long=3.0, leverage_short=0.5,
    sl_enable=True, sl_risk_pct=6.0,
    signal_tf="D",
)

# Variants to test: ATR length 14, various long/short mult combos
ATR_VARIANTS = [
    # (atr_entry_len, atr_long_mult, atr_short_mult, label)
    (14, 1.7, 1.5, "ATR14 L1.7/S1.5 (orig)"),
    (14, 1.0, 1.0, "ATR14 L1.0/S1.0"),
    (14, 1.5, 1.5, "ATR14 L1.5/S1.5"),
    (14, 2.0, 1.5, "ATR14 L2.0/S1.5"),
    (14, 1.7, 1.0, "ATR14 L1.7/S1.0"),
    (14, 0.5, 0.5, "ATR14 L0.5/S0.5"),
]


def fmt(v, pct=False, dp=1):
    if v is None or (isinstance(v, float) and v != v):
        return "  n/a"
    if pct:
        return f"{v:+7.{dp}f}%"
    return f"{v:7.{dp}f}"


def run_one(params: AMBParams, df: pd.DataFrame, start: str) -> dict:
    ts = pd.Timestamp(start)
    trades = run_strategy(df, params, trade_start=ts)
    return compute_metrics(trades, params, start, str(df.index[-1].date()))


def main():
    periods = get_periods(TICKER)
    start, end = periods[PERIOD_NAME]
    df = get_slice(TICKER, start, end)
    print(f"\nBTC-USD  |  Period: {start} → {df.index[-1].date()}")
    print(f"Total bars: {len(df)}\n")

    # ── Baseline ─────────────────────────────────────────────────────────
    base_m = run_one(BASE, df, start)

    print(f"{'Config':<30}  {'P/L%':>8}  {'MaxDD%':>7}  {'Trades':>7}  {'Win%':>6}  {'PF':>5}  {'SL#':>4}")
    print("-" * 75)

    def row(label, m):
        sl_count = m.get("sl_hits", 0)
        pf = m.get("profit_factor", 0)
        pf_str = f"{pf:5.2f}" if pf and pf == pf else "  n/a"
        print(f"{label:<30}  {m['pl_pct']:+8.1f}%  {m['max_dd']:7.1f}%  "
              f"{m['trades']:>7}  {m['win_rate']:6.1f}%  {pf_str}  {sl_count:>4}")

    row("Baseline (v1.6.1)", base_m)
    print()

    # ── ATR variants ─────────────────────────────────────────────────────
    for atr_len, long_mult, short_mult, label in ATR_VARIANTS:
        import copy
        p = copy.copy(BASE)
        p.atr_entry_enable = True
        p.atr_entry_len    = atr_len
        p.atr_long_mult    = long_mult
        p.atr_short_mult   = short_mult
        m = run_one(p, df, start)
        row(label, m)

    print()

    # ── Extra: ATR filter long-only, short-only ───────────────────────────
    print("--- Long-only decomposition ---")
    import copy

    p_no_s = copy.copy(BASE)
    p_no_s.allow_shorts = False
    row("Baseline long-only", run_one(p_no_s, df, start))

    p_atr_no_s = copy.copy(BASE)
    p_atr_no_s.allow_shorts    = False
    p_atr_no_s.atr_entry_enable = True
    p_atr_no_s.atr_entry_len    = 14
    p_atr_no_s.atr_long_mult    = 1.7
    p_atr_no_s.atr_short_mult   = 1.5
    row("ATR14 L1.7/S1.5 long-only", run_one(p_atr_no_s, df, start))


if __name__ == "__main__":
    main()

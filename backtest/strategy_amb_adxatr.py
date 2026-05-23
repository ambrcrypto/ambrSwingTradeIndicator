"""
strategy_amb_adxatr.py – AMB Dual MA Signal with ADX + ATR entry filter.

Filter rules (entry only — exits and SL are NEVER filtered):
  • ADX(14) > ADX_THRESHOLD  (trend strong enough)
  • |close − Slow-EMA| > ATR(14) × ATR_MULTIPLIER  (price far enough from MA)

Both conditions must be true at the bar of the entry signal.
Flip-entries (simultaneous exit + entry) are also filtered.

Returns (list[Trade], filter_stats dict).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass

from .strategy_amb import AMBParams, Trade, _calc_ma, _calc_atr, _first_day_mask

# ─────────────────────────────────────────────────────────────────────────────
# ADX + ATR filter parameters
# ─────────────────────────────────────────────────────────────────────────────

ADX_PERIOD      = 14
ADX_THRESHOLD   = 25
ATR_PERIOD      = 14
ATR_MULTIPLIER  = 0.5


# ─────────────────────────────────────────────────────────────────────────────
# ADX calculation (Wilder's RMA, identical to Pine Script ta.adx)
# ─────────────────────────────────────────────────────────────────────────────

def _calc_adx(
    high:  np.ndarray,
    low:   np.ndarray,
    close: np.ndarray,
    length: int = ADX_PERIOD,
) -> np.ndarray:
    """
    Wilder's ADX — matches Pine Script ta.adx(high, low, close, length).

    Algorithm:
      up   = high[i] - high[i-1]
      down = low[i-1]  - low[i]
      DM+  = up   if up > down and up > 0 else 0
      DM-  = down if down > up and down > 0 else 0
      RMA14(TR), RMA14(DM+), RMA14(DM-)
      DI+  = 100 * RMA(DM+) / RMA(TR)
      DI-  = 100 * RMA(DM-) / RMA(TR)
      DX   = 100 * |DI+ - DI-| / (DI+ + DI-)
      ADX  = RMA14(DX)

    Seed: simple mean of first `length` valid values (Wilder convention).
    Returns NaN for warmup bars (first 2*length bars).
    """
    n = len(close)

    # ── True Range (vectorised, same as _calc_atr) ────────────────────────
    tr = np.empty(n)
    tr[0] = np.nan
    tr[1:] = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:]  - close[:-1]),
        ),
    )

    # ── Directional Movement (vectorised) ────────────────────────────────
    dm_plus  = np.zeros(n)
    dm_minus = np.zeros(n)
    up   = high[1:]  - high[:-1]   # shape (n-1,)
    down = low[:-1]  - low[1:]     # shape (n-1,)
    dm_plus[1:]  = np.where((up > down)   & (up   > 0), up,   0.0)
    dm_minus[1:] = np.where((down > up)   & (down > 0), down, 0.0)

    # ── Wilder's RMA for TR, DM+, DM- ────────────────────────────────────
    def _rma(arr: np.ndarray, p: int) -> np.ndarray:
        out = np.full(n, np.nan)
        # find first complete set of p non-NaN values starting at index 1
        valid = np.where(~np.isnan(arr[1:]))[0] + 1  # 1-based indices
        if len(valid) < p:
            return out
        seed_end = valid[p - 1]       # last bar of seed window
        seed_start = seed_end - p + 1 # first bar of seed window (inclusive)
        # ensure all bars in [seed_start, seed_end] are non-NaN
        seed_vals = arr[seed_start:seed_end + 1]
        if np.any(np.isnan(seed_vals)):
            return out
        out[seed_end] = float(np.mean(seed_vals))
        inv_p     = 1.0 / p
        comp_coef = (p - 1) * inv_p
        for j in range(seed_end + 1, n):
            if np.isnan(arr[j]):
                out[j] = out[j - 1]   # propagate last (edge case)
            else:
                out[j] = comp_coef * out[j - 1] + inv_p * arr[j]
        return out

    rma_tr   = _rma(tr,       length)
    rma_plus = _rma(dm_plus,  length)
    rma_min  = _rma(dm_minus, length)

    # ── Directional Indices ───────────────────────────────────────────────
    with np.errstate(invalid="ignore", divide="ignore"):
        di_plus  = np.where(rma_tr > 0, 100.0 * rma_plus / rma_tr, 0.0)
        di_minus = np.where(rma_tr > 0, 100.0 * rma_min  / rma_tr, 0.0)

    di_sum  = di_plus + di_minus
    with np.errstate(invalid="ignore", divide="ignore"):
        dx = np.where(di_sum > 0, 100.0 * np.abs(di_plus - di_minus) / di_sum, 0.0)

    # Mask warmup bars where RMA isn't valid yet
    warmup_mask = np.isnan(rma_tr)
    dx = np.where(warmup_mask, np.nan, dx)

    # ── ADX = RMA(DX, length) ─────────────────────────────────────────────
    adx = _rma(dx, length)
    return adx


# ─────────────────────────────────────────────────────────────────────────────
# Filter statistics container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ADXATRFilterStats:
    total_signals:       int = 0   # raw entry signals (before filter)
    passed:              int = 0   # signals that passed both filters
    filtered_adx_only:  int = 0   # blocked only because ADX was weak
    filtered_atr_only:  int = 0   # blocked only because price near MA
    filtered_both:      int = 0   # blocked by both

    @property
    def filtered_total(self) -> int:
        return self.filtered_adx_only + self.filtered_atr_only + self.filtered_both

    @property
    def pct_filtered_adx(self) -> float:
        """% of signals where ADX condition failed (regardless of ATR)."""
        adx_fail = self.filtered_adx_only + self.filtered_both
        return adx_fail / max(self.total_signals, 1) * 100.0

    @property
    def pct_filtered_atr(self) -> float:
        """% of signals where ATR condition failed (regardless of ADX)."""
        atr_fail = self.filtered_atr_only + self.filtered_both
        return atr_fail / max(self.total_signals, 1) * 100.0

    def print_summary(self) -> None:
        print("\n── ADX+ATR Filter Statistics ───────────────────────────────────")
        print(f"  Total entry signals      : {self.total_signals}")
        print(f"  Passed both filters      : {self.passed}")
        print(f"  Filtered (ADX too weak)  : {self.filtered_adx_only}  "
              f"({self.pct_filtered_adx:.1f}% of signals impacted by ADX)")
        print(f"  Filtered (ATR too close) : {self.filtered_atr_only}  "
              f"({self.pct_filtered_atr:.1f}% of signals impacted by ATR)")
        print(f"  Filtered (both)          : {self.filtered_both}")
        print(f"  ADX threshold : {ADX_THRESHOLD}  |  ATR multiplier : {ATR_MULTIPLIER}×")


# ─────────────────────────────────────────────────────────────────────────────
# Main strategy runner
# ─────────────────────────────────────────────────────────────────────────────

def run_strategy_adxatr(
    df:          pd.DataFrame,
    params:      AMBParams,
    trade_start: "pd.Timestamp | None" = None,
    adx_period:     int   = ADX_PERIOD,
    adx_threshold:  float = ADX_THRESHOLD,
    atr_period:     int   = ATR_PERIOD,
    atr_multiplier: float = ATR_MULTIPLIER,
) -> tuple[list[Trade], ADXATRFilterStats]:
    """
    Run AMB strategy with ADX+ATR entry filter on an OHLCV DataFrame.

    Entry signals are blocked when:
      - ADX(adx_period) ≤ adx_threshold, OR
      - |close - slow_ema| ≤ ATR(atr_period) × atr_multiplier

    Exits and Stop-Loss are never filtered.

    Returns (list[Trade], ADXATRFilterStats).
    """
    close_s = df["close"]
    close   = close_s.to_numpy(dtype=float)
    high    = df["high"].to_numpy(dtype=float)
    low_    = df["low"].to_numpy(dtype=float)
    dates   = df.index
    n       = len(df)

    slow_ma     = _calc_ma(close_s, params.slow_ma_len, params.slow_ma_type)
    fast_ma     = _calc_ma(close_s, params.fast_ma_len, params.fast_ma_type)
    atr_sl      = _calc_atr(high, low_, close, params.atr_sl_len) if params.atr_sl_enable else np.full(n, np.nan)
    atr_filter  = _calc_atr(high, low_, close, atr_period)
    adx         = _calc_adx(high, low_, close, adx_period)
    signal_days = _first_day_mask(dates, params.signal_tf)

    stats = ADXATRFilterStats()

    # ── State ──────────────────────────────────────────────────────────────
    last_dir:            int   = 0
    position_open:       bool  = False
    long_above_fast_ma:  bool  = False
    short_below_fast_ma: bool  = False
    entry_price:         float = 0.0
    entry_atr:           float = 0.0
    entry_bar:           int   = 0
    entry_date:          pd.Timestamp = dates[0]

    trades: list[Trade] = []

    for i in range(1, n):
        if np.isnan(slow_ma[i]) or np.isnan(fast_ma[i]):
            continue
        if np.isnan(slow_ma[i - 1]) or np.isnan(fast_ma[i - 1]):
            continue

        c  = close[i];  c0 = close[i - 1]
        h  = high[i]
        lo = low_[i]
        s  = slow_ma[i]; s0 = slow_ma[i - 1]
        f  = fast_ma[i]; f0 = fast_ma[i - 1]

        # ── Fast MA state tracking ──────────────────────────────────────────
        if position_open and params.use_fast_ma:
            if last_dir == 1  and c > f:
                long_above_fast_ma  = True
            if last_dir == -1 and c < f:
                short_below_fast_ma = True

        # ── Crossovers (signal-day gated) ───────────────────────────────────
        if signal_days[i]:
            cross_above_slow = (c > s) and (c0 <= s0)
            cross_above_fast = params.use_fast_ma and (c > f) and (c0 <= f0)
            cross_below_slow = (c < s) and (c0 >= s0)
            cross_below_fast = params.use_fast_ma and (c < f) and (c0 >= f0)
        else:
            cross_above_slow = cross_above_fast = cross_below_slow = cross_below_fast = False

        # ── SL levels ───────────────────────────────────────────────────────
        if params.atr_sl_enable and position_open and entry_price > 0 and entry_atr > 0:
            sl_long_level  = (entry_price - entry_atr * params.atr_sl_mult) if last_dir == 1  else None
            sl_short_level = (entry_price + entry_atr * params.atr_sl_mult) if last_dir == -1 else None
        elif params.sl_enable and position_open and entry_price > 0:
            sl_long_level  = (
                entry_price * (1.0 - params.sl_risk_pct / (100.0 * params.leverage_long))
                if last_dir == 1 else None
            )
            sl_short_level = (
                entry_price * (1.0 + params.sl_risk_pct / (100.0 * params.leverage_short))
                if last_dir == -1 else None
            )
        else:
            sl_long_level  = None
            sl_short_level = None

        # ── Exit conditions ─────────────────────────────────────────────────
        exit_long_A  = position_open and last_dir == 1  and long_above_fast_ma  and cross_below_fast
        exit_long_B  = position_open and last_dir == 1  and cross_below_slow
        exit_long_SL = (sl_long_level  is not None) and (lo <= sl_long_level)
        exit_long    = exit_long_A or exit_long_B or exit_long_SL

        exit_short_A  = position_open and last_dir == -1 and short_below_fast_ma and cross_above_fast
        exit_short_B  = position_open and last_dir == -1 and cross_above_slow
        exit_short_SL = (sl_short_level is not None) and (h >= sl_short_level)
        exit_short    = exit_short_A or exit_short_B or exit_short_SL

        # ── Raw entry conditions ────────────────────────────────────────────
        long_entry   = (not position_open) and (last_dir != 1)  and cross_above_slow
        long_reentry = (not position_open) and (last_dir == 1)  and cross_above_fast and (c > s)

        short_entry   = (not position_open) and (last_dir != -1) and cross_below_slow
        short_reentry = (not position_open) and (last_dir == -1) and cross_below_fast and (c < s)

        # ── Flip logic ──────────────────────────────────────────────────────
        flip_to_short = exit_long  and cross_below_slow and params.allow_shorts
        flip_to_long  = exit_short and cross_above_slow and params.allow_longs

        # ── ADX + ATR entry filter ──────────────────────────────────────────
        # Applied to: long_entry, long_reentry, short_entry, short_reentry,
        #             flip_to_long, flip_to_short.
        # Exits (exit_long, exit_short) are NEVER filtered.
        raw_entry = (long_entry or long_reentry or short_entry or short_reentry
                     or flip_to_long or flip_to_short)

        if raw_entry:
            cur_adx = adx[i]
            cur_atr = atr_filter[i]
            adx_ok  = (not np.isnan(cur_adx)) and (cur_adx > adx_threshold)
            atr_ok  = (not np.isnan(cur_atr)) and (abs(c - s) > cur_atr * atr_multiplier)

            stats.total_signals += 1

            if adx_ok and atr_ok:
                stats.passed += 1
                # let signals through unchanged
            else:
                # Record why it was blocked (for separate ADX / ATR stats)
                if (not adx_ok) and (not atr_ok):
                    stats.filtered_both += 1
                elif not adx_ok:
                    stats.filtered_adx_only += 1
                else:
                    stats.filtered_atr_only += 1

                # Block all entry flags; exits are already computed above
                long_entry    = False
                long_reentry  = False
                short_entry   = False
                short_reentry = False
                flip_to_long  = False
                flip_to_short = False

        long_signal  = ((long_entry  or long_reentry)  and params.allow_longs)  or flip_to_long
        short_signal = ((short_entry or short_reentry) and params.allow_shorts) or flip_to_short

        # ── State machine: EXIT first, then ENTRY ───────────────────────────

        if exit_long and position_open and last_dir == 1:
            if exit_long_SL:
                if params.atr_sl_enable:
                    pct = ((sl_long_level - entry_price) / entry_price * 100.0) * params.leverage_long
                else:
                    pct = -params.sl_risk_pct
            else:
                pct = ((c - entry_price) / entry_price * 100.0) * params.leverage_long
            if trade_start is None or entry_date >= trade_start:
                trades.append(Trade(
                    entry_bar=entry_bar, entry_date=entry_date,
                    entry_price=entry_price, direction=1,
                    exit_bar=i, exit_date=dates[i],
                    exit_price=c,
                    exit_type="SL" if exit_long_SL else "CL",
                    pct=pct,
                ))
            position_open       = False
            long_above_fast_ma  = False
            short_below_fast_ma = False
            entry_price         = 0.0

        elif exit_short and position_open and last_dir == -1:
            if exit_short_SL:
                if params.atr_sl_enable:
                    pct = ((entry_price - sl_short_level) / entry_price * 100.0) * params.leverage_short
                else:
                    pct = -params.sl_risk_pct
            else:
                pct = ((entry_price - c) / entry_price * 100.0) * params.leverage_short
            if trade_start is None or entry_date >= trade_start:
                trades.append(Trade(
                    entry_bar=entry_bar, entry_date=entry_date,
                    entry_price=entry_price, direction=-1,
                    exit_bar=i, exit_date=dates[i],
                    exit_price=c,
                    exit_type="SL" if exit_short_SL else "CS",
                    pct=pct,
                ))
            position_open       = False
            long_above_fast_ma  = False
            short_below_fast_ma = False
            entry_price         = 0.0

        # ── Open new position ───────────────────────────────────────────────
        if long_signal:
            last_dir            = 1
            position_open       = True
            entry_price         = c
            entry_atr           = float(atr_sl[i]) if not np.isnan(atr_sl[i]) else 0.0
            entry_bar           = i
            entry_date          = dates[i]
            long_above_fast_ma  = c > f
            short_below_fast_ma = False

        elif short_signal:
            last_dir            = -1
            position_open       = True
            entry_price         = c
            entry_atr           = float(atr_sl[i]) if not np.isnan(atr_sl[i]) else 0.0
            entry_bar           = i
            entry_date          = dates[i]
            short_below_fast_ma = c < f
            long_above_fast_ma  = False

    # ── Close open position at last bar ────────────────────────────────────
    if position_open and entry_price > 0 and (trade_start is None or entry_date >= trade_start):
        c = close[-1]
        if last_dir == 1:
            pct   = ((c - entry_price) / entry_price * 100.0) * params.leverage_long
            etype = "CL_OPEN"
        else:
            pct   = ((entry_price - c) / entry_price * 100.0) * params.leverage_short
            etype = "CS_OPEN"
        trades.append(Trade(
            entry_bar=entry_bar, entry_date=entry_date,
            entry_price=entry_price, direction=last_dir,
            exit_bar=n - 1, exit_date=dates[-1],
            exit_price=c,
            exit_type=etype,
            pct=pct,
        ))

    return trades, stats

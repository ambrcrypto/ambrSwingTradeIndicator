"""
strategy_amb.py – AMB Dual MA Signal strategy logic.

1:1 mirror of ambTradeSignalIndicator.pine (v1.5).
Signal rules, state machine, SL logic all faithfully reproduced.

Returns a list of Trade objects from run_strategy().
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Parameter container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AMBParams:
    slow_ma_len:    int   = 130
    slow_ma_type:   str   = "SMA"   # "SMA" | "EMA"
    fast_ma_len:    int   = 44
    fast_ma_type:   str   = "SMA"   # "SMA" | "EMA"
    allow_longs:    bool  = True
    allow_shorts:   bool  = True
    leverage_long:  float = 3.0
    leverage_short: float = 1.4
    sl_enable:      bool  = False
    sl_risk_pct:    float = 2.0     # max capital loss % per trade
    start_capital:  float = 1000.0

    def label(self) -> str:
        sl_str = f"SL{self.sl_risk_pct:.0f}" if self.sl_enable else "noSL"
        return (
            f"S{self.slow_ma_len}{self.slow_ma_type[0]}"
            f"_F{self.fast_ma_len}{self.fast_ma_type[0]}"
            f"_LL{self.leverage_long:.1f}"
            f"_LS{self.leverage_short:.2f}"
            f"_{sl_str}"
            + ("_noShorts" if not self.allow_shorts else "")
        )

    def as_dict(self) -> dict:
        return {
            "slow_ma_len":    self.slow_ma_len,
            "slow_ma_type":   self.slow_ma_type,
            "fast_ma_len":    self.fast_ma_len,
            "fast_ma_type":   self.fast_ma_type,
            "allow_longs":    self.allow_longs,
            "allow_shorts":   self.allow_shorts,
            "leverage_long":  self.leverage_long,
            "leverage_short": self.leverage_short,
            "sl_enable":      self.sl_enable,
            "sl_risk_pct":    self.sl_risk_pct,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Trade record
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    entry_bar:   int
    entry_date:  pd.Timestamp
    entry_price: float
    direction:   int            # 1 = long, -1 = short
    exit_bar:    int
    exit_date:   pd.Timestamp
    exit_price:  float
    exit_type:   str            # "CL" | "CS" | "SL"
    pct:         float          # realised P/L % (leveraged, compounded basis)


# ─────────────────────────────────────────────────────────────────────────────
# MA helper
# ─────────────────────────────────────────────────────────────────────────────

def _calc_ma(series: pd.Series, length: int, ma_type: str) -> np.ndarray:
    if ma_type == "SMA":
        return series.rolling(length, min_periods=length).mean().to_numpy()
    elif ma_type == "EMA":
        return series.ewm(span=length, adjust=False, min_periods=length).mean().to_numpy()
    else:
        raise ValueError(f"Unknown MA type: {ma_type!r}. Use 'SMA' or 'EMA'.")


# ─────────────────────────────────────────────────────────────────────────────
# Main strategy runner
# ─────────────────────────────────────────────────────────────────────────────

def run_strategy(df: pd.DataFrame, params: AMBParams,
                 trade_start: "pd.Timestamp | None" = None) -> list[Trade]:
    """
    Run AMB strategy on OHLCV DataFrame.

    df          : pandas DataFrame with columns [open, high, low, close, volume],
                  DatetimeIndex, sorted ascending.
                  Should include history BEFORE the target period for MA warmup
                  so SMAs are valid from the first bar of interest.
    trade_start : If given, only RECORD trades whose entry date is on or after
                  this timestamp.  The state machine still warms up from bar 0,
                  mirroring how TradingView's main state machine runs from the
                  beginning of history before the backtest window opens.
    Returns list of closed Trade objects.
    Open position at last bar is closed at last close price.
    """
    close_s = df["close"]
    close   = close_s.to_numpy(dtype=float)
    high    = df["high"].to_numpy(dtype=float)
    low_    = df["low"].to_numpy(dtype=float)
    dates   = df.index
    n       = len(df)

    slow_ma = _calc_ma(close_s, params.slow_ma_len, params.slow_ma_type)
    fast_ma = _calc_ma(close_s, params.fast_ma_len, params.fast_ma_type)

    # ── State ──────────────────────────────────────────────────────────────
    last_dir:            int   = 0      # 0=none, 1=long, -1=short
    position_open:       bool  = False
    long_above_fast_ma:  bool  = False
    short_below_fast_ma: bool  = False
    entry_price:         float = 0.0
    entry_bar:           int   = 0
    entry_date:          pd.Timestamp = dates[0]

    trades: list[Trade] = []

    for i in range(1, n):
        # Skip until both MAs have enough history
        if np.isnan(slow_ma[i]) or np.isnan(fast_ma[i]):
            continue
        if np.isnan(slow_ma[i - 1]) or np.isnan(fast_ma[i - 1]):
            continue

        # Skip pre-window bars – state machine starts FRESH at trade_start,
        # mirroring TradingView's bt_position_open=False reset at window open.
        # MAs are valid here because full history was passed in (warmup).
        if trade_start is not None and dates[i] < trade_start:
            continue

        c  = close[i];  c0 = close[i - 1]
        h  = high[i]
        lo = low_[i]
        s  = slow_ma[i]; s0 = slow_ma[i - 1]
        f  = fast_ma[i]; f0 = fast_ma[i - 1]

        # ── Fast MA state tracking (mirrors Pine Script block) ──────────────
        if position_open:
            if last_dir == 1  and c > f:
                long_above_fast_ma  = True
            if last_dir == -1 and c < f:
                short_below_fast_ma = True

        # ── Crossovers (global, computed every bar – CW10002 rule) ──────────
        cross_above_slow = (c > s) and (c0 <= s0)
        cross_above_fast = (c > f) and (c0 <= f0)
        cross_below_slow = (c < s) and (c0 >= s0)
        cross_below_fast = (c < f) and (c0 >= f0)

        # ── SL levels ───────────────────────────────────────────────────────
        sl_long_level  = (
            entry_price * (1.0 - params.sl_risk_pct / (100.0 * params.leverage_long))
            if params.sl_enable and position_open and last_dir == 1 and entry_price > 0
            else None
        )
        sl_short_level = (
            entry_price * (1.0 + params.sl_risk_pct / (100.0 * params.leverage_short))
            if params.sl_enable and position_open and last_dir == -1 and entry_price > 0
            else None
        )

        # ── Exit conditions ─────────────────────────────────────────────────
        exit_long_A  = position_open and last_dir == 1  and long_above_fast_ma  and cross_below_fast
        exit_long_B  = position_open and last_dir == 1  and cross_below_slow
        exit_long_SL = (sl_long_level  is not None) and (lo <= sl_long_level)
        exit_long    = exit_long_A or exit_long_B or exit_long_SL

        exit_short_A  = position_open and last_dir == -1 and short_below_fast_ma and cross_above_fast
        exit_short_B  = position_open and last_dir == -1 and cross_above_slow
        exit_short_SL = (sl_short_level is not None) and (h >= sl_short_level)
        exit_short    = exit_short_A or exit_short_B or exit_short_SL

        # ── Entry conditions ────────────────────────────────────────────────
        long_entry   = (not position_open) and (last_dir != 1)  and cross_above_slow
        long_reentry = (not position_open) and (last_dir == 1)  and cross_above_fast and (c > s)

        short_entry   = (not position_open) and (last_dir != -1) and cross_below_slow
        short_reentry = (not position_open) and (last_dir == -1) and cross_below_fast and (c < s)

        # ── Flip logic ──────────────────────────────────────────────────────
        # SL-exit does NOT block flip when Slow MA is simultaneously crossed
        flip_to_short = exit_long  and cross_below_slow and params.allow_shorts
        flip_to_long  = exit_short and cross_above_slow and params.allow_longs

        long_signal  = ((long_entry  or long_reentry)  and params.allow_longs)  or flip_to_long
        short_signal = ((short_entry or short_reentry) and params.allow_shorts) or flip_to_short

        # ── State machine: EXIT first, then ENTRY (enables same-bar flip) ───

        if exit_long and position_open and last_dir == 1:
            pct = (
                -params.sl_risk_pct
                if exit_long_SL
                else ((c - entry_price) / entry_price * 100.0) * params.leverage_long
            )
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
            pct = (
                -params.sl_risk_pct
                if exit_short_SL
                else ((entry_price - c) / entry_price * 100.0) * params.leverage_short
            )
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
            entry_bar           = i
            entry_date          = dates[i]
            long_above_fast_ma  = c > f
            short_below_fast_ma = False

        elif short_signal:
            last_dir            = -1
            position_open       = True
            entry_price         = c
            entry_bar           = i
            entry_date          = dates[i]
            short_below_fast_ma = c < f
            long_above_fast_ma  = False

    # ── Close open position at last bar (unrealized → realized) ─────────────
    if position_open and entry_price > 0:
        c = close[-1]
        if last_dir == 1:
            pct = ((c - entry_price) / entry_price * 100.0) * params.leverage_long
            etype = "CL_OPEN"
        else:
            pct = ((entry_price - c) / entry_price * 100.0) * params.leverage_short
            etype = "CS_OPEN"
        trades.append(Trade(
            entry_bar=entry_bar, entry_date=entry_date,
            entry_price=entry_price, direction=last_dir,
            exit_bar=n - 1, exit_date=dates[-1],
            exit_price=c,
            exit_type=etype,
            pct=pct,
        ))

    return trades

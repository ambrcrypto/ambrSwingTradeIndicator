"""
strategy_amb.py – AMB Dual MA Signal strategy logic.

1:1 mirror of AMB Dual MA Signal.pine.
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
    slow_ma_type:   str   = "EMA"   # "SMA" | "EMA"
    fast_ma_len:    int   = 60
    fast_ma_type:   str   = "SMA"   # "SMA" | "EMA"
    allow_longs:    bool  = True
    allow_shorts:   bool  = True
    use_fast_ma:    bool  = True    # False = Slow MA only (no re-entry, no fast-exit)
    leverage_long:  float = 3.75
    leverage_short: float = 0.5
    sl_enable:      bool  = True
    sl_risk_pct:    float = 3.0     # max capital loss % per trade (% SL mode)
    # ATR-based SL (overrides sl_enable when True)
    atr_sl_enable:  bool  = False
    atr_sl_len:     int   = 14      # ATR period (Wilder's RMA, same as Pine ta.atr)
    atr_sl_mult:    float = 2.5     # SL distance = ATR_at_entry × atr_mult
    # ATR-based entry filter (additional condition on top of MA crossover)
    # long_entry only when (close - slowMA) >= ATR × atr_long_mult
    # short_entry only when (slowMA - close) >= ATR × atr_short_mult
    atr_entry_enable:   bool  = False
    atr_entry_len:      int   = 14
    atr_long_mult:      float = 1.7
    atr_short_mult:     float = 1.5
    start_capital:  float = 1000.0
    signal_tf:      str   = "D"    # "D"=daily, "W"=weekly, "M"=monthly

    def label(self) -> str:
        if self.atr_sl_enable:
            sl_str = f"ATR{self.atr_sl_len}x{self.atr_sl_mult:.1f}"
        elif self.sl_enable:
            sl_str = f"SL{self.sl_risk_pct:.0f}"
        else:
            sl_str = "noSL"
        tf_str  = f"_{self.signal_tf}" if self.signal_tf != "D" else ""
        fma_str = "" if self.use_fast_ma else "_noFMA"
        return (
            f"S{self.slow_ma_len}{self.slow_ma_type[0]}"
            f"_F{self.fast_ma_len}{self.fast_ma_type[0]}"
            f"_LL{self.leverage_long:.1f}"
            f"_LS{self.leverage_short:.2f}"
            f"_{sl_str}"
            + tf_str
            + fma_str
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
            "use_fast_ma":    self.use_fast_ma,
            "leverage_long":  self.leverage_long,
            "leverage_short": self.leverage_short,
            "sl_enable":      self.sl_enable,
            "sl_risk_pct":    self.sl_risk_pct,
            "atr_sl_enable":  self.atr_sl_enable,
            "atr_sl_len":     self.atr_sl_len,
            "atr_sl_mult":       self.atr_sl_mult,
            "atr_entry_enable": self.atr_entry_enable,
            "atr_entry_len":    self.atr_entry_len,
            "atr_long_mult":    self.atr_long_mult,
            "atr_short_mult":   self.atr_short_mult,
            "signal_tf":        self.signal_tf,
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


def _calc_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """
    Wilder's ATR – identical to Pine Script ta.atr() / ta.rma().
    Seed: simple mean of first `length` True Range values.
    Then: atr[i] = atr[i-1] * (length-1)/length + tr[i] / length
    """
    n = len(close)
    # Vectorised True Range
    tr = np.empty(n)
    tr[0] = np.nan
    tr[1:] = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
    )
    atr = np.full(n, np.nan)
    if n <= length:
        return atr
    # Seed: simple mean of first `length` TRs
    atr[length] = float(np.mean(tr[1:length + 1]))
    # Wilder's smoothing
    inv_len    = 1.0 / length
    comp_coeff = (length - 1) * inv_len
    for j in range(length + 1, n):
        atr[j] = comp_coeff * atr[j - 1] + inv_len * tr[j]
    return atr


def _first_day_mask(dates: pd.DatetimeIndex, tf: str) -> np.ndarray:
    """Boolean mask: True on first available trading day of each period.

    tf="D"  → every day (all True)
    tf="W"  → first trading day of each ISO calendar week
    tf="M"  → first trading day of each calendar month
    Stop-loss checks are NOT affected by this mask (always daily).
    """
    if tf == "D":
        return np.ones(len(dates), dtype=bool)
    mask = np.zeros(len(dates), dtype=bool)
    seen: set = set()
    for i, dt in enumerate(dates):
        key = (dt.year, dt.isocalendar()[1]) if tf == "W" else (dt.year, dt.month)
        if key not in seen:
            seen.add(key)
            mask[i] = True
    return mask


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

    slow_ma   = _calc_ma(close_s, params.slow_ma_len, params.slow_ma_type)
    fast_ma   = _calc_ma(close_s, params.fast_ma_len, params.fast_ma_type)
    atr       = _calc_atr(high, low_, close, params.atr_sl_len) if params.atr_sl_enable else np.full(n, np.nan)
    atr_entry = _calc_atr(high, low_, close, params.atr_entry_len) if params.atr_entry_enable else np.full(n, np.nan)
    signal_days = _first_day_mask(dates, params.signal_tf)

    # ── State ──────────────────────────────────────────────────────────────
    last_dir:            int   = 0      # 0=none, 1=long, -1=short
    position_open:       bool  = False
    long_above_fast_ma:  bool  = False
    short_below_fast_ma: bool  = False
    entry_price:         float = 0.0
    entry_atr:           float = 0.0    # ATR value frozen at entry (ATR SL mode only)
    entry_bar:           int   = 0
    entry_date:          pd.Timestamp = dates[0]

    # Pending entry state (ATR entry filter mode)
    # After a MA crossover, wait until close reaches MA_at_cross +/- ATR_at_cross * mult
    pending_long:        bool  = False
    pending_short:       bool  = False
    pending_long_level:  float = 0.0    # close must reach >= this to enter long
    pending_short_level: float = 0.0    # close must reach <= this to enter short

    trades: list[Trade] = []

    for i in range(1, n):
        # Skip until both MAs have enough history
        if np.isnan(slow_ma[i]) or np.isnan(fast_ma[i]):
            continue
        if np.isnan(slow_ma[i - 1]) or np.isnan(fast_ma[i - 1]):
            continue

        c  = close[i];  c0 = close[i - 1]
        h  = high[i]
        lo = low_[i]
        s  = slow_ma[i]; s0 = slow_ma[i - 1]
        f  = fast_ma[i]; f0 = fast_ma[i - 1]

        # ── Fast MA state tracking (mirrors Pine Script block) ──────────────
        if position_open and params.use_fast_ma:
            if last_dir == 1  and c > f:
                long_above_fast_ma  = True
            if last_dir == -1 and c < f:
                short_below_fast_ma = True

        # ── Crossovers – only on signal days (signal_tf filter) ────────────
        # SL checks always run daily; new entries/exits only on first day
        # of the configured period (D=every day, W=weekly, M=monthly).
        if signal_days[i]:
            cross_above_slow = (c > s) and (c0 <= s0)
            cross_above_fast = params.use_fast_ma and (c > f) and (c0 <= f0)
            cross_below_slow = (c < s) and (c0 >= s0)
            cross_below_fast = params.use_fast_ma and (c < f) and (c0 >= f0)
        else:
            cross_above_slow = False
            cross_above_fast = False
            cross_below_slow = False
            cross_below_fast = False

        # ── SL levels ───────────────────────────────────────────────────────
        if params.atr_sl_enable and position_open and entry_price > 0 and entry_atr > 0:
            # ATR SL: level fixed at entry ATR × mult, never moves during trade
            sl_long_level  = (entry_price - entry_atr * params.atr_sl_mult) if last_dir == 1  else None
            sl_short_level = (entry_price + entry_atr * params.atr_sl_mult) if last_dir == -1 else None
        elif params.sl_enable and position_open and entry_price > 0:
            # % SL: fixed percentage capital risk
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

        # ── Entry conditions ────────────────────────────────────────────────
        long_entry   = (not position_open) and (last_dir != 1)  and cross_above_slow
        long_reentry = (not position_open) and (last_dir == 1)  and cross_above_fast and (c > s)

        short_entry   = (not position_open) and (last_dir != -1) and cross_below_slow
        short_reentry = (not position_open) and (last_dir == -1) and cross_below_fast and (c < s)

        # ── ATR pending entry filter ─────────────────────────────────────────
        # On MA crossover: arm a pending entry. Actual entry fires on a later
        # bar when close reaches MA_at_cross +/- ATR_at_cross * mult.
        # Pending is cancelled if price crosses back below/above slow MA.
        if params.atr_entry_enable:
            ae = atr_entry[i] if not np.isnan(atr_entry[i]) else 0.0

            # Arm pending long on crossover (only for first-time entries, not reentry/flip)
            if (not position_open) and (last_dir != 1) and cross_above_slow and ae > 0:
                pending_long        = True
                pending_short       = False
                pending_long_level  = s + ae * params.atr_long_mult  # s = slowMA at cross bar
                long_entry = False  # suppress immediate entry

            # Arm pending short on crossover
            if (not position_open) and (last_dir != -1) and cross_below_slow and ae > 0:
                pending_short       = True
                pending_long        = False
                pending_short_level = s - ae * params.atr_short_mult  # price must drop to here
                short_entry = False  # suppress immediate entry

            # Cancel pending if MA crossed back
            if pending_long  and cross_below_slow:
                pending_long  = False
            if pending_short and cross_above_slow:
                pending_short = False
            # Cancel pending if position was opened (e.g. via reentry/flip)
            if position_open:
                pending_long  = False
                pending_short = False

            # Fire pending long when close reaches target level
            if pending_long and (not position_open) and c >= pending_long_level:
                long_entry   = True
                pending_long = False

            # Fire pending short when close reaches target level
            if pending_short and (not position_open) and c <= pending_short_level:
                short_entry   = True
                pending_short = False

        # ── Flip logic ──────────────────────────────────────────────────────
        # SL-exit does NOT block flip when Slow MA is simultaneously crossed
        flip_to_short = exit_long  and cross_below_slow and params.allow_shorts
        flip_to_long  = exit_short and cross_above_slow and params.allow_longs

        long_signal  = ((long_entry  or long_reentry)  and params.allow_longs)  or flip_to_long
        short_signal = ((short_entry or short_reentry) and params.allow_shorts) or flip_to_short

        # ── State machine: EXIT first, then ENTRY (enables same-bar flip) ───

        if exit_long and position_open and last_dir == 1:
            if exit_long_SL:
                if params.atr_sl_enable:
                    # ATR SL: actual loss based on price distance to frozen SL level
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
                    # ATR SL: actual loss based on price distance to frozen SL level
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
            entry_atr           = float(atr[i]) if not np.isnan(atr[i]) else 0.0
            entry_bar           = i
            entry_date          = dates[i]
            long_above_fast_ma  = c > f
            short_below_fast_ma = False
            pending_long        = False
            pending_short       = False

        elif short_signal:
            last_dir            = -1
            position_open       = True
            entry_price         = c
            entry_atr           = float(atr[i]) if not np.isnan(atr[i]) else 0.0
            entry_bar           = i
            entry_date          = dates[i]
            short_below_fast_ma = c < f
            long_above_fast_ma  = False
            pending_long        = False
            pending_short       = False

    # ── Close open position at last bar (unrealized → realized) ─────────────
    if position_open and entry_price > 0 and (trade_start is None or entry_date >= trade_start):
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

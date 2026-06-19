import pandas as pd
import numpy as np
from datetime import date
from pathlib import Path
from tqdm import tqdm
from copy import deepcopy
import concurrent.futures

from backtest.data import get_all
from backtest.strategy_amb import (
    AMBParams, Trade, _calc_ma, _calc_atr, _first_day_mask
)

from backtest.optimize import _grid_params
from backtest.engine import compute_metrics
from backtest.report import console

BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "results" / "walk_forward"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── 1. The Stitched Strategy Runner ──────────────────────────────────────────

def recalculate_arrays(df: pd.DataFrame, params: AMBParams):
    """Recalculate indicator arrays for the full timeline when params change."""
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
    atr_trail = _calc_atr(high, low_, close, params.trail_atr_len) if params.trail_sl_enable else np.full(n, np.nan)
    signal_days = _first_day_mask(dates, params.signal_tf)
    
    return slow_ma, fast_ma, atr, atr_entry, atr_trail, signal_days

def run_stitched_strategy(df: pd.DataFrame, param_map: dict[pd.Timestamp, AMBParams], trade_start: pd.Timestamp) -> list[Trade]:
    """
    param_map: dictates which AMBParams to use after a given checkpoint.
    If position is flat, we check if the current date has crossed a checkpoint, and switch params if so.
    """
    close_s = df["close"]
    close   = close_s.to_numpy(dtype=float)
    high    = df["high"].to_numpy(dtype=float)
    low_    = df["low"].to_numpy(dtype=float)
    dates   = df.index
    n       = len(df)
    
    # Sort checkpoints to easily find the active one
    checkpoints = sorted(list(param_map.keys()))
    
    # Identify initial params (the very first checkpoint, or default fallback)
    current_params = param_map[checkpoints[0]]
    active_cp_idx = 0
    
    slow_ma, fast_ma, atr, atr_entry, atr_trail, signal_days = recalculate_arrays(df, current_params)

    # State variables
    last_dir:            int   = 0     
    position_open:       bool  = False
    long_above_fast_ma:  bool  = False
    short_below_fast_ma: bool  = False
    entry_price:         float = 0.0
    entry_atr:           float = 0.0    
    entry_bar:           int   = 0
    entry_date:          pd.Timestamp = dates[0]

    pending_long:        bool  = False
    pending_short:       bool  = False
    pending_long_level:  float = 0.0    
    pending_short_level: float = 0.0    

    trail_active:         bool  = False
    trail_sl_level:       float = 0.0   
    trail_reentry_armed:  bool  = False 

    peak_dd_active:       bool  = False
    peak_close_long:      float = 0.0   
    peak_close_short:     float = float('inf')  

    trades: list[Trade] = []

    for i in range(1, n):
        # ── Parameter Switching Logic (Flat State Only) ──────────────────────
        if not position_open:
            # Are we crossing the next checkpoint?
            while active_cp_idx < len(checkpoints) - 1 and dates[i] >= checkpoints[active_cp_idx + 1]:
                active_cp_idx += 1
                current_params = param_map[checkpoints[active_cp_idx]]
                # Recalculate indicators with new params for the remaining journey
                slow_ma, fast_ma, atr, atr_entry, atr_trail, signal_days = recalculate_arrays(df, current_params)
        
        params = current_params # alias

        if np.isnan(slow_ma[i]) or np.isnan(fast_ma[i]) or np.isnan(slow_ma[i - 1]) or np.isnan(fast_ma[i - 1]):
            continue

        c  = close[i];  c0 = close[i - 1]
        h  = high[i]
        lo = low_[i]
        s  = slow_ma[i]; s0 = slow_ma[i - 1]
        f  = fast_ma[i]; f0 = fast_ma[i - 1]

        if position_open and params.use_fast_ma:
            if last_dir == 1  and c > f: long_above_fast_ma  = True
            if last_dir == -1 and c < f: short_below_fast_ma = True
            
        if params.trail_sl_enable and position_open:
            atr_t = float(atr_trail[i]) if not np.isnan(atr_trail[i]) else 0.0
            if last_dir == 1:
                unrealised_pct = (c - entry_price) / entry_price * 100.0
                if unrealised_pct >= params.trail_activate_pct: trail_active = True
                if trail_active and atr_t > 0:
                    trail_sl_level = max(trail_sl_level, c - atr_t * params.trail_atr_factor)
            elif last_dir == -1:
                unrealised_pct = (entry_price - c) / entry_price * 100.0
                if unrealised_pct >= params.trail_activate_pct: trail_active = True
                if trail_active and atr_t > 0:
                    trail_sl_level = min(trail_sl_level, c + atr_t * params.trail_atr_factor)
                    
        if params.peak_dd_enable and position_open:
            if last_dir == 1:
                unrealised_pct = (c - entry_price) / entry_price * 100.0
                if unrealised_pct >= params.peak_dd_activate_pct: peak_dd_active = True
                if c > peak_close_long: peak_close_long = c
            elif last_dir == -1:
                unrealised_pct = (entry_price - c) / entry_price * 100.0
                if unrealised_pct >= params.peak_dd_activate_pct: peak_dd_active = True
                if c < peak_close_short: peak_close_short = c
                
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

        if params.atr_sl_enable and position_open and entry_price > 0 and entry_atr > 0:
            sl_long_level  = (entry_price - entry_atr * params.atr_sl_mult) if last_dir == 1  else None
            sl_short_level = (entry_price + entry_atr * params.atr_sl_mult) if last_dir == -1 else None
        elif params.sl_enable and position_open and entry_price > 0:
            sl_long_level  = (entry_price * (1.0 - params.sl_risk_pct / (100.0 * params.leverage_long))) if last_dir == 1 else None
            sl_short_level = (entry_price * (1.0 + params.sl_risk_pct / (100.0 * params.leverage_short))) if last_dir == -1 else None
        else:
            sl_long_level  = None
            sl_short_level = None

        exit_long_A   = position_open and last_dir == 1  and long_above_fast_ma  and cross_below_fast
        exit_long_B   = position_open and last_dir == 1  and cross_below_slow
        exit_long_SL  = (sl_long_level  is not None) and (lo <= sl_long_level)
        exit_long_TSL = (params.trail_sl_enable and trail_active and position_open and last_dir == 1  and lo <= trail_sl_level)
        exit_long_PD  = (params.peak_dd_enable and peak_dd_active and position_open and last_dir == 1 and peak_close_long > 0 and c < peak_close_long * (1.0 - params.peak_dd_pct / 100.0))
        exit_long     = exit_long_A or exit_long_B or exit_long_SL or exit_long_TSL or exit_long_PD

        exit_short_A   = position_open and last_dir == -1 and short_below_fast_ma and cross_above_fast
        exit_short_B   = position_open and last_dir == -1 and cross_above_slow
        exit_short_SL  = (sl_short_level is not None) and (h >= sl_short_level)
        exit_short_TSL = (params.trail_sl_enable and trail_active and position_open and last_dir == -1 and h  >= trail_sl_level)
        exit_short_PD  = (params.peak_dd_enable and peak_dd_active and position_open and last_dir == -1 and peak_close_short < float('inf') and c > peak_close_short * (1.0 + params.peak_dd_pct / 100.0))
        exit_short     = exit_short_A or exit_short_B or exit_short_SL or exit_short_TSL or exit_short_PD

        long_entry   = (not position_open) and (last_dir != 1)  and cross_above_slow
        long_reentry = (not position_open) and (last_dir == 1)  and cross_above_fast and (c > s)
        short_entry   = (not position_open) and (last_dir != -1) and cross_below_slow
        short_reentry = (not position_open) and (last_dir == -1) and cross_below_fast and (c < s)
        
        trail_reentry_long  = (params.trail_sl_enable and trail_reentry_armed and not position_open and last_dir == 1 and cross_above_fast and c > s)
        trail_reentry_short = (params.trail_sl_enable and trail_reentry_armed and not position_open and last_dir == -1 and cross_below_fast and c < s)
        if trail_reentry_armed and last_dir == 1  and cross_below_slow: trail_reentry_armed = False
        if trail_reentry_armed and last_dir == -1 and cross_above_slow: trail_reentry_armed = False

        if params.atr_entry_enable:
            ae = atr_entry[i] if not np.isnan(atr_entry[i]) else 0.0
            if (not position_open) and (last_dir != 1) and cross_above_slow and ae > 0:
                pending_long = True; pending_short = False; pending_long_level = s + ae * params.atr_long_mult; long_entry = False
            if (not position_open) and (last_dir != -1) and cross_below_slow and ae > 0:
                pending_short = True; pending_long = False; pending_short_level = s - ae * params.atr_short_mult; short_entry = False
                
            if pending_long  and cross_below_slow: pending_long  = False
            if pending_short and cross_above_slow: pending_short = False
            if position_open: pending_long = False; pending_short = False
                
            if pending_long and (not position_open) and c >= pending_long_level: long_entry = True; pending_long = False
            if pending_short and (not position_open) and c <= pending_short_level: short_entry = True; pending_short = False

        flip_to_short = exit_long  and cross_below_slow and params.allow_shorts
        flip_to_long  = exit_short and cross_above_slow and params.allow_longs
        long_signal  = ((long_entry  or long_reentry  or trail_reentry_long)  and params.allow_longs)  or flip_to_long
        short_signal = ((short_entry or short_reentry or trail_reentry_short) and params.allow_shorts) or flip_to_short

        if exit_long and position_open and last_dir == 1:
            if exit_long_TSL:
                exit_px = trail_sl_level; exit_type_str = "TSL"; pct = ((trail_sl_level - entry_price) / entry_price * 100.0) * params.leverage_long; trail_reentry_armed = True
            elif exit_long_SL:
                exit_px = c; exit_type_str = "SL"; pct = ((sl_long_level - entry_price) / entry_price * 100.0) * params.leverage_long if params.atr_sl_enable else -params.sl_risk_pct
            elif exit_long_PD:
                exit_px = c; exit_type_str = "PD"; pct = ((c - entry_price) / entry_price * 100.0) * params.leverage_long
            else:
                exit_px = c; exit_type_str = "CL"; pct = ((c - entry_price) / entry_price * 100.0) * params.leverage_long

            if dates[i] >= trade_start:
                trades.append(Trade(entry_bar=entry_bar, entry_date=entry_date, entry_price=entry_price, direction=1, exit_bar=i, exit_date=dates[i], exit_price=exit_px, pct=pct, exit_type=exit_type_str))
            position_open = False
            if not flip_to_short: last_dir = 0
            
        elif exit_short and position_open and last_dir == -1:
            if exit_short_TSL:
                exit_px = trail_sl_level; exit_type_str = "TSS"; pct = ((entry_price - trail_sl_level) / entry_price * 100.0) * params.leverage_short; trail_reentry_armed = True
            elif exit_short_SL:
                exit_px = c; exit_type_str = "SL"; pct = ((entry_price - sl_short_level) / entry_price * 100.0) * params.leverage_short if params.atr_sl_enable else -params.sl_risk_pct
            elif exit_short_PD:
                exit_px = c; exit_type_str = "PD"; pct = ((entry_price - c) / entry_price * 100.0) * params.leverage_short
            else:
                exit_px = c; exit_type_str = "CS"; pct = ((entry_price - c) / entry_price * 100.0) * params.leverage_short
                
            if dates[i] >= trade_start:
                trades.append(Trade(entry_bar=entry_bar, entry_date=entry_date, entry_price=entry_price, direction=-1, exit_bar=i, exit_date=dates[i], exit_price=exit_px, pct=pct, exit_type=exit_type_str))
            position_open = False
            if not flip_to_long: last_dir = 0

        if long_signal and not position_open:
            position_open = True; last_dir = 1; entry_price = c; entry_bar = i; entry_date = dates[i]
            long_above_fast_ma = False; short_below_fast_ma = False; entry_atr = float(atr[i]) if not np.isnan(atr[i]) else 0.0
            trail_active = False; trail_sl_level = 0.0; trail_reentry_armed = False
            peak_dd_active = False; peak_close_long = c
        elif short_signal and not position_open:
            position_open = True; last_dir = -1; entry_price = c; entry_bar = i; entry_date = dates[i]
            long_above_fast_ma = False; short_below_fast_ma = False; entry_atr = float(atr[i]) if not np.isnan(atr[i]) else 0.0
            trail_active = False; trail_sl_level = float('inf'); trail_reentry_armed = False
            peak_dd_active = False; peak_close_short = c

    # Close open position at end
    if position_open and dates[-1] >= trade_start:
        c_val = float(close[-1])
        if last_dir == 1:
            pct = ((c_val - entry_price) / entry_price * 100.0) * params.leverage_long
            trades.append(Trade(entry_bar=entry_bar, entry_date=entry_date, entry_price=entry_price, direction=1, exit_bar=n-1, exit_date=dates[-1], exit_price=c_val, pct=pct, exit_type="END"))
        elif last_dir == -1:
            pct = ((entry_price - c_val) / entry_price * 100.0) * params.leverage_short
            trades.append(Trade(entry_bar=entry_bar, entry_date=entry_date, entry_price=entry_price, direction=-1, exit_bar=n-1, exit_date=dates[-1], exit_price=c_val, pct=pct, exit_type="END"))

    return trades

# ── 2. Walk-Forward Setup ────────────────────────────────────────────────────

def get_checkpoints(start_year: int, start_month: int, end_date: pd.Timestamp) -> list[pd.Timestamp]:
    checkpoints = []
    y, m = start_year, start_month
    while True:
        cp = pd.Timestamp(date(y, m, 1))
        if cp >= end_date:
            break
        checkpoints.append(cp)
        m += 6
        if m > 12:
            m -= 12
            y += 1
    return checkpoints

def _eval_param(args):
    df_slice, p, train_start, train_end = args
    from backtest.engine import backtest
    res = backtest(df_slice, p, train_start.isoformat(), train_end.isoformat(), trade_start=train_start.isoformat())
    if res["liq_risk"]: return (-999.0, p)
    c = res.get("calmar", 0.0)
    c = c if c > 0 else res.get("pl_pct", 0) / 100.0
    return (c, p)

def run_training(df: pd.DataFrame, train_start: pd.Timestamp, train_end: pd.Timestamp, params_grid: list[AMBParams]) -> AMBParams:
    """Evaluate grid on slice, return best by Calmar using multiprocessing."""
    df_slice = df[(df.index >= train_start) & (df.index <= train_end)].copy()
    if len(df_slice) < 50:
        return params_grid[0]
        
    best_p = params_grid[0]
    best_calmar = -999.0
    
    args_list = [(df_slice, p, train_start, train_end) for p in params_grid]
    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = executor.map(_eval_param, args_list)
        
    for c, p in results:
        if c > best_calmar:
            best_calmar = c
            best_p = p
            
    return best_p

def main():
    ticker = "BTC-USD"
    source = "binance"
    console.print(f"[bold cyan]Fetching {source} data for {ticker}...[/bold cyan]")
    df = get_all(ticker, source=source)
    
    grid = _grid_params("btc_quick")
    console.print(f"Grid size: {len(grid)}")
    
    # Baseline for scenario C
    baseline_params = AMBParams(
        slow_ma_len=130, slow_ma_type="EMA",
        fast_ma_len=60, fast_ma_type="SMA",
        allow_longs=True, allow_shorts=True,
        leverage_long=3.75, leverage_short=0.5,
        sl_enable=True, sl_risk_pct=3.0, signal_tf="D",
        atr_sl_enable=False, atr_entry_enable=False,
        trail_sl_enable=False, peak_dd_enable=False, use_fast_ma=True
    )
    
    # Checkpoints starting 2021-10-01 (to allow for full 48M lookback from Aug 2017)
    end_date = df.index[-1]
    checkpoints = get_checkpoints(2021, 10, end_date)
    
    console.print(f"[yellow]Running {len(checkpoints)} Optimization Checkpoints...[/yellow]")
    
    best_A_map = {}
    best_B_map = {}
    best_C_map = {}
    best_D_map = {}
    
    for cp in tqdm(checkpoints, desc="Training Checkpoints"):
        # Scenario A: Train on CP - 24 months to CP
        cp_train_start_A = cp - pd.DateOffset(months=24)
        best_A_map[cp] = run_training(df, cp_train_start_A, cp, grid)

        # Scenario B: Expanding Window (from 2017 to CP)
        cp_train_start_B = pd.Timestamp('2017-08-17')
        best_B_map[cp] = run_training(df, cp_train_start_B, cp, grid)

        # Scenario C: Static Baseline
        best_C_map[cp] = baseline_params
        
        # Scenario D: Train on CP - 48 months to CP (Halving Cycle)
        cp_train_start_D = cp - pd.DateOffset(months=48)
        best_D_map[cp] = run_training(df, cp_train_start_D, cp, grid)
        
    console.print("[cyan]Training complete. Running Walk-Forward Simulation...[/cyan]")
    
    oos_start = checkpoints[0] # 2021-10-01
    
    def simulate_and_print(name: str, p_map: dict):
        trades = run_stitched_strategy(df, p_map, trade_start=oos_start)
        # compute_metrics strictly wants a single AMBParams obj, but we can pass a dummy one 
        # since strategy was stitched. Will update `compute_metrics` to not crash.
        metrics = compute_metrics(trades, baseline_params, oos_start.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        
        console.print(f"\\n[bold green]=== {name} ===[/bold green]")
        console.print(f"Trades:     {metrics['trades']}")
        console.print(f"Net P/L:    {metrics['pl_pct']}%")
        console.print(f"Max DD:     {metrics['max_dd']}%")
        console.print(f"Calmar:     {metrics['calmar']}")
        console.print(f"Win Rate:   {metrics['win_rate']}%")
        console.print(f"Expectancy: {metrics['expectancy']}")
        
    simulate_and_print("Scenario A: The Sprinter (Rolling 24M)", best_A_map)
    simulate_and_print("Scenario B: The Elephant (Expanding Window)", best_B_map)
    simulate_and_print("Scenario C: The Stubborn (Baseline v1.8.5)", best_C_map)
    simulate_and_print("Scenario D: The Cycle Surfer (Rolling 48M)", best_D_map)


if __name__ == "__main__":
    main()

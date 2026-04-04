# AMB Strategy Logic Comparison: Pine Script vs Python

## STATUS: Logic Implementation Complete

Both Pine Script v1.5 and Python backtest implement the **exact same signal logic**:

### Signal Definitions (IDENTICAL)

| Signal | Pine Script | Python | Match? |
|--------|-----------|--------|--------|
| **OL Entry** | `not position_open and lastSignalDirection != 1 and cross_above_slowMA` | `(not position_open) and (last_dir != 1) and cross_above_slow` | ✅ |
| **OL Re-Entry** | `not position_open and lastSignalDirection == 1 and cross_above_fastMA and close > slowMA` | `(not position_open) and (last_dir == 1) and cross_above_fast and (c > s)` | ✅ |
| **CL Exit A** | `position_open and lastSignalDirection == 1 and longAboveFastMA and cross_below_fastMA` | `position_open and last_dir == 1 and long_above_fast_ma and cross_below_fast` | ✅ |
| **CL Exit B** | `position_open and lastSignalDirection == 1 and cross_below_slowMA` | `position_open and last_dir == 1 and cross_below_slow` | ✅ |
| **CL Exit SL** | `not na(sl_long_level) and low <= sl_long_level` | `(sl_long_level is not None) and (lo <= sl_long_level)` | ✅ |
| **Flip to Short** | `exitLong and cross_below_slowMA and allowShorts` | `exit_long and cross_below_slow and allow_shorts` | ✅ |

### State Machine (IDENTICAL)

Both implement **Exits before Entries** (enables same-bar flips):
1. Check all EXIT conditions
2. If exit triggered: close trade, reset state
3. Check all ENTRY conditions
4. If entry triggered: open new trade

### Fast MA State Tracking (IDENTICAL)

Both track `longAboveFastMA` and `shortBelowFastMA`:
- Set to TRUE when price closes beyond MA during open position
- Reset to FALSE on exit
- Required for Exit A condition

### SL Logic (IDENTICAL)

```
Long SL  = entry_price * (1.0 - sl_risk_pct / (100.0 * leverage_long))
Short SL = entry_price * (1.0 + sl_risk_pct / (100.0 * leverage_short))
```

Both check intra-bar extremes (low for long, high for short).

### Crossover Detection (IDENTICAL)

Both use standard crossover definition:
```
cross_above = (close > ma) and (close_prev <= ma_prev)
cross_below = (close < ma) and (close_prev >= ma_prev)
```

---

## KNOWN DIFFERENCES: Results Discrepancy (45 vs 79 trades)

**Python**: 45 trades, +1,554% P/L, -25.6% MaxDD (2021-04-14 to 2023-10-31)  
**TradingView**: 79 trades, +895% P/L, -12.65% MaxDD

### Possible Causes

1. **Price Data Source**
   - yfinance vs TradingView data (different OHLC, splits/adjustments?)
   - Daily close vs intraday prices?

2. **MA Calculation**
   - Both use SMA(100) and SMA(44)
   - Potential: different rounding in bar-by-bar calculation

3. **Time Zone or Bar Alignment**
   - TradingView may use different session times for D (daily)
   - yfinance uses UTC close

4. **Leverage/Position Sizing**
   - Python: applies leverage to P/L %
   - TradingView: may apply differently to position capital?

### Verification Steps

To match TradingView exactly:

1. **Export TradingView MA values** (100 SMA, 44 SMA) for same dates
2. **Compare CSV** against `ma_export.csv` (Python export)
3. **Check first crossover** dates — if different, data source is the issue
4. **Check SL calculation** — confirm entry price and SL level match
5. **Count trades by date** — identify where extra 34 trades occur

---

## Code Locations

- **Pine Script Signal Logic**: ambTradeSignalIndicator.pine, lines 95-170
- **Python Signal Logic**: backtest/strategy_amb.py, lines 155-220
- **State Machine (Pine)**: ambTradeSignalIndicator.pine, lines 295-380
- **State Machine (Python)**: backtest/strategy_amb.py, lines 222-262

---

## NEXT STEPS

1. **Export TradingView chart data** (close, Slow MA, Fast MA) for 2021-04-14 to 2023-10-31
2. **Compare against** Python `ma_export.csv`
3. **Identify data discrepancy** or signal timing difference
4. **Adjust Python** if needed to match TradingView price source

Once matched, backtest results will be 100% aligned.

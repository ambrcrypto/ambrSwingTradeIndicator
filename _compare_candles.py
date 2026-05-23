import sqlite3
import pandas as pd

DB = r"C:\Users\arneb\OneDrive\Documents\20_IT\ClaudeWorkEnv\ambTradingAutomation\state\phase1.sqlite3"
con = sqlite3.connect(DB)
rows = con.execute(
    "SELECT candle_date_utc, close, high, low FROM candles "
    "WHERE candle_date_utc BETWEEN '2026-04-01' AND '2026-04-10' ORDER BY candle_date_utc"
).fetchall()
con.close()

# Load backtest cache
df_cache = pd.read_csv(
    r"C:\Users\arneb\OneDrive\Documents\20_IT\ClaudeWorkEnv\ambSwingTradeIndicator\backtest\cache\bybit_BTC_USD.csv",
    index_col=0, parse_dates=True
)

print("Phase1 DB vs backtest cache Bybit — April 1-10 2026:")
print(f"{'Date':<12} {'DB close':>12} {'Cache close':>12} {'diff%':>8}  {'DB high':>10} {'Cache high':>10}")
for rdate, rclose, rhigh, rlow in rows:
    cache_row = df_cache.loc[df_cache.index.strftime('%Y-%m-%d') == rdate]
    if cache_row.empty:
        print(f"  {rdate}: DB={rclose:.1f}  cache=MISSING")
        continue
    cc = float(cache_row['close'].iloc[0])
    ch = float(cache_row['high'].iloc[0])
    diff_pct = abs(rclose - cc) / cc * 100
    print(f"  {rdate}  DB={rclose:>12.1f}  cache={cc:>12.1f}  diff={diff_pct:>6.2f}%  DB_high={rhigh:>10.1f}  cache_high={ch:>10.1f}")

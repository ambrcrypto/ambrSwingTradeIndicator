"""
data.py – Download and cache OHLCV data via yfinance.

Caches as CSV per ticker in backtest/cache/.
Re-downloads automatically if cache is > 1 day old.
"""

import os
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR  = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Alias map: user-friendly name → yfinance symbol
TICKER_MAP: dict[str, str] = {
    "BTCUSDT": "BTC-USD",
    "ETHUSDT": "ETH-USD",
    "BTC":     "BTC-USD",
    "ETH":     "ETH-USD",
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
    "VOO":     "VOO",
    "SPY":     "SPY",
    "QQQ":     "QQQ",
}

# Predefined test periods (start, end).  None = today.
# Each entry: (label, start_date, end_date)
PERIODS: dict[str, tuple[str | None, str | None]] = {
    "2021_default":       ("2021-04-14", None),          # Pine Script default → present
    "full":               ("2010-01-01", None),          # max available
    "bull_2020_2021":     ("2020-10-01", "2021-11-30"),  # crypto bull
    "bear_2022":          ("2022-01-01", "2022-12-31"),  # crypto bear
    "recovery_2023_2025": ("2023-01-01", "2025-12-31"),  # recovery + new ATH
    "last_2y":            (None,         None),          # dynamic, filled in get_periods()
}


def _yf_ticker(ticker: str) -> str:
    return TICKER_MAP.get(ticker.upper(), ticker)


def _cache_path(yf_sym: str) -> Path:
    safe = yf_sym.replace("-", "_").replace("/", "_")
    return CACHE_DIR / f"{safe}.csv"


def _download_fresh(yf_sym: str) -> pd.DataFrame:
    """Download all available history from yfinance."""
    df = yf.download(yf_sym, start="2010-01-01", progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No data returned for {yf_sym}")
    # Flatten MultiIndex columns that yfinance sometimes returns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df.index.name = "date"
    return df


def get_all(ticker: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Return full history DataFrame (open/high/low/close/volume).
    Uses on-disk cache; refreshes if > 23h old or force_refresh=True.
    """
    yf_sym = _yf_ticker(ticker)
    cache  = _cache_path(yf_sym)

    if cache.exists() and not force_refresh:
        age = datetime.now() - datetime.fromtimestamp(cache.stat().st_mtime)
        if age < timedelta(hours=23):
            df = pd.read_csv(cache, index_col="date", parse_dates=True)
            return df

    df = _download_fresh(yf_sym)
    df.to_csv(cache)
    return df


def get_slice(ticker: str,
              start: str | None = None,
              end:   str | None = None,
              force_refresh: bool = False,
              warmup: bool = False) -> pd.DataFrame:
    """
    Return OHLCV slice filtered by [start, end].
    Dates are ISO strings "YYYY-MM-DD" or None.

    warmup=True  : skip the start-date filter so full history (from 2010)
                   is returned.  Enables the strategy state machine to warm up
                   MAs and position state before the trade recording window.
                   Pass trade_start to run_strategy() to filter which trades
                   are recorded.  Mirrors TradingView behaviour where the main
                   state machine runs from bar 0 before the backtest window.
    """
    df = get_all(ticker, force_refresh=force_refresh)
    if start and not warmup:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df.copy()


def get_periods(ticker: str) -> dict[str, tuple[str, str]]:
    """
    Return all PERIODS that have data for this ticker,
    with actual start/end dates filled in.
    """
    df = get_all(ticker)
    first = df.index[0].strftime("%Y-%m-%d")
    last  = df.index[-1].strftime("%Y-%m-%d")

    result = {}
    for name, (s, e) in PERIODS.items():
        # Fill dynamic dates
        if name == "last_2y":
            two_years_ago = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
            s, e = two_years_ago, last

        s = s or first
        e = e or last

        # Skip if this period has no data for ticker
        if pd.Timestamp(e) < pd.Timestamp(first):
            continue
        # Clamp start to first available
        s_eff = max(pd.Timestamp(s), pd.Timestamp(first)).strftime("%Y-%m-%d")

        sub = df[(df.index >= pd.Timestamp(s_eff)) & (df.index <= pd.Timestamp(e))]
        if len(sub) < 50:   # need at least 50 bars
            continue

        result[name] = (s_eff, e)

    return result


def describe(ticker: str) -> None:
    """Print a summary of available data for a ticker."""
    df = get_all(ticker)
    print(f"\n{'='*50}")
    print(f"  {_yf_ticker(ticker)}")
    print(f"  Bars:  {len(df)}")
    print(f"  From:  {df.index[0].date()}")
    print(f"  To:    {df.index[-1].date()}")
    print(f"  Close: {df['close'].iloc[-1]:.2f}")
    print(f"{'='*50}")
    for name, (s, e) in get_periods(ticker).items():
        sub = df[(df.index >= pd.Timestamp(s)) & (df.index <= pd.Timestamp(e))]
        print(f"  {name:<22} {s} → {e}  ({len(sub)} bars)")


if __name__ == "__main__":
    for t in ["BTC-USD", "ETH-USD", "VOO"]:
        describe(t)

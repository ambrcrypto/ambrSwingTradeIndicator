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
    # ── Reference periods (not used in robustness – cumulative/overlapping) ────
    "2021_default":           ("2021-04-14", None),   # Pine Script default → present
    "full":                   ("2010-01-01", None),   # max available
    "last_2y":                (None,         None),   # dynamic, filled in get_periods()
    # ── BTC market regime periods: 3 full cycles (2017–present) ────────────────
    # Non-overlapping phase slices for regime-diverse robustness testing.
    # P1–P6 are fixed anchors; P7 rolls forward every 6 months.
    "btc_p1_bull_2017":       ("2017-01-01", "2017-12-31"),  # Zyklus 2 Bull:  $900 → $20k
    "btc_p2_bear_2018":       ("2018-01-01", "2018-12-31"),  # Zyklus 2 Bear:  −84%
    "btc_p3_sideways_2019":   ("2019-01-01", "2020-02-29"),  # Seitwärts / Recovery
    "btc_p4_bull_2020_2021":  ("2020-03-01", "2021-11-30"),  # Zyklus 3 Bull:  COVID + ATH $69k
    "btc_p5_bear_2022":       ("2021-12-01", "2022-12-31"),  # Zyklus 3 Bear:  −78%, FTX
    "btc_p6_bull_2023_2024":  ("2023-01-01", "2024-12-31"),  # Zyklus 4 Bull:  ETF + Halving
    "btc_p7_current_2025":    ("2025-01-01", None),          # Laufend (Out-of-sample)
}

# Periods excluded from robustness scoring (cumulative or overlapping with regime periods).
# run_robustness() uses all periods EXCEPT these.
ROBUSTNESS_EXCLUDE: frozenset[str] = frozenset({"2021_default", "full", "last_2y"})


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

"""
ticker_config.py – per-ticker default AMBParams.

Used by run.py and run_optimize.py as starting defaults.
CLI flags always override these values.

signal_tf controls how often MA crossover signals are evaluated:
  "D"  – every trading day (default, good for volatile assets like BTC/ETH)
  "W"  – only the first trading day of each calendar week
  "M"  – only the first trading day of each calendar month
Stop-loss checks always run daily regardless of signal_tf.
"""

from __future__ import annotations
from .strategy_amb import AMBParams


TICKER_CONFIG: dict[str, AMBParams] = {
    # ── Crypto ────────────────────────────────────────────────────────────
    "BTC-USD": AMBParams(
        slow_ma_len=130, slow_ma_type="EMA",   # rollierender BTC-Default fuer Review-Fenster ab 2025-04-01
        fast_ma_len=60,  fast_ma_type="SMA",
        use_fast_ma=True,
        leverage_long=3.75, leverage_short=0.5,
        sl_enable=True, sl_risk_pct=3.0,
        signal_tf="D",
    ),
    "ETH-USD": AMBParams(
        slow_ma_len=130, slow_ma_type="EMA",
        fast_ma_len=44,  fast_ma_type="SMA",
        use_fast_ma=True,
        leverage_long=3.0, leverage_short=1.0,
        sl_enable=True, sl_risk_pct=8.0,
        signal_tf="D",
    ),
    # ── Equities / ETFs ────────────────────────────────────────────────────
    "VOO": AMBParams(
        slow_ma_len=130, slow_ma_type="EMA",
        fast_ma_len=44,  fast_ma_type="SMA",
        use_fast_ma=False,  # Slow MA only: equities need fewer trades, not fast exits
        leverage_long=2.0, leverage_short=1.0,
        sl_enable=True, sl_risk_pct=8.0,
        signal_tf="W",   # weekly signals
    ),
    "SPY": AMBParams(
        slow_ma_len=130, slow_ma_type="EMA",
        fast_ma_len=44,  fast_ma_type="SMA",
        use_fast_ma=False,
        leverage_long=2.0, leverage_short=1.0,
        sl_enable=True, sl_risk_pct=8.0,
        signal_tf="W",
    ),
    "QQQ": AMBParams(
        slow_ma_len=130, slow_ma_type="EMA",
        fast_ma_len=44,  fast_ma_type="SMA",
        use_fast_ma=False,
        leverage_long=2.0, leverage_short=1.0,
        sl_enable=True, sl_risk_pct=8.0,
        signal_tf="W",
    ),
}


def get_ticker_params(ticker: str) -> AMBParams:
    """Return default AMBParams for ticker, or global default if not configured."""
    return TICKER_CONFIG.get(ticker, AMBParams())

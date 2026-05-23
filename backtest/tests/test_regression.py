"""
test_regression.py – Golden-Reference-Test für v1.6.1 BTC-USD.

Prüft dass die Python-Backtest-Engine für eine FIXE historische Periode
exakt die bekannten Referenzwerte liefert.

Zweck: Regressionssicherung – jede Code-Änderung an strategy_amb.py
oder engine.py die diese Zahlen verändert, schlägt hier sofort an.

Fixfenster: 2021-04-14 → 2023-10-31 (historisch, stabil, nie ändernd)
Referenzwerte aus Diagnose-Run 2026-04-06.

Verwendung:
    cd ambSwingTradeIndicator
    pytest backtest/tests/test_regression.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.data import get_slice
from backtest.engine import compute_metrics
from backtest.strategy_amb import AMBParams, run_strategy

# ── Historische Referenzwerte (v1.6.1, BTC-USD, 2021-04-14 → 2023-10-31) ───
# Ermittelt mit diagnose_discrepancy.py am 2026-04-06.
# Fixe Test-Konfiguration: SMA130/SMA44 / LL3.0 / LS0.5 / SL6%
REF_TRADE_COUNT = 42
REF_PL_PCT      = 145.53   # ±2% Toleranz (rel)
REF_MAX_DD      = 32.33    # ±5% Toleranz (rel)

PERIOD_START = "2021-04-14"
PERIOD_END   = "2023-10-31"
TICKER       = "BTC-USD"
HISTORICAL_PARAMS = AMBParams(
    slow_ma_len=130,
    slow_ma_type="SMA",
    fast_ma_len=44,
    fast_ma_type="SMA",
    use_fast_ma=True,
    allow_longs=True,
    allow_shorts=True,
    leverage_long=3.0,
    leverage_short=0.5,
    sl_enable=True,
    sl_risk_pct=6.0,
    signal_tf="D",
)


@pytest.fixture(scope="module")
def btc_trades():
    """Einmaliger Backtest-Run für alle Tests in diesem Modul."""
    params      = HISTORICAL_PARAMS
    df_full     = get_slice(TICKER, warmup=True)
    end_ts      = pd.Timestamp(PERIOD_END)
    df_cut      = df_full[df_full.index <= end_ts].copy()
    trade_start = pd.Timestamp(PERIOD_START)
    all_trades  = run_strategy(df_cut, params, trade_start=trade_start)
    return [t for t in all_trades if t.entry_date >= trade_start]


@pytest.fixture(scope="module")
def btc_metrics(btc_trades):
    params = HISTORICAL_PARAMS
    return compute_metrics(btc_trades, params, PERIOD_START, PERIOD_END)


class TestRegressionV161:
    def test_trade_count(self, btc_trades):
        """Anzahl Trades muss exakt 42 sein (v1.6.1 Referenz)."""
        assert len(btc_trades) == REF_TRADE_COUNT, (
            f"Trade-Count geändert: erwartet {REF_TRADE_COUNT}, "
            f"erhalten {len(btc_trades)}. "
            f"Prüfe ob strategy_amb.py Signal-Logik oder Daten geändert wurden."
        )

    def test_pl_pct(self, btc_metrics):
        """P/L% liegt innerhalb ±2% des Referenzwerts."""
        assert btc_metrics["pl_pct"] == pytest.approx(REF_PL_PCT, rel=0.02), (
            f"P/L% ausserhalb Toleranz: erwartet ~{REF_PL_PCT}%, "
            f"erhalten {btc_metrics['pl_pct']:.2f}%"
        )

    def test_max_dd(self, btc_metrics):
        """MaxDD% liegt innerhalb ±5% des Referenzwerts."""
        assert btc_metrics["max_dd"] == pytest.approx(REF_MAX_DD, rel=0.05), (
            f"MaxDD ausserhalb Toleranz: erwartet ~{REF_MAX_DD}%, "
            f"erhalten {btc_metrics['max_dd']:.2f}%"
        )

    def test_no_trades_with_wrong_config(self):
        """Sanity-Check: komplett andere Konfiguration liefert andere Trade-Anzahl."""
        # SMA(200) over same period should give fewer signals (trend is slower to react)
        from backtest.strategy_amb import AMBParams
        params_wrong = AMBParams(slow_ma_len=200, fast_ma_len=44, sl_enable=False,
                                  leverage_long=3.0, leverage_short=0.5)
        df_full  = get_slice(TICKER, warmup=True)
        end_ts   = pd.Timestamp(PERIOD_END)
        df_cut   = df_full[df_full.index <= end_ts].copy()
        ts       = pd.Timestamp(PERIOD_START)
        trades   = run_strategy(df_cut, params_wrong, trade_start=ts)
        trades_w = [t for t in trades if t.entry_date >= ts]
        # Different config must produce different result (catches accidental parameter override)
        assert len(trades_w) != REF_TRADE_COUNT, (
            "SMA200-Config ergab die gleiche Anzahl Trades wie v1.6.1 – "
            "möglicherweise wird TICKER_CONFIG nicht korrekt geladen."
        )

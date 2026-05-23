"""
test_signals.py – Synthetische Unit-Tests für AMB Signal-Logik.

Jeder Test konstruiert eine minimale, deterministische Preisreihe
die genau ein Signal-Szenario aus TESTCASES.md abdeckt.

Gruppen: A (Entries), B (Re-Entries), C (Exits), D (SL), F (Flip)

Verwendung:
    cd ambSwingTradeIndicator
    pytest backtest/tests/ -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.strategy_amb import AMBParams, run_strategy


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def make_ohlcv(
    closes: list[float],
    highs:  list[float] | None = None,
    lows:   list[float] | None = None,
) -> pd.DataFrame:
    """Build minimal OHLCV DataFrame from close prices.
    highs/lows default to close ±1% if not supplied.
    """
    n   = len(closes)
    c   = np.array(closes, dtype=float)
    h   = np.array(highs,  dtype=float) if highs is not None else c * 1.01
    lo  = np.array(lows,   dtype=float) if lows  is not None else c * 0.99
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": c, "high": h, "low": lo, "close": c, "volume": np.ones(n)},
        index=dates,
    )


def _params(**kw) -> AMBParams:
    """AMBParams with test defaults (small MAs, no SL, both directions)."""
    defaults = dict(slow_ma_len=5, fast_ma_len=2, sl_enable=False,
                    allow_longs=True, allow_shorts=True)
    defaults.update(kw)
    return AMBParams(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Gruppe A – Erstmalige Entries (TC A-01, A-02, A-03, A-04)
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupA:
    def test_A01_long_entry_cross_above_slow(self):
        """A-01: Kurs schliesst über SlowMA (Crossover) → OL Entry, Long eröffnet."""
        # slow=SMA5: warmup 5 bars @ 10, then bar 5 = 20
        # SMA5[4]=10, SMA5[5]=(10*4+20)/5=12  →  c=20 > 12, c0=10 ≤ 10  → cross
        prices = [10, 10, 10, 10, 10, 20]
        trades = run_strategy(make_ohlcv(prices), _params(allow_shorts=False))
        assert len(trades) == 1
        assert trades[0].direction == 1

    def test_A02_no_entry_no_cross(self):
        """A-02: Flache Preise, kein Cross → kein Trade."""
        prices = [10, 10, 10, 10, 10, 10]
        trades = run_strategy(make_ohlcv(prices), _params())
        assert len(trades) == 0

    def test_A03_short_entry_cross_below_slow(self):
        """A-03: Kurs schliesst unter SlowMA (Crossunder) → OS Entry, Short eröffnet."""
        # SMA5[4]=20, SMA5[5]=(20*4+10)/5=18  →  c=10 < 18, c0=20 ≥ 20  → cross
        prices = [20, 20, 20, 20, 20, 10]
        trades = run_strategy(make_ohlcv(prices), _params(allow_longs=False))
        assert len(trades) == 1
        assert trades[0].direction == -1

    def test_A04_no_short_entry_upward_bar(self):
        """A-04: Kurs steigt, kein Crossunder → kein Short."""
        prices = [10, 10, 10, 10, 10, 15]
        trades = run_strategy(make_ohlcv(prices), _params(allow_longs=False))
        assert len(trades) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Gruppe B – Re-Entries (TC B-01, B-02)
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupB:
    def test_B01_long_reentry_cross_above_fast(self):
        """B-01: lastDir=Long, kein Trade offen, Kurs über SlowMA, CrossAbove FastMA → RL."""
        # Sequence:
        #   bar 5: OL Entry (cross above slow)       → lastDir=1, open=True
        #   bar 6: close=22, longAboveFastMA gets set (22 > fast_ma)
        #   bar 7: close=8  → cross below slow → CL Exit B (no flip: shorts disabled)
        #   bar 8: close=16 → cross above fast (c0=8 ≤ fast_ma prev), close > slow MA → RL
        #
        # Prices:    0    1    2    3    4    5    6    7    8
        prices  = [10,  10,  10,  10,  10,  20,  22,   8,  16]
        # SMA5:  NaN  NaN  NaN  NaN   10   11 12.4 13.2 13.2* → check bar8 below
        # SMA2:  NaN   10   10   10   10   15   21   15   12
        # Bar 5: c=20>s=11, c0=10≤s0=10 → OL Entry
        # Bar 6: c=22>f=21 → longAboveFastMA=True
        # Bar 7: c=8<s=(10+10+10+20+22+8*...)/5
        #   SMA5[7]=(10+10+20+22+8)/5=14  c=8<14, c0=22≥12.4 → cross_below_slow=True → Exit
        # Bar 8: lastDir=1, not open
        #   SMA5[8]=(10+20+22+8+16)/5=15.2  c=16>15.2 ✓
        #   SMA2[8]=(8+16)/2=12  c=16>12, c0=8≤f0=SMA2[7]=(22+8)/2=15 → cross_above_fast=True
        #   → long_reentry fires ✅
        trades = run_strategy(make_ohlcv(prices), _params(allow_shorts=False))
        assert len(trades) == 2
        assert all(t.direction == 1 for t in trades)
        # Second trade is re-entry after first closed
        assert trades[1].entry_bar > trades[0].exit_bar

    def test_B02_no_reentry_when_below_slow(self):
        """B-02: FastMA cross aber Kurs unter SlowMA → kein RL."""
        # Same sequence as B01 but bar 8 close=9 (below slow MA after exit)
        # SMA5[8] ≈ (10+20+22+8+9)/5=13.8, c=9 < 13.8 → condition c > slow fails → no reentry
        prices = [10, 10, 10, 10, 10, 20, 22, 8, 9]
        trades = run_strategy(make_ohlcv(prices), _params(allow_shorts=False))
        # Only 1 trade (the first Long), no re-entry
        assert len(trades) == 1
        assert trades[0].direction == 1


# ─────────────────────────────────────────────────────────────────────────────
# Gruppe C – Exits (TC C-01, C-02)
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupC:
    def test_C01_exit_long_A_cross_below_fast(self):
        """C-01: Long offen, FastMA je berührt, CrossUnder FastMA → CL-A Exit."""
        # slow=SMA5, fast=SMA2
        # Bar 5: OL Entry at c=25  (SMA5[5]=(10*4+25)/5=13, cross above slow)
        # Bar 6: c=30 > fast_ma[6]=(25+30)/2=27.5 → longAboveFastMA=True
        # Bar 7: c=22, fast_ma[7]=(30+22)/2=26, slow_ma[7]=(10+10+10+25+30+22)/... SMA5=(10+25+30+22)/5... 
        #   SMA5[7]=(10*2+25+30+22)/5 = (10+10+25+30+22)/5=19.4  c=22>19.4: NOT crossing slow ✓
        #   cross_below_fast: c=22 < f=26, c0=30 ≥ f0=27.5 → True → CL-A ✅
        prices = [10, 10, 10, 10, 10, 25, 30, 22]
        trades = run_strategy(make_ohlcv(prices), _params(allow_shorts=False))
        assert len(trades) == 1
        assert trades[0].direction == 1
        assert trades[0].exit_type == "CL"

    def test_C02_exit_long_B_cross_below_slow(self):
        """C-02: Long offen, FastMA nie berührt (fast_ma > price at entry), CrossUnder SlowMA → CL-B."""
        # Use slow=SMA2 (reactive), fast=SMA10 (sticky, high from previous high prices)
        # Phase 1: 10 bars at 30 → fast_ma (SMA10) gets seeded at ~30
        # Phase 2: 5 bars at 10 → price drops, fast_ma slowly declines but still high
        # Phase 3: bar 15=15 → cross above slow (SMA2=(10+15)/2=12.5, c=15>12.5, c0=10≤10 ✓)
        #          fast_ma[15] = SMA10 = mean([30,30,30,10,10,10,10,10,10,15])=(155)/10=15.5 ← wait
        #          Actually SMA10 at bar 15 = mean of bars 6-15:
        #          bars 6-9=30 (4 bars), bars 10-14=10 (5 bars), bar 15=15 → (4×30+5×10+15)/10=17.5
        #          c=15, f=17.5  → longAboveFastMA = (15 > 17.5) = False ✅ 
        # Phase 4: bar 16=8 → cross below slow (SMA2[16]=(15+8)/2=11.5, c=8<11.5, c0=15≥12.5 ✓)
        #          → CL-B ✅
        prices = [30]*10 + [10]*5 + [15, 8]
        trades = run_strategy(
            make_ohlcv(prices),
            _params(slow_ma_len=2, fast_ma_len=10, allow_shorts=False),
        )
        assert len(trades) == 1
        assert trades[0].direction == 1
        assert trades[0].exit_type == "CL"


# ─────────────────────────────────────────────────────────────────────────────
# Gruppe D – Stop Loss (TC D-01, D-02, D-03, D-04)
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupD:
    def test_D01_sl_long(self):
        """D-01: Long offen, Intrabar-Low trifft SL-Level → SL Exit, P/L = -sl_risk_pct."""
        # Entry at bar 5 close=20
        # SL level = 20 * (1 - 6/(100*3)) = 20 * 0.98 = 19.6
        # Bar 7: close=21 (no exit via MA), but low=19.0 ≤ 19.6 → SL fires
        closes = [10, 10, 10, 10, 10, 20, 21, 21]
        lows   = [9.9]*5 + [19.8, 20.8, 19.0]  # bar 7 low hits SL
        trades = run_strategy(
            make_ohlcv(closes, lows=lows),
            _params(sl_enable=True, sl_risk_pct=6.0, leverage_long=3.0,
                    allow_shorts=False),
        )
        assert len(trades) == 1
        assert trades[0].exit_type == "SL"
        assert trades[0].pct == pytest.approx(-6.0)

    def test_D02_sl_short(self):
        """D-02: Short offen, Intrabar-High trifft SL-Level → SL Exit."""
        # Entry at bar 5 close=10
        # SL level = 10 * (1 + 6/(100*0.5)) = 10 * 1.12 = 11.2
        # Bar 7: close=9, but high=11.5 ≥ 11.2 → SL fires
        closes = [20, 20, 20, 20, 20, 10,  9,  9]
        highs  = [20.2]*5 + [10.1, 9.1, 11.5]  # bar 7 high hits SL
        trades = run_strategy(
            make_ohlcv(closes, highs=highs),
            _params(sl_enable=True, sl_risk_pct=6.0, leverage_short=0.5,
                    allow_longs=False),
        )
        assert len(trades) == 1
        assert trades[0].exit_type == "SL"
        assert trades[0].pct == pytest.approx(-6.0)

    def test_D03_sl_flip_allowed(self):
        """D-03: SL getroffen UND SlowMA gleichzeitig gekreuzt → Flip Short eröffnet."""
        # Long entry at bar 5 (close=20)
        # Bar 6: SL fires (low hits) AND cross below slow MA simultaneously
        #   → exit_long (SL) = True, cross_below_slow = True, allow_shorts = True
        #   → flip_to_short fires → Short opens same bar
        # SMA5[5]=11, SMA5[6]=(10+10+10+10+20+8)/5... SMA5[6]=(10+10+10+20+8)/5=11.6
        # c=8 < 11.6, c0=20 ≥ 11 → cross_below_slow ✅
        # SL level for long = 20 * (1 - 6/(100*3)) = 19.6
        closes = [10, 10, 10, 10, 10, 20,  8]
        lows   = [9.9]*5 + [19.8, 7.5]  # bar 6 low=7.5 hits SL at 19.6 — wait, entry is bar 5
        # Entry at bar 5 (idx 5), SL=19.6. Bar 6 (idx 6): low=7.5 ≤ 19.6 → SL fires.
        # Also cross_below_slow at bar 6 → flip
        trades = run_strategy(make_ohlcv(closes, lows=lows),
                               _params(sl_enable=True, sl_risk_pct=6.0, leverage_long=3.0))
        assert len(trades) == 2
        assert trades[0].direction == 1
        assert trades[0].exit_type == "SL"
        assert trades[1].direction == -1                  # flip: Short opened
        assert trades[0].exit_date == trades[1].entry_date  # same bar

    def test_D04_sl_no_flip_without_ma_cross(self):
        """D-04: SL getroffen, kein SlowMA-Cross → kein Flip."""
        # Long entry at bar 5, SL fires at bar 6 but price stays above slow MA
        # SMA5[6]=(10+10+10+10+20+16)/... SMA5[6]=(10+10+10+20+16)/5=13.2
        # close=16 > 13.2 → NOT crossing slow MA
        # low=19.0 ≤ SL=19.6 → SL fires, no flip
        closes = [10, 10, 10, 10, 10, 20, 16]
        lows   = [9.9]*5 + [19.8, 19.0]
        trades = run_strategy(make_ohlcv(closes, lows=lows),
                               _params(sl_enable=True, sl_risk_pct=6.0, leverage_long=3.0))
        assert len(trades) == 1
        assert trades[0].exit_type == "SL"


# ─────────────────────────────────────────────────────────────────────────────
# Gruppe F – Flip (TC F-01, F-04)
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupF:
    def test_F01_flip_long_to_short(self):
        """F-01: Long offen, CrossUnder SlowMA → CL Exit + OS Entry auf gleicher Kerze."""
        # Bar 5: OL Entry (cross above slow)
        # Bar 7: c=8 → cross_below_slow → exit_long + flip_to_short same bar
        prices = [10, 10, 10, 10, 10, 20, 22, 8]
        trades = run_strategy(make_ohlcv(prices), _params())
        assert len(trades) == 2
        assert trades[0].direction == 1
        assert trades[1].direction == -1
        assert trades[0].exit_date == trades[1].entry_date  # same bar (flip)

    def test_F04_flip_short_to_long(self):
        """F-04: Short offen, CrossOver SlowMA → CS Exit + OL Entry auf gleicher Kerze."""
        # Bar 5: OS Entry (cross below slow)
        # Bar 7: c=22 → cross above slow → exit_short + flip_to_long
        prices = [20, 20, 20, 20, 20, 10, 8, 22]
        trades = run_strategy(make_ohlcv(prices), _params())
        assert len(trades) == 2
        assert trades[0].direction == -1
        assert trades[1].direction == 1
        assert trades[0].exit_date == trades[1].entry_date

    def test_F07_no_flip_on_fresh_entry(self):
        """F-07: OL Entry ohne offene Position → kein CS auf gleicher Kerze."""
        prices = [10, 10, 10, 10, 10, 20]
        trades = run_strategy(make_ohlcv(prices), _params(allow_shorts=False))
        # Only 1 trade (one long entry), no spurious short
        assert len(trades) == 1
        assert trades[0].direction == 1

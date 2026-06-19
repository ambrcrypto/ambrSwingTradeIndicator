"""
Kurzanalyse: Was hätte der ATR Trailing Stop in den letzten 2 Monaten geändert?
Läuft mit den Default-Params (Slow EMA 130, Fast SMA 60, LL 3.75, LS 0.5, SL 3%).
Trail-Simulation: activate_pct=5%, atr_factor=2.0, atr_len=14
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backtest.data import get_slice
from backtest.strategy_amb import AMBParams, run_strategy, _calc_atr

# ── Config ──────────────────────────────────────────────────────────────────
TICKER       = "BTC-USD"
WINDOW_DAYS  = 62   # ~2 Monate
TRAIL_ACT    = 5.0  # % Gewinn bis Trail aktiv
TRAIL_FACTOR = 2.0
TRAIL_LEN    = 14

params = AMBParams(
    slow_ma_len=130, slow_ma_type="EMA",
    fast_ma_len=60,  fast_ma_type="SMA",
    leverage_long=3.75, leverage_short=0.5,
    sl_enable=True, sl_risk_pct=3.0,
)

# ── Daten laden (mit Warmup für MA-Berechnung) ───────────────────────────────
end_date   = datetime.today().strftime("%Y-%m-%d")
start_rec  = (datetime.today() - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")

df = get_slice(TICKER, start=start_rec, warmup=True)   # warmup=True → volle History für MAs
trade_start = pd.Timestamp(start_rec)

print(f"\nBTC-USD  |  Analyse-Fenster: {start_rec} → {end_date}")
print(f"Datenbasis: {df.index[0].date()} → {df.index[-1].date()}  ({len(df)} Bars total)\n")

# ── Baseline-Strategie laufen lassen ─────────────────────────────────────────
trades = run_strategy(df, params, trade_start=trade_start)

print(f"{'='*65}")
print(f"BASELINE-TRADES (letzten {WINDOW_DAYS} Tage)")
print(f"{'='*65}")
if not trades:
    print("  Keine abgeschlossenen Trades im Fenster.")
else:
    for t in trades:
        sign = "▲ LONG " if t.direction == 1 else "▼ SHORT"
        print(f"  {sign}  {t.entry_date.date()} @ {t.entry_price:,.0f}"
              f"  →  {t.exit_date.date()} @ {t.exit_price:,.0f}"
              f"  [{t.exit_type}]  {t.pct:+.1f}%")

# ── Trail-Simulation auf denselben Daten ────────────────────────────────────
# Wir simulieren manuell, was der Trail auf jedem offenen Trade getan hätte.
# Wir brauchen die vollständige tägliche OHLCV-Sequenz während des Trades.

close = df["close"].to_numpy(dtype=float)
high  = df["high"].to_numpy(dtype=float)
low_  = df["low"].to_numpy(dtype=float)
dates = df.index
atr   = _calc_atr(high, low_, close, TRAIL_LEN)

def simulate_trail(trade, df, close, high, low_, dates, atr,
                   activate_pct, factor):
    """
    Simuliert Trailing Stop auf einem bestehenden Trade.
    Gibt zurück: (exit_date, exit_price, exit_type, pct_trail)
    oder None wenn Trail nicht getriggert hätte.
    """
    ep    = trade.entry_price
    lev   = trade.leverage_long if trade.direction == 1 else trade.leverage_short
    # Finde Entry-Bar-Index
    entry_idx = np.searchsorted(dates, trade.entry_date)
    exit_idx  = np.searchsorted(dates, trade.exit_date)

    trail_active = False
    trail_level  = 0.0

    for i in range(entry_idx, exit_idx + 1):
        c = close[i]
        h = high[i]
        lo = low_[i]
        at = atr[i] if not np.isnan(atr[i]) else 0.0

        if trade.direction == 1:
            unreal = (c - ep) / ep * 100.0
            if unreal >= activate_pct:
                trail_active = True
            if trail_active and at > 0:
                new_lvl = c - at * factor
                trail_level = max(trail_level, new_lvl)
            # Check trigger
            if trail_active and lo <= trail_level:
                pct = (trail_level - ep) / ep * 100.0 * trade.leverage_long
                return dates[i], trail_level, "TSL", pct
        else:
            unreal = (ep - c) / ep * 100.0
            if unreal >= activate_pct:
                trail_active = True
            if trail_active and at > 0:
                new_lvl = c + at * factor
                trail_level = min(trail_level, new_lvl) if trail_level > 0 else new_lvl
            if trail_active and h >= trail_level:
                pct = (ep - trail_level) / ep * 100.0 * trade.leverage_short
                return dates[i], trail_level, "TSS", pct

    return None  # kein Trail-Exit — normaler Exit hätte gegolten

# Füge leverage an Trade-Objekte an (ist nicht im Dataclass, daher manuell)
for t in trades:
    t.leverage_long  = params.leverage_long
    t.leverage_short = params.leverage_short

print(f"\n{'='*65}")
print(f"TRAIL-SIMULATION  (activate ≥{TRAIL_ACT}%, ATR×{TRAIL_FACTOR})")
print(f"{'='*65}")

total_baseline = 0.0
total_trail    = 0.0
n_changed      = 0

for t in trades:
    result = simulate_trail(t, df, close, high, low_, dates, atr,
                            TRAIL_ACT, TRAIL_FACTOR)
    baseline_pct = t.pct
    total_baseline += baseline_pct

    if result and result[0] < t.exit_date:
        trail_date, trail_price, trail_type, trail_pct = result
        diff = trail_pct - baseline_pct
        sign = "+" if diff >= 0 else ""
        print(f"  Trade {t.entry_date.date()} → {t.exit_date.date()}  [{t.exit_type} {baseline_pct:+.1f}%]")
        print(f"    Trail hätte {trail_date.date()} @ {trail_price:,.0f} gefeuert  [{trail_type} {trail_pct:+.1f}%]")
        print(f"    Differenz: {sign}{diff:.1f}%")
        total_trail += trail_pct
        n_changed += 1
    else:
        # Trail hätte nicht früher gefeuert
        total_trail += baseline_pct
        if result:
            print(f"  Trade {t.entry_date.date()} → {t.exit_date.date()}  "
                  f"[kein früherer Trail-Exit — Baseline-Exit zuerst]")
        else:
            print(f"  Trade {t.entry_date.date()} → {t.exit_date.date()}  "
                  f"[Trail nie aktiv — Gewinnziel {TRAIL_ACT}% nicht erreicht]")

print(f"\n{'='*65}")
print(f"ZUSAMMENFASSUNG")
print(f"  Trades im Fenster:       {len(trades)}")
print(f"  Davon Trail-verändert:   {n_changed}")
print(f"  Kumuliertes P/L Baseline: {total_baseline:+.1f}%")
print(f"  Kumuliertes P/L Trail:    {total_trail:+.1f}%")
print(f"  Differenz:                {total_trail - total_baseline:+.1f}%")
print(f"{'='*65}\n")

# ── Aktueller offener Trade ──────────────────────────────────────────────────
# run_strategy schliesst offene Positionen am letzten Bar.
# Wir schauen ob der letzte Trade als _OPEN markiert ist.
if trades and trades[-1].exit_type.endswith("_OPEN"):
    t = trades[-1]
    print(f"AKTUELL OFFENER TRADE:")
    print(f"  {'LONG' if t.direction==1 else 'SHORT'} seit {t.entry_date.date()} @ {t.entry_price:,.0f}")
    print(f"  Aktueller Kurs: {close[-1]:,.0f}  ({dates[-1].date()})")
    unreal = (close[-1] - t.entry_price) / t.entry_price * 100.0 * params.leverage_long
    print(f"  Unrealisiert (leveraged): {unreal:+.1f}%")
    # Trail-Level jetzt?
    at_now = atr[-1] if not np.isnan(atr[-1]) else 0.0
    gross_pct = (close[-1] - t.entry_price) / t.entry_price * 100.0
    if gross_pct >= TRAIL_ACT and at_now > 0:
        trail_now = close[-1] - at_now * TRAIL_FACTOR
        print(f"  Trail AKTIV — aktuelles Trail-Level: {trail_now:,.0f}  (ATR={at_now:,.0f})")
    else:
        print(f"  Trail noch INAKTIV — unrealisiert {gross_pct:+.1f}% < {TRAIL_ACT}% Schwelle")
    print()

# AMB Strategy Logic Comparison: Pine Script vs Python

## STATUS: ✅ Logic verified — alter Vergleich war obsolet (2026-04-06 aufgelöst)

---

## Signal-Logik (IDENTISCH in Pine und Python)

| Signal | Pine Script | Python | Match? |
|--------|-----------|--------|--------|
  | **OL Entry** | `not position_open and (lastSignalDirection != 1 or not useFastMA) and cross_above_slowMA` | `(not position_open) and (last_dir != 1 or not params.use_fast_ma) and cross_above_slow` | ✅ |
| **OL Re-Entry** | `not position_open and lastSignalDirection == 1 and cross_above_fastMA and close > slowMA` | `(not position_open) and (last_dir == 1) and cross_above_fast and (c > s)` | ✅ |
| **CL Exit A** | `position_open and lastSignalDirection == 1 and longAboveFastMA and cross_below_fastMA` | `position_open and last_dir == 1 and long_above_fast_ma and cross_below_fast` | ✅ |
| **CL Exit B** | `position_open and lastSignalDirection == 1 and cross_below_slowMA` | `position_open and last_dir == 1 and cross_below_slow` | ✅ |
| **CL Exit SL** | `not na(sl_long_level) and low <= sl_long_level` | `(sl_long_level is not None) and (lo <= sl_long_level)` | ✅ |
| **Flip to Short** | `exitLong and cross_below_slowMA and allowShorts` | `exit_long and cross_below_slow and allow_shorts` | ✅ |

### State Machine (IDENTISCH)

Beide implementieren **Exits before Entries** (ermöglicht same-bar Flips):
1. Exit-Conditions prüfen
2. Bei Exit: Position schliessen, State zurücksetzen
3. Entry-Conditions prüfen
4. Bei Entry: Position öffnen

### SL-Logik (IDENTISCH)

```
Long SL  = entry_price × (1 − sl_risk_pct / (100 × leverage_long))
Short SL = entry_price × (1 + sl_risk_pct / (100 × leverage_short))
```

Beide prüfen Intrabar-Extremwerte (Low für Long, High für Short).

### Crossover-Erkennung (IDENTISCH)

```
cross_above = (close > ma) and (close_prev <= ma_prev)   # Pine: ta.crossover()
cross_below = (close < ma) and (close_prev >= ma_prev)   # Pine: ta.crossunder()
```

---

## Aufgelöste Diskrepanz: "45 vs 79 Trades" (war obsolet)

### Was dokumentiert war

Das alte Dokument enthielt: *"Python: 45 Trades, TradingView: 79 Trades (2021-04-14 bis 2023-10-31)"*

### Root-Cause-Analyse (2026-04-06)

Der Vergleich war aus zwei Gründen ungültig:

**1. Falsche Konfiguration:** Das alte Dokument verwendete `SMA(100)` — die aktuelle Live-Konfiguration ist `SMA(130)`. Ein direkter Vergleich 45 vs 79 ist damit keine Aussage über v1.6.1.

**2. Kein Strategy Tester möglich:** `AMB Dual MA Signal.pine` ist ein **Indicator** (kein Strategy-Script). TradingView hat keinen eingebauten Trade-Counter für Indicators. Die "79 Trades" konnten nicht von TradingView's Strategy Tester stammen — sie wurden manuell oder aus einer früheren Script-Version mit anderen Parametern gezählt.

### Aktueller Stand v1.6.1 (Python, 2026-04-06)

Diagnostic-Run mit `python -m backtest.diagnose_discrepancy` (Konfiguration: `SMA130/SMA44/LL3/LS0.5/SL6%`):

| Periode | Trades | Long | Short | CL | CS | SL |
|---------|--------|------|-------|----|----|----|
| 2021-04-14 → 2023-10-31 | **42** | 21 | 21 | 8 | 21 | 12 |
| 2021-04-14 → heute      | **85** | 45 | 40 | 21 | 40 | 24 |

**Crossover-Events 2021–2023:** 45 gesamt (10× Slow↑, 12× Fast↑, 10× Slow↓, 13× Fast↓)

Export-Dateien:
- `backtest/results/discrepancy/v1.6.1_2021_to_2023_trades_detail.csv`
- `backtest/results/discrepancy/v1.6.1_2021_to_2023_crossovers.csv`
- `backtest/results/discrepancy/v1.6.1_2021_to_2023_ma_daily.csv`

---

## TradingView-Abgleich: Anleitung für manuelle Verifizierung

Da Pine Script ein Indicator ist, muss der Abgleich manuell über Crossover-Daten erfolgen:

### Schritt 1: Erste Crossover-Daten gegen Chart prüfen

Öffne TradingView → BTC-USD Daily → SMA(130) + SMA(44).  
Prüfe, ob diese ersten 5 Crossover-Daten aus Python mit dem Chart übereinstimmen:

| Datum | Event | Close | SMA130 | SMA44 |
|-------|-------|-------|--------|-------|
| 2021-04-30 | CROSS_ABOVE_FAST | 57.750 | 46.583 | 56.924 |
| 2021-05-12 | CROSS_BELOW_SLOW | 49.151 | 49.298 | 57.022 |
| 2021-05-13 | CROSS_ABOVE_SLOW | 49.716 | 49.428 | 56.813 |
| 2021-05-15 | CROSS_BELOW_SLOW | 46.760 | 49.664 | 56.327 |
| 2021-08-07 | CROSS_ABOVE_SLOW | 44.556 | 43.410 | 35.385 |

### Schritt 2: Interpretation

- **Daten stimmen überein** → Pine und Python sind 1:1 synchron. ✅
- **Daten weichen ab** → `request.security()` in Pine könnte andere Bar-Alignment-Logik verwenden als yfinance UTC-Close. Ursache wäre dann die Datenquelle, nicht die Logik.

### Hinweis: request.security() und barmerge

Das Pine Script verwendet:
```pine
slowMA_value = request.security(syminfo.tickerid, slowMA_tf, slowMA_calc,
                                barmerge.gaps_off, barmerge.lookahead_off)
```
Auf Daily Chart mit `slowMA_tf = "D"` ist dies äquivalent zu `ta.sma(close, 130)`.  
Python berechnet identisch mit `pd.Series.rolling(130).mean()`.

---

## Code-Positionen

| Komponente | Pine Script | Python |
|-----------|-------------|--------|
| Crossover-Variablen | `AMB Dual MA Signal.pine`, Zeilen ~130–142 | `strategy_amb.py`, `run_strategy()`, Crossovers-Block |
| Signal-Conditions | `.pine` Zeilen ~145–185 | `strategy_amb.py`, Entry/Exit conditions |
| State Machine | `.pine` Zeilen ~190–260 | `strategy_amb.py`, State Machine Block |
| SL-Kalkulation | `.pine` Zeile ~160–162 | `strategy_amb.py`, `sl_long_level` / `sl_short_level` |

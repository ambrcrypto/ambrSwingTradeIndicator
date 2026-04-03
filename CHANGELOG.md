# CHANGELOG – AMB Dual MA Signal

---

## [v1.0] – 2026-04-02

### Indikator-Name
`AMB Dual MA Signal v1`

### Neue Features
- Dual-MA-Logik: Slow MA (Trendfilter/Entry) + Fast MA (Exit/Re-Entry)
- OL Entry via Slow MA Crossover (von unten)
- OL Re-Entry via Fast MA Crossover (von unten, über Slow MA)
- CL Exit A: war über Fast MA → schliesst darunter
- CL Exit B: nie über Fast MA seit Entry → schliesst unter Slow MA
- OS / CS spiegelverkehrt
- State-Tracking: `longAboveFastMA` / `shortBelowFastMA` pro Trade
- Visuelle Unterscheidung Entry (OL/OS gross) vs. Re-Entry (RL/RS klein)
- Backtesting integriert (compound P/L, Leverage, Datumsfenster)
- Alerts für alle 4 Signal-Typen

### Entfernt (gegenüber altem Code)
- ATR-basierte Entry/Exit-Logik (in V2 geplant)
- Stop Loss (in V2 geplant)
- Asymmetrische Re-Entry-Logik (Bug aus alter Version)

### Bekannte Einschränkungen
- Kein ATR-Filter (V2)
- Kein Stop Loss (V2)
- Bei Multi-Timeframe (z.B. 4H Chart + Daily MA): Crossover-Erkennung kann abweichen

### Getestete Konfiguration
- BTCUSDT 1D
- Slow MA: 130 SMA Daily
- Fast MA: 44 SMA Daily

---

## [v1.5] – 2026-04-03 ✅ Freigegeben

### Features
- Stop Loss (CHG-004): Intrabar SL für Long und Short
  - Ein Input `Max Risk % per Trade` (Default 2%, minval 0.1%)
  - SL-Level automatisch aus Leverage berechnet:
    - Long SL = `EP × (1 − risk / (100 × leverageLong))`
    - Short SL = `EP × (1 + risk / (100 × leverageShort))`
  - SL prüft Low (Long) / High (Short) intrabar – kein Warten auf Kerzenschluss
  - Kein Flip bei SL-Exit (`flipToShort`/`flipToLong` ausgeschlossen)
  - Visualisierung: rote dotted Linie + Label am rechten Rand (live-tracking)
  - EP-Linie/Label blau (dotted, rechter Rand), SL-Linie/Label rot
  - Backtest P/L bei SL-Hit: exakt `−sl_risk_pct` (Leverage bereits eingerechnet)
  - SL-Exit zeigt `SL`-Marker (xcross, rot) statt `CL`/`CS`
  - SL-Linie/Label werden nachträglich erstellt falls SL nach Trade-Eröffnung aktiviert wird

---

## [v1.4] – 2026-04-03 ✅ Freigegeben

### Features
- Erweitertes Backtest-Statistik-Table (4×4-Grid):
  - MaxDD (Peak-to-Trough Drawdown über alle Trades)
  - Profit Factor (Summe Gewinne / Summe Verluste)
  - AvgW / AvgL (Durchschnittlicher Gewinn / Verlust in %)
  - Expectancy (Erwartungswert pro Trade in %)
  - P/L% und Exp farbig (grün/rot)
- Unrealized P/L bei offener Position (Use End Date = off):
  - Wird in `end_capital` eingerechnet (compound)
  - Table-Zelle "End" zeigt `LONG +X%` / `SHORT +X%` mit Farbkodierung
- Live-Label auf aktueller Kerze:
  - Zeigt unrealisierten P/L der offenen Position als `+X%` / `-X%`
  - Farbe und Stil identisch mit Trade-Close-Labels (grün/rot, weisse Schrift)
  - Wird jeden Tick aktualisiert und bei Trade-Close entfernt

---

## [v1.3] – 2026-04-03 ✅ Freigegeben

### Fixes
- Bug CHG-002: `exitLong_B` / `exitShort_B` – SlowMA-Exit feuerte nicht wenn FastMA bereits berührt war. `not longAboveFastMA` / `not shortBelowFastMA` Bedingung entfernt. SlowMA-Cross triggert nun immer einen Exit, unabhängig vom FastMA-Zustand.

---

## [v1.2] – 2026-04-03 ✅ Freigegeben

### Features
- Flip-Logik: Exit + Entry auf gleicher Kerze wenn Slow MA gekreuzt wird
  - Long offen + cross_below_slowMA → CL + OS gleiche Kerze
  - Short offen + cross_above_slowMA → CS + OL gleiche Kerze
  - Fast MA Exit ohne Slow MA Cross → nur CL/CS, kein Flip
- State Machine umstrukturiert: Exits laufen vor Entries (ermöglicht Flip)
- `flipToLong` / `flipToShort` als separate Variablen

### Fixes
- Bug: OL/OS wurde nach Exit nicht ausgelöst wenn Slow MA auf gleicher Kerze gekreuzt

---

## [v1.1] – 2026-04-02

### Fixes
- CW10002: `ta.crossover()` / `ta.crossunder()` aus Conditions extrahiert → globale Variablen `cross_above_slowMA`, `cross_above_fastMA`, `cross_below_slowMA`, `cross_below_fastMA`

### Dev-Regeln hinzugefügt
- Syntax-Check vor jedem Release
- Pine Script CW10002-Regel dokumentiert

---

## [v0.1] – (Vorgänger: ambTradeSignalIndicator)

Erster Prototyp mit ATR-basierter Entry-Logik.
- Slow MA + ATR-Threshold für Entry
- Fast MA als zusätzliche Bedingung für Re-Entry (asymmetrisch)
- Backtest BTCUSDT 1D ab 2021-04-14: ~3000% Performance
- Bekannte Issues: Re-Entry-Logik inkonsistent, Settings-File nicht synchron

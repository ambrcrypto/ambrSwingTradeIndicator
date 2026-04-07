# CHANGELOG – AMB Dual MA Signal

---

## [v1.7.0] – 2026-04-07 ✅ Live Config (aktuell)

### Feature: Health Monitor Dashboard
- Neue Input-Gruppe **Health Monitor** mit 4 konfigurierbaren Schwellwerten:
  - `hm_min_exp` = 3.0% (Min Expectancy)
  - `hm_min_win` = 15.0% (Min Win Rate)
  - `hm_max_dd` = 55.0% (Max MaxDD)
  - `hm_max_sl_rate` = 50.0% (Max SL Rate)
- **SL-Rate** neu berechnet: Anteil Trades die via Stop Loss geschlossen wurden
- **Dashboard-Zeile 5** (Health Status): `✓ System OK` (grün) / `⚠ REVISION CHECK` (rot)
- Betroffene Metriken färben sich rot bei Schwellwertüberschreitung (Win%, MaxDD, SL%)
- Expectancy: dreistufig grün/orange/rot (ok / warn / negativ)
- Baseline v1.6.1: Exp 8.28%, Win 25%, MaxDD 31.89%, SL-Rate ~27%

---

## [v1.6.1] – 2026-04-04

### Änderung
- `sl_risk_pct`: 9.0% → **6.0%** (Revert gegenüber v1.6.0)
- `ticker_config.py` BTC-USD: sl_risk_pct 9.0 → 6.0

### Begründung
- Robustness-Vergleich 9% vs 6%: SL6% zeigt eindeutig bessere P/L (+2370% vs +1980%) bei praktisch identischem MaxDD
- LL3×/SL6% = 2% Long-Preistoleranz (strukturelles Risiko bei BTC-Tages-Wick, akzeptierter Tradeoff)
- LS0.5×/SL6% = 12% Short-Preistoleranz (praktisch nie ausgelöst)

### Live Config
`LL3×/LS0.5×/SL6%/SMA130/44` – alle Dateien synchron

---

## [v1.6.0] – 2026-04-04

### Features

#### Neue Live-Konfiguration BTC-USD
- `leverageLong`: 4.0 → **3.0** (7-Perioden-Robustness: LL3× gewinnt 5/7)
- `leverageShort`: 1.0 → **0.5** (LS0.5× eliminiert Short-SL-Risiko, Compounding-Effekt erhalten)
- `sl_risk_pct`: 9.0% (später in v1.6.1 auf 6.0% revertiert)
- `slow_ma_type`: EMA → **SMA** (robuster über alle Perioden)
- `fast_ma_len`: 60 → **44** (44 gewinnt in 7/7 Perioden vs 60)

#### Python Backtest: 7-Perioden BTC Regime-Robustness
- 7 nicht-überlappende BTC-Marktphasen P1–P7 definiert (Bull/Bear/Seitwärts)
- `run_optimize.py`: `btc_quick` / `btc_full` Modi ergänzt
- `data.py`: P1–P7 Periodendefinitionen hinzugefügt
- Robustness-Kriterium: MinCalmar und Anzahl Perioden mit positivem Calmar

#### Bugfix: trade_start
- `run_strategy()`: `trade_start`-Parameter hatte bei Robustness-Runs die MA-Warmup-Phase nicht korrekt berücksichtigt → korrigiert

#### ATR Pending Entry Filter (getestet, verworfen)
- `strategy_amb.py`: `atr_entry_enable` / `atr_entry_len` / `atr_long_mult` / `atr_short_mult` zu AMBParams hinzugefügt
- Mechanismus: Nach MA-Cross wird Pending-Entry generiert; feuert wenn `close >= MA_at_cross + ATR × mult`
- Backtest-Ergebnis: Baseline +2370% schlägt alle ATR-Varianten (beste: L0.5/S0.5 = +2372%, dd 29% vs 32%)
- Entscheidung: ATR Pending Entry bringt keinen Mehrwert → Baseline beibehalten

---

## [v1.5.4] – 2026-04-04 ✅ Freigegeben

### Features

#### Pine Script: Manual Entry Price (CHG-005)
- Neue Input-Gruppe `Manual Entry`:
  - `Use Manual EP` (bool, default off)
  - `Entry Price` (float, default 0.0)
- Wenn aktiv: eigener EP wird für visuelle EP/SL-Linie und `End:`-Feld verwendet
- Klare Trennung der Variablen:
  - `entry_price` = `eff_ep` (manual oder close) → nur für Chart-Visualisierung
  - `ep_for_sl_trigger` = immer `close` des Signal-Bars → für SL-Trigger-Berechnung (historisch korrekt)
  - `bt_entry_price` = immer `close` → für Backtest P/L-Statistik (unveränderlich)
  - `display_unrealized` = basiert auf `manual_ep_val` wenn aktiv → nur für `End:`-Feld + Live-Label
- Garantiert: P/L-Statistik (WR, PF, MaxDD, Exp) bleibt immer auf Strategie-Basis

#### Pine Script: BTC-optimierte Defaults
- `slowMA_type`: EMA → **SMA** (robuster über Perioden)
- `fastMA_len`: 44 → **60** (weniger Fehlsignale)
- `leverageLong`: 3.0 → **4.0** (Robustness-Optimum)
- `sl_risk_pct`: 8.0 → **9.0** (Robustness-Optimum)

#### Python Backtest: Robustness Score (Step 2)
- `optimize.py`: `run_robustness()` – bewertet Top-N Konfigurationen über 4 Sub-Perioden
- `report.py`: `print_robustness_results()` – formatierte Ausgabe mit Min/Avg Calmar
- `run_optimize.py`: `--robustness` / `--robustness-sort` Flags
- `ticker_config.py`: BTC-USD auf neue Werte aktualisiert (SMA/60/4×/9%)
- Winner BTC: SMA130 / SMA60 / LL4× / SL9%, MinCalmar = 2.12

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

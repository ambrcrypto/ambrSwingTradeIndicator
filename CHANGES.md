# CHANGES – AMB Dual MA Signal

---

## CHG-011 – Rollierende 6M-Review mit 1Y-Lookback als neuer Default-Prozess

| Feld | Inhalt |
|---|---|
| **ID** | CHG-011 |
| **Status** | ✅ Abgeschlossen |
| **Version** | v1.8.5 |
| **Datum** | 2026-04-14 |
| **Requested by** | User |

### Change Request
Das Backtesting-Startdatum soll auf 2025-04-01 gesetzt werden, damit der Testbereich immer exakt ein Jahr vor dem aktuellen Review-Checkpoint beginnt. Alle 6 Monate erfolgt eine neue Prüfung; der Default wird nur bei Bedarf ersetzt.

### Umsetzung
- Pine-Backtest-Start auf 2025-04-01 umgestellt.
- Default-Kandidat für den aktuellen Review-Zyklus gesetzt auf:
  - Slow MA = EMA 130
  - Fast MA = SMA 60
  - Long Leverage = 3.75x
  - Short Leverage = 0.5x
  - Stop Loss = 3.0%
- Health-Monitor und Anforderungen an das rollierende 1-Jahres-Fenster angepasst.

### Verifiziert
Bybit BTCUSD, Rollfenster 2025-04-01 bis 2026-04-13:
- aktueller Default: +147.50%, MaxDD 9.46%, 16 Trades
- Win Rate 43.75%, Expectancy 6.83%, SL-Rate 18.8%

### Abschluss
Die Strategie folgt jetzt dem gewünschten Wartungsprozess: alle 6 Monate Review mit 1Y-Lookback und nur dann Baseline-Reset, wenn ein stärkerer Kandidat bestätigt wird.

---

## CHG-010 – Neue Live-Baseline aus Walk-Forward-BTC-Backtest

| Feld | Inhalt |
|---|---|
| **ID** | CHG-010 |
| **Status** | ✅ Abgeschlossen |
| **Version** | v1.8.4 |
| **Datum** | 2026-04-14 |
| **Requested by** | User |

### Change Request
Die aktuell besten verifizierten Werte aus dem jüngsten BTC-Backtest sollen als neue Baseline übernommen werden. Dokumentation und Projektstand sollen bereinigt werden.

### Umsetzung
- Default-Parameter in [AMB Dual MA Signal.pine](AMB%20Dual%20MA%20Signal.pine) und in der Python-Ticker-Konfiguration auf die neue Live-Baseline gesetzt:
  - Slow MA = EMA 130
  - Fast MA = SMA 60
  - Long Leverage = 4.0x
  - Short Leverage = 0.5x
  - Stop Loss = 4.0%
- Health-Monitor-Kommentar und Warnschwellen auf den neuen Referenzstand kalibriert.
- Historischer Regressionstest von den Live-Defaults entkoppelt.
- Nicht mehr benötigte Explorationsdateien aus den Seilbahn-/Challenger-Versuchen entfernt.

### Verifiziert
Bybit BTCUSD, Zeitraum 2022-11-21 bis 2026-04-13:
- bisheriger Default: +2418.47%, MaxDD 28.67%, 64 Trades
- neue Baseline: +3762.59%, MaxDD 40.41%, 53 Trades
- Zusatz-KPIs neue Baseline: Win Rate 22.64%, Expectancy 11.82%, SL-Rate 45.3%

### Abschluss
Der Indikator und die Backtest-Defaults laufen jetzt wieder auf einem einheitlichen, aktuellen und dokumentierten Baseline-Stand.

---

## CHG-009 – BTCUSD-Baseline ab 2022 als verbindliche Referenz

| Feld | Inhalt |
|---|---|
| **ID** | CHG-009 |
| **Status** | ✅ Abgeschlossen |
| **Version** | v1.8.3 |
| **Datum** | 2026-04-14 |
| **Requested by** | User |

### Change Request
Als Baseline gilt BTCUSD nach dem fixen Startdatum in 2022. Die Standardkonfiguration soll auf die verifizierte stärkere Variante umgestellt werden.

### Umsetzung
- Default-Parameter in [AMB Dual MA Signal.pine](AMB%20Dual%20MA%20Signal.pine) auf den verifizierten Sieger gesetzt:
  - Slow MA = EMA 100
  - Fast MA = SMA 52
  - Long Leverage = 3.75x
  - Short Leverage = 0.5x
  - Stop Loss = 3.0%
- Health-Monitor-Kommentar auf BTCUSD ab 2022-11-21 umgestellt.
- Warnschwellen an die neue Referenz angepasst.

### Verifiziert
Bybit BTCUSD, Zeitraum 2022-11-21 bis aktuell:
- alte Baseline: +2135.42%, MaxDD 31.89%, 64 Trades
- neuer Default: +2418.47%, MaxDD 28.67%, 64 Trades

### Abschluss
Die Baseline-Definition ist jetzt eindeutig festgelegt und der Indikator nutzt standardmässig die bessere BTCUSD-Variante.

---

## CHG-008 – Python Backtest mit Bybit-Perp Datenquelle

| Feld | Inhalt |
|---|---|
| **ID** | CHG-008 |
| **Status** | ✅ Abgeschlossen |
| **Version** | v1.8.0 |
| **Datum** | 2026-04-11 |
| **Requested by** | User |

### Change Request
Backtest fuer Parameter-Justierung soll optional auf Bybit BTCUSDT Perpetual Daten laufen. Fuer lange Historie soll yfinance weiter verfuegbar bleiben.

### Umsetzung
- Data-Layer erweitert: `source`-Parameter (`yfinance`/`bybit`) in `get_all()`, `get_slice()`, `get_periods()`, `describe()`.
- Bybit-Download via `ccxt.bybit().fetch_ohlcv()` in `backtest/data.py` mit Pagination und CSV-Cache.
- CLI erweitert:
  - `python -m backtest.run --source yfinance|bybit`
  - `python -m backtest.run_optimize --source yfinance|bybit`
- Optimizer-Pipeline source-aware gemacht (Perioden, Datenzugriff, Cross-Checks, Output-Dateien).
- Dependency erweitert: `ccxt` in `backtest/requirements.txt`.

### Test Cases

| TC | Szenario | Erwartetes Resultat |
|---|---|---|
| TC-DB-01 | `get_periods("BTC-USD", source="yfinance")` | Periodenliste vorhanden, inkl. `2021_default` |
| TC-DB-02 | `get_periods("BTC-USD", source="bybit")` | Periodenliste vorhanden (kuerzer), inkl. `2021_default` sofern Daten vorhanden |
| TC-DB-03 | Bybit Smoke Test 1D OHLCV | Symbol `BTC/USDT:USDT` (swap, linear) wird geladen und liefert Kerzen |

### Verifiziert
- Smoke-Test erfolgreich: Bybit BTCUSDT Perp-Daten bis 2026-04-11 geladen.
- Strategy-Schnelllauf auf Bybit-Datensatz ohne Fehler ausgefuehrt.

### Abschluss
Backtest kann jetzt fuer Langzeit-Optimierung mit yfinance und fuer aktuelle Baseline mit Bybit ausgefuehrt werden.

---

## CHG-007 – Signal-Control Toggles auch in Anzeige/Test-Labels

| Feld | Inhalt |
|---|---|
| **ID** | CHG-007 |
| **Status** | ✅ Abgeschlossen |
| **Version** | v1.7.1 |
| **Datum** | 2026-04-11 |
| **Requested by** | User |

### Change Request
Beim Deaktivieren von Longs oder Shorts sollen nicht nur Trades unterbunden werden, sondern auch die zugehoerigen Signal-Marker und Test-Mode-Labels im Chart.

### Ursache
Trade-Logik war bereits korrekt an `allowLongs` / `allowShorts` gebunden. Die Visualisierung und Teile der Test-Mode-Ausgabe nutzten jedoch direkte Entry/Re-Entry-Flags ohne konsistente Toggle-Gates.

### Umsetzung
- Neue Anzeige-Flags eingefuehrt:
  - `disp_long_entry`, `disp_long_reentry`
  - `disp_short_entry`, `disp_short_reentry`
- `plotshape()` fuer OL/RL/OS/RS auf diese Flags umgestellt.
- Test-Mode-Labels A01/B01/A03/B04 mit `allowLongs` bzw. `allowShorts` gegated.

### Test Case

| TC | Szenario | Erwartetes Resultat |
|---|---|---|
| TC-TGL-01 | `Allow Long Trades? = false`, `Allow Short Trades? = true` | Keine OL/RL Marker, keine A01/B01 Labels; Short-Signale bleiben sichtbar |

### Test-Feedback (User)
Freigegeben durch User am 2026-04-11. Verhalten funktioniert wie erwartet.

### Abschluss
Fix produktiv in v1.7.1 dokumentiert.

---

## CHG-006 – Health Monitor: KPI-Revisionswarnung im Dashboard

| Feld | Inhalt |
|---|---|
| **ID** | CHG-006 |
| **Status** | ✅ Abgeschlossen |
| **Version** | v1.7.0 |
| **Datum** | 2026-04-07 |
| **Requested by** | User |

### Change Request
Baseline-KPIs direkt im Pine Script Dashboard verankern. Dashboard soll warnen wenn KPIs unter konfigurierbare Schwellwerte fallen, damit Parameterrevision rechtzeitig erkannt wird.

### Implementierung
- Neue Input-Gruppe „Health Monitor" mit `hm_enable`, `hm_min_exp`, `hm_min_win`, `hm_max_dd`, `hm_max_sl_rate`
- SL-Rate-Berechnung (`sl_count / trades`) neu hinzugefügt
- Dashboard um Zeile 5 erweitert: Status-Zelle + SL%-Anzeige + Schwellwert-Info
- Farblogik: Exp orange bei warn, rot bei negativ; Win/MaxDD/SL% rot bei Überschreitung
- Table von `4×4` auf `4×5` erweitert

### Baseline v1.6.1 (ab 2022-11-21, BTC/USD)
| KPI | Baseline | Warnschwelle |
|---|---|---|
| Expectancy | 8.28% | < 3.0% |
| Win Rate | 25% | < 15% |
| MaxDD | 31.89% | > 55% |
| SL Rate | ~27% | > 50% |

---

## CHG-001 – Flip-Logik: Exit + Entry auf gleicher Kerze

| Feld | Inhalt |
|---|---|
| **ID** | CHG-001 |
| **Status** | ✅ Abgeschlossen (Schritt 10) |
| **Version** | v1.2 |
| **Datum** | 2026-04-03 |
| **Requested by** | User |

### Change Request
Nach einem Exit durch Slow-MA-Kreuzung soll auf **derselben Kerze** eine Position in der Gegenrichtung eröffnet werden.

### Analyse (BA)
Klare Anforderung. Betrifft State Machine – Exits müssen vor Entries laufen. Kein Konflikt mit bestehender Re-Entry-Logik.

### Review (BA + Trading Experte)
Logisch korrekt: Slow MA ist Trendfilter. Wenn Slow MA gekreuzt wird, wechselt die Trendrichtung – sofortiger Gegenhandel ist konsistent mit der Strategie.

### Test Cases

| TC | Szenario | Erwartetes Resultat |
|---|---|---|
| TC-01 | Long offen, Kerze schliesst unter Slow MA (nie Fast MA berührt) | CL + OS auf gleicher Kerze |
| TC-02 | Long offen, Kerze schliesst unter Fast MA (Fast MA je berührt), NICHT unter Slow MA | Nur CL, kein OS |
| TC-03 | Long offen, Kerze schliesst unter Fast MA UND unter Slow MA | CL + OS auf gleicher Kerze |
| TC-04 | Short offen, Kerze schliesst über Slow MA (nie Fast MA berührt) | CS + OL auf gleicher Kerze |
| TC-05 | Short offen, Kerze schliesst über Fast MA (Fast MA je berührt), NICHT über Slow MA | Nur CS, kein OL |
| TC-06 | Short offen, Kerze schliesst über Fast MA UND über Slow MA | CS + OL auf gleicher Kerze |
| TC-07 | Kein offener Trade, Slow MA Kreuzung nach oben | Nur OL, kein CS |
| TC-08 | Kein offener Trade, Slow MA Kreuzung nach unten | Nur OS, kein CL |

### Machbarkeit (Entwickler)
Umsetzbar. State Machine umstrukturiert: Exits laufen vor Entries. `flipToLong` / `flipToShort` als separate Variablen. Kein Risiko von Zirkularität.

### Umsetzung
- `flipToShort = exitLong and cross_below_slowMA and allowShorts`
- `flipToLong = exitShort and cross_above_slowMA and allowLongs`
- State Machine: Exit-Block vor Entry-Block
- Visualisierung: Flip-Entries zeigen OL/OS Marker (gleich wie reguläre Entries)

### Pre-Check (BA + Entwickler)
- TC-01: `exitLong_B` feuert (kein FastMA, cross_below_slowMA) → `flipToShort=true` ✅
- TC-02: `exitLong_A` feuert (FastMA berührt, cross_below_fastMA), `cross_below_slowMA=false` → `flipToShort=false` ✅
- TC-03: `exitLong_A` feuert UND `cross_below_slowMA=true` → `flipToShort=true` ✅
- TC-04–06: Spiegelverkehrt zu TC-01–03 ✅
- TC-07: `position_open=false` → `flipToShort=false`, nur `longEntry` ✅
- TC-08: `position_open=false` → `flipToLong=false`, nur `shortEntry` ✅

### Test-Feedback (User)
Freigegeben durch User am 2026-04-03. Flip-Logik funktioniert korrekt auf Chart verifiziert.

### Abschluss
Change formal abgeschlossen. Flip-Logik ist produktiv in v1.2+. Kein weiterer Handlungsbedarf.

---

## CHG-003 – Erweitertes Backtest-Reporting + Live-Label

| Feld | Inhalt |
|---|---|
| **ID** | CHG-003 |
| **Status** | ✅ Abgeschlossen |
| **Version** | v1.4 |
| **Datum** | 2026-04-03 |
| **Requested by** | User |

### Change Request
Backtest-Tabelle um weitere Metriken erweitern (MaxDD, PF, AvgW/L, Expectancy). Offene Position soll bei aktivem Backtest (ohne Enddatum) als Unrealized P/L sichtbar sein – sowohl in der Tabelle als auch als Chart-Label.

### Umsetzung
- Tabelle auf 4×4 erweitert:
  - Row 2: MaxW / MaxL / MaxDD / PF
  - Row 3: AvgW / AvgL / Exp (farbig) / Leverage
- `unrealized_pct` berechnet für offene BT-Position (Long: close/entry, Short: entry/close × Leverage)
- `end_capital` wird bei offener Position mit unrealisierten % compounded
- Table-Zelle "End" zeigt `LONG +X%` / `SHORT +X%` farbig wenn Position offen
- `live_trade_lbl`: var label, wird jeden Bar gelöscht/neu gesetzt mit aktuellem unrealized %; Stil identisch mit Trade-Close-Labels

### Test-Feedback (User)
Freigegeben durch User am 2026-04-03. Label sichtbar und korrekt formatiert. Tabelle vollständig.

### Abschluss
Change formal abgeschlossen. In v1.4 produktiv.

---

## CHG-004 – Stop Loss Feature

| Feld | Inhalt |
|---|---|
| **ID** | CHG-004 |
| **Status** | ✅ Abgeschlossen |
| **Version** | v1.5 |
| **Datum** | 2026-04-03 |
| **Requested by** | User |

### Change Request
Stop Loss für Long und Short. Intrabar-Prüfung (Low/High). Kein Flip bei SL-Exit. Visualisierung als Linie + Label. Backtest-Integration.

### Analyse (BA) – 5 Klärungsfragen
1. SL-Level: Fixer %-Offset vom EP oder technisch (Swing Low/High)? → Prozentual
2. Ein SL für L+S oder getrennt? → Ein Input, aber Berechnung je nach Leverage
3. Intrabar (Low/High) oder Close-basiert? → Intrabar
4. Flip bei SL-Exit erlaubt? → Nein
5. Visualisierung? → Linie + Label am rechten Rand

### Finale Spezifikation
- Input: `sl_risk_pct` = max. Kapitalverlust pro Trade (%), Default 2.0%, minval 0.1%
- Long SL = `EP × (1 − sl_risk_pct / (100 × leverageLong))`
- Short SL = `EP × (1 + sl_risk_pct / (100 × leverageShort))`
- Trigger: `low <= sl_long_level` (Long) / `high >= sl_short_level` (Short)
- Flip erlaubt bei SL-Exit wenn Slow MA gleichzeitig gekreuzt: `flipToLong = exitShort and cross_above_slowMA ...` (kein `not exitShort_SL` mehr)
- Backtest P/L: `−sl_risk_pct` (exakt, da Abstand leverage-korrekt berechnet)
- CL/CS Marker bei SL-Exit unterdrückt (nur SL-Marker)

### Test Cases

| TC | Szenario | Erwartetes Resultat |
|---|---|---|
| TC-SL-01 | Long offen, SL enable, Low dieser Kerze ≤ sl_long_level | exitLong_SL=true, SL-Marker, kein Flip, kein CL-Marker |
| TC-SL-02 | Long offen, SL enable, Low > sl_long_level | exitLong_SL=false, Trade läuft weiter |
| TC-SL-03 | Short offen, SL enable, High ≥ sl_short_level | exitShort_SL=true, SL-Marker, kein Flip, kein CS-Marker |
| TC-SL-04 | Short offen, SL enable, High < sl_short_level | exitShort_SL=false, Trade läuft weiter |
| TC-SL-05 | SL disable | exitLong_SL=false, exitShort_SL=false immer |
| TC-SL-06 | SL enable, nach Trade-Eröffnung aktiviert | SL-Linie/Label erscheinen auf nächster Bar |
| TC-SL-07 | SL enable, sl_risk_pct=2%, leverageLong=3x, EP=68793 | sl_long_level = 68793 × (1 − 2/(100×3)) = 68334 |
| TC-SL-08 | SL enable, sl_risk_pct=2%, leverageShort=1.25x, EP=68793 | sl_short_level = 68793 × (1 + 2/(100×1.25)) = 69893 |
| TC-SL-09 | SL-Exit im Backtest | trade_pct = −sl_risk_pct (unabhängig von close) |
| TC-SL-10 | SL-Exit gleichzeitig mit Slow MA Cross | Kein Flip (SL hat Vorrang) |

### Test-Feedback (User)
Freigegeben durch User am 2026-04-03. SL-Linie und Label sichtbar, SL-Trigger korrekt, Overlap-Problem behoben (CL/CS unterdrückt bei SL-Exit).

### Abschluss
Change formal abgeschlossen. Stop Loss produktiv in v1.5.


| Feld | Inhalt |
|---|---|
| **ID** | CHG-002 |
| **Status** | ✅ Abgeschlossen (Schritt 10) |
| **Version** | v1.3 |
| **Datum** | 2026-04-03 |
| **Requested by** | User (Test-Feedback) |

### Bug-Beschreibung
Short offen, FastMA je berührt (shortBelowFastMA=true), Kurs kreuzt SlowMA nach oben ohne FastMA zu kreuzen → kein Exit. Gleiches spiegelverkehrt für Long.

**Beispiel:** BTCUSDT 1. Sept 2025, close 109191 > slowMA 109167, fastMA 115537 → kein CS, kein OL.

### Ursache
`exitShort_B` hatte Bedingung `not shortBelowFastMA` → schloss SlowMA-Exit aus wenn FastMA je berührt. Gleicher Fehler bei `exitLong_B` mit `not longAboveFastMA`.

### Fix
- `exitLong_B`: `not longAboveFastMA` entfernt → SlowMA-Exit immer
- `exitShort_B`: `not shortBelowFastMA` entfernt → SlowMA-Exit immer

### Test Cases

| TC | Szenario | Erwartetes Resultat |
|---|---|---|
| TC-C07 | Long offen, FastMA je berührt, Kurs kreuzt SlowMA nach unten (nicht FastMA) | CL |
| TC-C08 | Short offen, FastMA je berührt, Kurs kreuzt SlowMA nach oben (nicht FastMA) | CS + OL (Flip) |

### Pre-Check
- TC-C07: `exitLong_B` = position_open + dir==1 + cross_below_slowMA ✅ (longAboveFastMA spielt keine Rolle mehr)
- TC-C08: `exitShort_B` = position_open + dir==-1 + cross_above_slowMA ✅ → `flipToLong` = exitShort + cross_above_slowMA ✅

### Test-Feedback (User)
Freigegeben durch User am 2026-04-03. CS+OL erscheint korrekt bei BTCUSDT Sept 2025.

### Abschluss
Change formal abgeschlossen. Bug behoben und in v1.3 produktiv. Kein weiterer Handlungsbedarf.

---

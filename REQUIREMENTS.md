# AMB Dual MA Signal – Anforderungen

## Grundprinzip

| MA        | Rolle                                                                 |
|-----------|-----------------------------------------------------------------------|
| **Slow MA** | Trendfilter – definiert erlaubte Handelsrichtung. **Erster Einstieg** immer via Slow MA |
| **Fast MA** | Timing-Signal – steuert **Ausstieg und Wiedereinstieg** innerhalb des Trends |

### Trendrichtung
- Kurs **über** Slow MA → nur **Long**-Trades erlaubt
- Kurs **unter** Slow MA → nur **Short**-Trades erlaubt

---

## Long-Regeln

| Situation      | Bedingung                                                                                       |
|----------------|-------------------------------------------------------------------------------------------------|
| **OL Entry**   | Kurs schliesst über Slow MA, nachdem er in der vorherigen Kerze darunter war                   |
| **OL Re-Entry**| Kurs schliesst über Fast MA, nachdem er darunter war – kein offener Trade, implizit über Slow MA |
| **CL Exit A**  | Kurs hat seit Entry die Fast MA je überschritten → schliesst darunter                          |
| **CL Exit B**  | Kurs hat seit letztem Slow-MA-Crossover die Fast MA **nie** überschritten → schliesst unter Slow MA |

## Short-Regeln (spiegelverkehrt)

| Situation      | Bedingung                                                                                        |
|----------------|--------------------------------------------------------------------------------------------------|
| **OS Entry**   | Kurs schliesst unter Slow MA, nachdem er in der vorherigen Kerze darüber war                    |
| **OS Re-Entry**| Kurs schliesst unter Fast MA, nachdem er darüber war – kein offener Trade, implizit unter Slow MA |
| **CS Exit A**  | Kurs hat seit Entry die Fast MA je unterschritten → schliesst darüber                           |
| **CS Exit B**  | Kurs hat seit letztem Slow-MA-Crossover die Fast MA **nie** unterschritten → schliesst über Slow MA |

---

## Flip-Regel (Richtungswechsel auf gleicher Kerze)

Wenn ein Exit durch einen **Slow MA Cross** ausgelöst wird (oder gleichzeitig damit zusammenfällt), öffnet auf **derselben Kerze** eine Position in der Gegenrichtung.

| Situation | Exit | Flip Entry |
|---|---|---|
| Long offen → kreuzt Slow MA nach unten | CL | OS gleiche Kerze |
| Long offen → kreuzt Fast MA nach unten, NICHT Slow MA | CL | – |
| Long offen → kreuzt Fast MA nach unten UND Slow MA | CL | OS gleiche Kerze |
| Short offen → kreuzt Slow MA nach oben | CS | OL gleiche Kerze |
| Short offen → kreuzt Fast MA nach oben, NICHT Slow MA | CS | – |
| Short offen → kreuzt Fast MA nach oben UND Slow MA | CS | OL gleiche Kerze |

**Kern-Logik:** Flip nur wenn `cross_below_slowMA` (bei Long) bzw. `cross_above_slowMA` (bei Short) auf derselben Kerze true ist.

---

## ATR-Erweiterung (V2 – noch nicht implementiert)

ATR als optionaler Puffer, der **pro Situation** (Entry / Re-Entry / Exit) separat aktiviert werden kann, um Fehlsignale bei hoher Volatilität zu reduzieren.

| Situation  | Ohne ATR                    | Mit ATR                                  |
|------------|-----------------------------|------------------------------------------|
| OL Entry   | Crossover Slow MA           | Kurs schliesst über Slow MA + ATR×Faktor |
| OL Re-Entry| Crossover Fast MA           | Kurs schliesst über Fast MA + ATR×Faktor |
| CL Exit A  | Crossunder Fast MA          | Kurs schliesst unter Fast MA − ATR×Faktor|
| CL Exit B  | Crossunder Slow MA          | Kurs schliesst unter Slow MA − ATR×Faktor|
| OS / CS    | (spiegelverkehrt)           | (spiegelverkehrt)                        |

### Geplante Optionen für V2
- ATR-Faktor separat für Entry, Re-Entry und Exit konfigurierbar
- Optionaler Filter: Mindestanzahl Kerzen auf einer Seite vor Signal

---

## Stop Loss (implementiert ab v1.5)

- **Aktivierung:** `Enable Stop Loss` (bool, default off)
- **Input:** `Max Risk % per Trade` (float, default 2.0%, minval 0.1%)
- **SL-Level Berechnung** (abhängig von Leverage):
  - Long SL = `EP × (1 − sl_risk_pct / (100 × leverageLong))`
  - Short SL = `EP × (1 + sl_risk_pct / (100 × leverageShort))`
- **Trigger:** Intrabar (`low <= sl_long_level` / `high >= sl_short_level`)
- **Kein Flip** bei SL-Exit
- **Visualisierung:** rote dotted Linie + Label am rechten Chartrand
- **Backtest P/L:** exakt `−sl_risk_pct` (Leverage bereits in SL-Abstand eingerechnet)

---

## Technische Anforderungen

- Platform: TradingView Pine Script v6
- Signal-Timing: Kerzenschluss (`barstate.isconfirmed`)
- Multi-Timeframe-Support: Slow MA und Fast MA unabhängig konfigurierbar
- Backtesting: Integriert, mit Kapital, Leverage, Datumsfenster
- Alerts: ENTER LONG / ENTER SHORT / EXIT LONG / EXIT SHORT
- Ziel: Anwendbar auf BTC, Aktien, ETFs (anpassbare Parameter)

---

## Change-Prozess

| Schritt | Wer | Was |
|---|---|---|
| **1. Change Request** | User | Beschreibung des Changes |
| **2. Analyse** | BA | Eindeutige ID vergeben, Doku updaten, Rückfragen |
| **3. Review** | BA + Trading Experte | Kritisch hinterfragen, Alternativen prüfen |
| **4. Test Cases** | BA + Trading Experte | Testfälle definieren vor Umsetzung |
| **5. Machbarkeit** | Entwickler | Technische Prüfung, Aufwandschätzung |
| **6. Go / No Go** | User | Entscheid |
| **7. Umsetzung** | Entwickler | Code, Syntax-Check, Code-Review |
| **8. Pre-Check** | BA + Entwickler | Statischer Code-Check gegen Test Cases |
| **8b. Status Update** | BA | Test Cases + Code an User übergeben, Status kommunizieren |
| **9. TradingView Test** | User | Kopieren, testen, Feedback |
| **10. Abschluss** | BA | Learnings, CHANGELOG, git tag |

Alle Changes werden in `CHANGES.md` mit eindeutiger ID (CHG-XXX) verwaltet.

---

## Dev-Regeln (Entwicklungsprozess)

- **Syntax-Check vor jedem Release:** Code muss fehlerfrei in TradingView kompilieren – keine Warnings, keine Errors
- **Pine Script CW10002:** `ta.crossover()` / `ta.crossunder()` dürfen **nie** innerhalb von Conditions oder `if`-Blöcken aufgerufen werden. Immer als globale Variable auf oberster Ebene definieren:
  ```pine
  cross_above_slowMA = ta.crossover(close, slowMA_value)  // global
  longEntry = ... and cross_above_slowMA                  // dann verwenden
  ```
- **Mehrzeilige Conditions:** In Pine Script v6 erlaubt, aber Operatoren müssen am Zeilenende stehen
- **Versionierung:** Nach jeder Änderung CHANGELOG.md aktualisieren und git commit + tag setzen

---

## Default-Parameter (BTCUSDT 1D optimiert)

| Parameter        | Wert  |
|------------------|-------|
| Slow MA          | 130 SMA, Daily |
| Fast MA          | 44 SMA, Daily  |
| ATR Length       | 14 (RMA) – V2  |
| Leverage Long    | 3.0x           |
| Leverage Short   | 1.25x          |
| Backtest Start   | 2021-04-14     |

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

## ATR-Erweiterung (getestet in v1.6.0, verworfen)

ATR Pending Entry Filter wurde als optionale Erweiterung getestet:
- Mechanismus: Nach MA-Cross Pending-Entry setzen; feuert wenn `close >= MA_at_cross + ATR×mult`
- Optimale Multiplikatoren aus Urversion: Long 1.7×, Short 1.5×
- Backtest-Ergebnis (BTC-USD 2021→2026): Baseline +2370% schlägt alle ATR-Varianten
- **Entscheidung: Feature verworfen. Baseline bleibt optimal.**

ATR als Exit-Puffer (Exit A/B mit ATR-Abstand) weiterhin als V2-Option offen.

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

## Revisionsprozess (Health Monitor)

Der Health Monitor im Dashboard zeigt permanent ob die Strategie noch innerhalb der Basis-KPIs operiert. Diese KPIs werden nach jeder Parameteranpassung neu kalibriert.

### Revisions-Trigger

| Trigger | Beschreibung |
|---|---|
| **Kalender** | Pflichtrevision alle 6 Monate: **1. Oktober** und **1. April** jeden Jahres |
| **Event** | Sofortrevision sobald Dashboard `⚠ REVISION CHECK` zeigt |

Nächste Pflichtrevision: **2026-10-01**

**Wichtig:** Das Review-Fenster ist jetzt **rollierend**. Zum jeweiligen Checkpoint wird das Backtest-Startdatum genau **1 Jahr zurück** gesetzt. Beispiel: Review am 2026-04-01 ⇒ Startdatum 2025-04-01.

### Revisionsdurchführung

| Schritt | Wer | Was |
|---|---|---|
| **1. Daten erheben** | User | TradingView Dashboard-Screenshot, Python Backtest mit aktuellem Startdatum |
| **2. KPI-Analyse** | BA + Trading Experte | Vergleich Ist-KPIs vs. Baseline-Schwellwerte, Ursachenanalyse |
| **3. Entscheid** | User | Parameter beibehalten / anpassen |
| **4a. Beibehalten** | BA | Revisionsdatum aktualisieren, in CHANGELOG dokumentieren |
| **4b. Anpassen** | Entwickler | Parameter ändern → normaler Change-Prozess (CHG-XXX) |
| **5. Neue Baseline** | BA | Startdatum := Datum der Parameteranpassung, Health-Monitor-Schwellwerte neu kalibrieren |

### Baseline-Aktualisierung nach Parameteranpassung

1. **Checkpoint festlegen:** jeweils 1. April und 1. Oktober
2. **Pine Script:** `bt_start_year/month/day` auf genau **1 Jahr vor dem Checkpoint** setzen
3. **Backtest:** Optimierung mit den letzten 12 Monaten durchführen
4. **Default nur ändern**, wenn der neue Kandidat im Review klar besser bestätigt ist
5. **Health-Monitor:** `hm_min_exp`, `hm_min_win`, `hm_max_dd`, `hm_max_sl_rate` auf die neue Rolling-Baseline kalibrieren
6. **Kommentar** im Inputs-Block aktualisieren
7. CHANGELOG + CHANGES aktualisieren, git commit

### Aktuelle Rolling-Baseline (v1.8.5, Review-Fenster 2025-04-01 → live, BTC/USD)

| KPI | Baseline-Wert | Warnschwelle (Health Monitor) |
|---|---|---|
| Expectancy | 6.83% | < 3.5% |
| Win Rate | 43.75% | < 20% |
| MaxDD | 9.46% | > 20% |
| SL Rate | 18.8% | > 40% |

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

## Default-Parameter (BTC/USD 1D, Live v1.8.5)

_Aktualisiert v1.8.5 – rollierender Review-Stand mit 1Y-Lookback_

| Parameter        | Wert                    |
|------------------|-------------------------|
| Slow MA          | 130 **EMA**, Daily      |
| Fast MA          | **60 SMA**, Daily       |
| Leverage Long    | **3.75x**               |
| Leverage Short   | **0.5x**                |
| Stop Loss        | **3.0%** (Max Risk)     |
| Backtest Start   | **2025-04-01** (1Y vor Checkpoint 2026-04-01) |

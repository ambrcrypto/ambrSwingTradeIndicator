# CHANGES – AMB Dual MA Signal

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

## CHG-002 – Bug: SlowMA-Exit fehlt wenn FastMA bereits berührt

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

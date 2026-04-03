# CHANGES – AMB Dual MA Signal

---

## CHG-001 – Flip-Logik: Exit + Entry auf gleicher Kerze

| Feld | Inhalt |
|---|---|
| **ID** | CHG-001 |
| **Status** | 🟡 In Test (Schritt 9) |
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
_Ausstehend_

### Abschluss
_Ausstehend_

---

# Testfall-Matrix – AMB Dual MA Signal

> Test Mode im Indikator aktivieren (Gruppe "Debug") → zeigt TC-Subtyp-Label direkt im Chart.

---

## Legende

| Kürzel | Bedeutung |
|---|---|
| SlowMA | Slow MA (130 SMA Daily, Trendfilter) |
| FastMA | Fast MA (44 SMA Daily, Exit/Re-Entry) |
| FastMA je berührt | Kurs hat seit letztem Entry mindestens eine Kerze **über** (Long) bzw. **unter** (Short) FastMA geschlossen |
| position_open | Aktuell offener Trade |
| lastDir | `lastSignalDirection`: 1=Long, -1=Short, 0=nie |

---

## Gruppe A – Erstmalige Entries (OL / OS)

| TC | Debug-Label | Signal | Ausgangslage | Kerzenschluss-Bedingung | Erwartetes Resultat |
|---|---|---|---|---|---|
| A-01 | A01 | **OL** | Kein Trade offen, lastDir ≠ Long | Kurs schliesst **über** SlowMA (Crossover von unten) | OL angezeigt, Long eröffnet |
| A-02 | – | –  | Kein Trade offen, lastDir ≠ Long | Kurs schliesst unter SlowMA | Kein Signal |
| A-03 | A03 | **OS** | Kein Trade offen, lastDir ≠ Short | Kurs schliesst **unter** SlowMA (Crossunder von oben) | OS angezeigt, Short eröffnet |
| A-04 | – | – | Kein Trade offen, lastDir ≠ Short | Kurs schliesst über SlowMA | Kein Signal |

---

## Gruppe B – Re-Entries (RL / RS)

| TC | Debug-Label | Signal | Ausgangslage | Kerzenschluss-Bedingung | Erwartetes Resultat |
|---|---|---|---|---|---|
| B-01 | B01 | **RL** | Kein Trade offen, lastDir = Long, Kurs über SlowMA | Kurs schliesst **über** FastMA (Crossover von unten) | RL angezeigt, Long eröffnet |
| B-02 | – | – | Kein Trade offen, lastDir = Long, Kurs **unter** SlowMA | Kurs schliesst über FastMA | Kein Signal (SlowMA-Bedingung verletzt) |
| B-03 | – | – | Kein Trade offen, lastDir = **Short** | Kurs schliesst über FastMA, über SlowMA | Kein Signal (lastDir ≠ Long) |
| B-04 | B04 | **RS** | Kein Trade offen, lastDir = Short, Kurs unter SlowMA | Kurs schliesst **unter** FastMA (Crossunder von oben) | RS angezeigt, Short eröffnet |
| B-05 | – | – | Kein Trade offen, lastDir = Short, Kurs **über** SlowMA | Kurs schliesst unter FastMA | Kein Signal (SlowMA-Bedingung verletzt) |
| B-06 | – | – | Kein Trade offen, lastDir = **Long** | Kurs schliesst unter FastMA, unter SlowMA | Kein Signal (lastDir ≠ Short) |

---

## Gruppe C – Exits (CL / CS)

| TC | Debug-Label | Signal | Ausgangslage | Kerzenschluss-Bedingung | Erwartetes Resultat |
|---|---|---|---|---|---|
| C-01 | C01 | **CL-A** | Long offen, FastMA **je berührt** | Kurs schliesst **unter** FastMA (Crossunder) | CL angezeigt, Long geschlossen |
| C-02 | C02 | **CL-B** | Long offen, FastMA **nie berührt** | Kurs schliesst **unter** SlowMA (Crossunder) | CL angezeigt, Long geschlossen |
| C-03 | – | – | Long offen, FastMA **nie berührt** | Kurs schliesst unter FastMA, **nicht** unter SlowMA | Kein Exit |
| C-04 | C04 | **CS-A** | Short offen, FastMA **je berührt** | Kurs schliesst **über** FastMA (Crossover) | CS angezeigt, Short geschlossen |
| C-05 | C05 | **CS-B** | Short offen, FastMA **nie berührt** | Kurs schliesst **über** SlowMA (Crossover) | CS angezeigt, Short geschlossen |
| C-06 | – | – | Short offen, FastMA **nie berührt** | Kurs schliesst über FastMA, **nicht** über SlowMA | Kein Exit |
| C-07 | C01 | **CL-B** | Long offen, FastMA **je berührt** | Kurs kreuzt SlowMA nach **unten** (nicht FastMA) | CL angezeigt, Long geschlossen |
| C-08 | C05 | **CS-B** | Short offen, FastMA **je berührt** | Kurs kreuzt SlowMA nach **oben** (nicht FastMA) | CS angezeigt, Short geschlossen – **war der Bug-Fall** |

---

## Gruppe F – Flip (Exit + Entry auf gleicher Kerze)

| TC | Debug-Label | Signale | Ausgangslage | Kerzenschluss-Bedingung | Erwartetes Resultat |
|---|---|---|---|---|---|
| F-01 | C02 + FS | **CL-B + OS** | Long offen, FastMA nie berührt | Schliesst **unter SlowMA** | CL und OS auf gleicher Kerze |
| F-02 | C01 | **CL-A only** | Long offen, FastMA je berührt | Schliesst unter FastMA, **nicht** unter SlowMA | Nur CL, kein OS |
| F-03 | C01 + FS | **CL-A + OS** | Long offen, FastMA je berührt | Schliesst unter FastMA **und** unter SlowMA | CL und OS auf gleicher Kerze |
| F-04 | C05 + FL | **CS-B + OL** | Short offen, FastMA nie berührt | Schliesst **über SlowMA** | CS und OL auf gleicher Kerze |
| F-05 | C04 | **CS-A only** | Short offen, FastMA je berührt | Schliesst über FastMA, **nicht** über SlowMA | Nur CS, kein OL |
| F-06 | C04 + FL | **CS-A + OL** | Short offen, FastMA je berührt | Schliesst über FastMA **und** über SlowMA | CS und OL auf gleicher Kerze |
| F-07 | A01 | **OL only** | Kein Trade offen | Crossover SlowMA nach oben | Nur OL, kein CS |
| F-08 | A03 | **OS only** | Kein Trade offen | Crossunder SlowMA nach unten | Nur OS, kein CL |

---

## Test-Status

| TC-Gruppe | Status | Letzte Prüfung | Anmerkungen |
|---|---|---|---|
| A – Erstmalige Entries | 🔲 Offen | – | – |
| B – Re-Entries | 🔲 Offen | – | – |
| C – Exits | � In Test | 2026-04-03 | C-08 war Bug (CHG-002), Fix umgesetzt in v1.3 |
| F – Flip | 🟡 In Test | 2026-04-03 | CHG-001, Schritt 9 |

---

## Änderungshistorie

| Datum | Änderung |
|---|---|
| 2026-04-03 | Initiale Version erstellt. Gruppen A/B neu, C und F aus CHG-001 übernommen und erweitert. |

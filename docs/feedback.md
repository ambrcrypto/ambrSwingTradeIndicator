# Feedback zur letzten Session

Datum: 2026-06-18
Scope: Walk-Forward-Tests, Ergebnisinterpretation, Doku-Konsistenz

## Was gut war

- Klarer methodischer Fortschritt von statischen Backtests zu Walk-Forward-Ansatz.
- Reproduzierbare Testausgaben in `backtest/results/walk_forward/output.txt`.
- Gute Grundidee der Szenarien (24M Rolling, Expanding, Static, 48M Cycle).
- Trade-Stitching-Regel (Parameterwechsel nur im Flat-State) ist fachlich richtig.

## Hauptprobleme (Review)

1. Inkonsistente Szenario-Bezeichnung im Code
- Im Trainingsblock ist Szenario B als Expanding Window implementiert.
- In der Ausgabe wird Szenario B als "Halving Surfer (Rolling 48M)" gelabelt.
- Folge: Ergebnisinterpretation war teilweise verfalscht.

2. Doppelte 48M-Logik in einem Lauf
- Es existiert ein separates Szenario D mit 48M.
- Gleichzeitig wurde B als 48M benannt.
- Folge: Bericht und Diskussion wurden unnotig verwirrend.

3. Doku nicht vollstandig synchron zum finalen Run
- Methodik-Doku und letzte Runs nutzen nicht in allen Punkten identische Szenario-Definitionen.
- OOS-Zeitraum wurde zwischen Runs geandert, ohne durchgehend sauber zu versionieren.

## Verifizierte Resultate aus aktuellem Output

Quelle: `backtest/results/walk_forward/output.txt`

- Scenario A (Rolling 24M):
  - Net P/L: 5662.5%
  - Max DD: 40.39%
  - Calmar: 29.789

- Scenario B (im Code als Expanding trainiert, im Output aber als 48M benannt):
  - Net P/L: 1604.65%
  - Max DD: 62.17%
  - Calmar: 5.481

- Scenario C (Static Baseline):
  - Net P/L: 717.73%
  - Max DD: 31.53%
  - Calmar: 4.837

- Scenario D (Rolling 48M):
  - Net P/L: 660.51%
  - Max DD: 57.82%
  - Calmar: 2.463

## Schlussfolgerung

- Die 24M-Rolling-Variante bleibt der klare Favorit.
- Die Aussage ist jedoch erst voll belastbar, wenn die Szenario-Namen und Definitionen im Code eindeutig konsistent sind.
- Aktuell ist die Richtung richtig, aber die Reporting-Disziplin muss strikter werden.

## Konkrete Empfehlungen (next)

1. Skript bereinigen
- Eindeutige Szenarien:
  - A = Rolling 24M
  - B = Expanding
  - C = Static
  - D = Rolling 48M
- Ausgabe-Titel exakt an Trainingslogik koppeln.

2. Sauberen Re-Run durchfuhren
- Gleiches OOS-Fenster fur alle 4 Szenarien.
- Ergebnisdatei mit Timestamp im Dateinamen speichern.

3. Doku harmonisieren
- `docs/WALK_FORWARD_METHODOLOGY.md` auf finalen, bereinigten Run aktualisieren.
- Kurzprotokoll mit "Was wurde geandert" + "Warum" hinterlegen.

4. Entscheidungsregel fixieren
- Produktion auf 24M-Rolling + 6M-Rebalance ausrichten,
- aber nur nach bestandenem Konsistenz-Re-Run final freigeben.

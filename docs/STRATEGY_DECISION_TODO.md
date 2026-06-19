# Strategy Decision Todo

Date: 2026-06-18

## Ziel

Die bestehende AMB-Strategie soll nur dann mit neuen Parametern weitergefuehrt werden, wenn das neue Setup nicht nur mehr P/L, sondern auch ein vertretbares Risiko-/Verlustprofil liefert.

## Referenz: aktuelle Live-Strategie

- Slow MA: EMA 130
- Fast MA: SMA 60
- Leverage Long: 3.75x
- Leverage Short: 0.5x
- Stop Loss: 3.0%
- Start: 2025-04-01
- P/L: 151.13%
- MaxDD: 9.46%
- Profit Factor: 5.37
- Win Rate: 33.33%
- Expectancy: 4.84%
- Trades: 21

## Alternative: Fine 2026

- Slow MA: SMA 130
- Fast MA: SMA 60
- Leverage Long: 4.5x
- Leverage Short: 2.5x
- Stop Loss: 9.5%
- P/L: 201.47%
- MaxDD: 34.78%
- Profit Factor: 3.679
- Win Rate: 42.86%
- Expectancy: 10.05%
- Trades: 14

## Kernaussage

- Fine 2026 liefert mehr Ertrag.
- Die aktuelle Strategie liefert das klar bessere Drawdown- und Verlustprofil.
- Der Unterschied liegt nicht nur im Signalmodell, sondern vor allem im Risikomodell.
- Ein Wechsel auf Fine 2026 waere ein echter Strategiewechsel, kein kleines Tuning.

## Entscheidung aktuell

- Die aktuelle Strategie bleibt vorerst die bevorzugte Live-Variante.
- Fine 2026 wird nicht blind uebernommen.
- Ein Wechsel auf Fine 2026 erfolgt nur als bewusste Risikoentscheidung.

## Todo

1. Die aktuelle Strategie als offiziellen Benchmark beibehalten.
2. Fine 2026 als aggressive Alternative dokumentiert halten.
3. Bei kuenftigen Reviews nicht nur P/L, sondern immer auch MaxDD, Profit Factor, Avg Loss und SL-Rate vergleichen.
4. Neue Parameter nur uebernehmen, wenn sie gegenueber der aktuellen Live-Strategie insgesamt ueberzeugen.
5. Wenn ein Wechsel erfolgt, dann nur im Flat-State und nie mitten in einem offenen Trade.
6. Den halbjaehrlichen Review-Prozess beibehalten:
   - Stichtage: 1. April und 1. Oktober
   - Lookback: 24 Monate
   - Vergleich immer gegen die aktuelle Live-Strategie
7. Vor jedem kuenftigen Wechsel klar festhalten:
   - Was aendert sich am Signalmodell?
   - Was aendert sich am Risikomodell?
   - Ist es ein Tuning oder ein Strategiewechsel?

## Vorlaeufiges Fazit

- Coarse 2026 ist gegenueber der aktuellen Strategie nicht attraktiv.
- Fine 2026 ist interessant, aber deutlich aggressiver.
- Solange kein bewusster Strategiewechsel gewuenscht ist, bleibt die aktuelle Strategie die sauberere Wahl.
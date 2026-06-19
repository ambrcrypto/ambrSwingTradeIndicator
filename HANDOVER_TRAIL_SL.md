# Handover: ATR Trailing Stop + Re-Entry

**Datum:** 2026-05-23  
**Kontext:** AMB Dual MA Signal – Python Backtest (`strategy_amb.py`)  
**Ziel:** ATR-basierten Trailing Stop als dritten Exit-Mechanismus implementieren + regelbasierter Re-Entry danach

---

## Ausgangslage

Realer Trade: Long +15% im Profit, kein systematischer Gewinnschutz → Gewinn vernichtet durch FOMO Re-Entries. Kernproblem ist nicht der Entry, sondern der fehlende systematische Exit bei laufenden Gewinnen.

Bereits getestet und verworfen:
- HMM-Filter: funktioniert, aber nur 11 Trades (statistisch wertlos)
- ADX+ATR Entry-Filter: konzeptuell falsch für MA-Crossover (zu spät im Trend)

---

## Zieldatei

`backtest/strategy_amb.py` — 1:1 Mirror des Pine Script Indikators.

Bestehende SL-Modi zur Orientierung:
- `sl_enable` + `sl_risk_pct`: fixer %-SL auf Kapital
- `atr_sl_enable` + `atr_sl_mult`: ATR-SL, eingefroren am Entry-Bar

Der Trailing Stop ist ein **dritter, unabhängiger Modus** — er bewegt sich mit dem Preis mit (Ratchet-Mechanismus).

---

## Schritt 1 – Neue Parameter in `AMBParams`

Nach `atr_sl_mult` (aktuell Zeile 36) einfügen:

```python
trail_sl_enable:       bool  = False
trail_activate_pct:    float = 5.0    # Trail aktiviert sich ab X% unrealised Gewinn
trail_atr_factor:      float = 2.0    # Trail-Abstand = ATR(14) × factor
trail_atr_len:         int   = 14     # ATR-Periode (Wilder RMA, identisch zu _calc_atr)
```

`label()` erweitern (analog zu `atr_sl`-Branch):
```python
if self.trail_sl_enable:
    sl_str = f"Trail{self.trail_activate_pct:.0f}pct_x{self.trail_atr_factor:.1f}"
```

`as_dict()` um alle vier neuen Felder ergänzen.

---

## Schritt 2 – ATR-Array für Trail

In `run_strategy()`, direkt nach der bestehenden `atr`-Berechnung (aktuell Zeile 197):

```python
atr_trail = _calc_atr(high, low_, close, params.trail_atr_len) \
    if params.trail_sl_enable else np.full(n, np.nan)
```

Die bestehende `_calc_atr`-Funktion kann direkt wiederverwendet werden.

---

## Schritt 3 – Neue State-Variablen

Im State-Block (aktuell Zeilen 201–217) hinzufügen:

```python
trail_active:         bool  = False
trail_sl_level:       float = 0.0   # aktuelles Trail-Level, jede Bar aktualisiert
trail_reentry_armed:  bool  = False # True nach Trail-Exit, wartet auf FastMA-Bounce
```

---

## Schritt 4 – Trail-Level-Update (jede Bar)

Einzufügen **nach** dem Fast-MA-State-Tracking (nach Zeile 238), **vor** den Crossover-Berechnungen.

```python
if params.trail_sl_enable and position_open:
    atr_t = atr_trail[i] if not np.isnan(atr_trail[i]) else 0.0
    if last_dir == 1:
        unrealised_pct = (c - entry_price) / entry_price * 100.0
        if unrealised_pct >= params.trail_activate_pct:
            trail_active = True
        if trail_active and atr_t > 0:
            new_level = c - atr_t * params.trail_atr_factor
            trail_sl_level = max(trail_sl_level, new_level)  # nur aufwärts ratchet
    elif last_dir == -1:
        unrealised_pct = (entry_price - c) / entry_price * 100.0
        if unrealised_pct >= params.trail_activate_pct:
            trail_active = True
        if trail_active and atr_t > 0:
            new_level = c + atr_t * params.trail_atr_factor
            trail_sl_level = min(trail_sl_level, new_level)  # nur abwärts ratchet
```

**Ratchet-Regel:** `trail_sl_level` bewegt sich nur in Gewinnrichtung — nie zurück. Daher `max()` für Long, `min()` für Short.

---

## Schritt 5 – Trail-Exit-Bedingungen

In den Exit-Conditions (nach Zeile 276) einfügen:

```python
exit_long_TSL  = (params.trail_sl_enable and trail_active
                  and last_dir == 1  and lo <= trail_sl_level)
exit_short_TSL = (params.trail_sl_enable and trail_active
                  and last_dir == -1 and h  >= trail_sl_level)
```

Die bestehenden Exit-Aggregationen erweitern:

```python
exit_long  = exit_long_A  or exit_long_B  or exit_long_SL  or exit_long_TSL
exit_short = exit_short_A or exit_short_B or exit_short_SL or exit_short_TSL
```

---

## Schritt 6 – P/L-Berechnung und Trade-Record bei Trail-Exit

Im Exit-State-Machine-Block (aktuell Zeile 342ff.) für Long:

```python
if exit_long_TSL:
    exit_price_actual = trail_sl_level   # intrabar, nicht close
    exit_type_str     = "TSL"
    pct = ((exit_price_actual - entry_price) / entry_price * 100.0) * params.leverage_long
    trail_reentry_armed = True           # Re-Entry aktivieren
elif exit_long_SL:
    ...  # bestehende Logik unverändert
else:
    exit_price_actual = c
    exit_type_str     = "CL"
    pct = ((c - entry_price) / entry_price * 100.0) * params.leverage_long
```

Spiegelverkehrt für Short (`exit_type_str = "TSS"`, `leverage_short`).

`Trade.exit_type` akzeptiert damit neu auch `"TSL"` und `"TSS"` — kein struktureller Change am Dataclass nötig, es ist ein freier String.

---

## Schritt 7 – Re-Entry nach Trail-Exit

**Logik:** Preis bricht über FastMA, SlowMA noch bullisch (Trend intakt), kein neuer Downward-Cross des SlowMA seit Trail-Exit.

In den Entry-Conditions (nach Zeile 289) hinzufügen:

```python
trail_reentry_long  = (trail_reentry_armed and not position_open
                       and last_dir == 1 and cross_above_fast and c > s)
trail_reentry_short = (trail_reentry_armed and not position_open
                       and last_dir == -1 and cross_below_fast and c < s)
```

In die Signal-Aggregation einbauen:

```python
long_signal  = ((long_entry or long_reentry or trail_reentry_long)  and params.allow_longs)  or flip_to_long
short_signal = ((short_entry or short_reentry or trail_reentry_short) and params.allow_shorts) or flip_to_short
```

`trail_reentry_armed` auf `False` setzen wenn:
- Ein neuer Trade eröffnet wird (in "Open new position"-Block)
- `cross_below_slow` eintritt (Trend gedreht, Re-Entry wäre konträr)

---

## Schritt 8 – Reset beim Trade-Open

Im "Open new position"-Block (aktuell Zeile 389ff.) für **beide** Richtungen ergänzen:

```python
trail_active        = False
trail_sl_level      = 0.0
trail_reentry_armed = False
```

---

## Schritt 9 – Vergleichs-Skript

Neues `backtest/run_trail_comparison.py` analog zu `run_hmm_comparison.py`.

Vier Varianten backtesten (BTC-USD, gleicher Zeitraum wie Baseline):

| Label | `trail_activate_pct` | `trail_atr_factor` |
|---|---|---|
| Baseline | — (trail disabled) | — |
| Trail 5%/2.0x | 5 | 2.0 |
| Trail 10%/1.5x | 10 | 1.5 |
| Trail 15%/3.0x | 15 | 3.0 |

Output pro Variante: Sharpe, Sortino, CAGR, MaxDD, n_trades, davon TSL-Exits, davon Trail-Re-Entries.

---

## Offene Fragen (sollen durch den Backtest beantwortet werden)

1. Welche Kombination `trail_activate_pct` / `trail_atr_factor` ist optimal?
2. Verbessert der Trailing Stop Sortino/Calmar messbar gegenüber Baseline?
3. Wie oft triggert der Trail-Re-Entry vs. regulärer Re-Entry (cross_above_fast)?
4. Gibt es Parameter-Cluster (Robustheit) oder nur einzelne Peaks (Overfitting)?

---

## Nicht tun

- Den bestehenden `atr_sl_enable`-Modus **nicht** anfassen — er bleibt unverändert
- `trail_sl_enable` und `atr_sl_enable` sollten sich gegenseitig ausschliessen (Guard-Check in `run_strategy()` empfohlen)
- Kein Flip-Mechanismus bei TSL-Exit (analog zu regulärem SL: kein Flip)

---

## Rückfragen (Claude, 2026-05-23)

**F1 – Intrabar Exit-Preis**  
Schritt 6 setzt `exit_price_actual = trail_sl_level`. Bei Daily-Bars kann der Preis intrabar durch das Trail-Level fallen und dann noch tiefer schließen. Das führt im Backtest zu einem zu optimistischen Exit-Preis.  
→ Gewünscht: Exit immer auf `trail_sl_level` (optimistisch/Pine-Script-like), oder pessimistisch auf `low` wenn `low <= trail_sl_level`?

**A1:** Exit auf `trail_sl_level` — konsistent mit dem bestehenden `atr_sl_enable`-Modus (der macht es identisch) und mit Pine Script-Verhalten. Der Backtest soll mit TradingView vergleichbar sein, nicht konservativer. Wer einen Worst-Case braucht, kann `sl_enable` als Floor kombinieren (→ F3).

---

**F2 – Exit-Priorität bei Kollision**  
Wenn `exit_long_TSL` und `exit_long_A` am selben Bar beide `True` sind (Trail gerissen + FastMA-Crossdown gleichzeitig): welcher `exit_type_str` soll im Trade-Record stehen? Vorschlag: TSL hat Vorrang (er ist der frühere intrabar Auslöser).  
→ Bestätigen oder andere Priorität?

**A2:** Bestätigt — TSL hat Vorrang. Reihenfolge im if/elif-Block: `exit_long_TSL` vor `exit_long_SL` vor `exit_long_A/B`. Begründung: TSL und SL sind intrabar-Trigger (prüfen `low`/`high`), MA-Exits sind Schlusskurs-Trigger — intrabar hat zeitlich Vorrang.

---

**F3 – `trail_sl_enable` + `sl_enable` gleichzeitig**  
Die Spec schließt `trail_sl_enable` und `atr_sl_enable` gegenseitig aus, aber `sl_enable` (fixer %-SL) wird nicht erwähnt. Ist die Kombination Trail + fixer SL erlaubt (fixed SL als Worst-Case-Floor)?  
→ Erlaubt, oder auch gegenseitig ausschließen?

**A3:** Erlaubt und erwünscht. Der fixe %-SL (z.B. −3%) dient als Worst-Case-Floor für den Fall, dass der Trail noch nicht aktiv ist (Trade noch nicht >X% im Profit). Die Kombination ergibt: unter Aktivierungsschwelle schützt der %-SL, darüber übernimmt der Trail. Kein Guard nötig — beide können parallel laufen, der zuerst feuernde Exit gewinnt (TSL hat Vorrang per F2).

---

**F4 – Parametervarianten**  
3 Varianten (5%/2.0, 10%/1.5, 15%/3.0) sind für eine erste Validierung ok. Soll das Vergleichs-Skript nur diese 3 Varianten testen, oder einen vollständigen Grid-Scan (z.B. activate_pct ∈ {3,5,10,15} × atr_factor ∈ {1.5,2.0,3.0}) mit Tabellen-Ausgabe?

**A4:** Grid-Scan — `activate_pct ∈ {3, 5, 8, 10, 15}` × `atr_factor ∈ {1.0, 1.5, 2.0, 2.5, 3.0}` = 25 Kombinationen. Tabellen-Ausgabe als HTML (analog bestehende Comparison-Skripte). Nur so lässt sich ein robuster Parameter-Cluster von einem einzelnen Peak unterscheiden. Die 3 Handover-Varianten bleiben als "Highlight-Zeilen" in der Tabelle markiert.

# Getting Started – AMB Dual MA Signal

Dieses Dokument erklärt Setup, ersten Backtest-Run, Optimierung und Metrik-Interpretation für Neueinsteiger.

---

## 1. Voraussetzungen

- **Python 3.11+**
- **TradingView** (für den Live-Indikator)
- Internetzugang für den ersten Daten-Download (yfinance → Binance/Yahoo)

---

## 2. Setup (einmalig)

```bash
# 1. Ins Projektverzeichnis wechseln
cd ambSwingTradeIndicator

# 2. Virtuelle Umgebung erstellen und aktivieren
python -m venv .venv

# Windows:
.\.venv\Scripts\activate

# macOS/Linux:
source .venv/bin/activate

# 3. Abhängigkeiten installieren
pip install -r backtest/requirements.txt
```

Beim ersten Backtest-Run lädt das System automatisch historische OHLCV-Daten via yfinance herunter (~5 Sekunden für BTC-USD) und speichert sie in `backtest/cache/`. Danach wird der Cache verwendet (gültig 23h).

---

## 3. Erster Backtest-Run

```bash
# BTC-USD mit Live-Konfiguration v1.6.1 (Standard)
python -m backtest.run --ticker BTC-USD --period 2021_default
```

**Erwartete Ausgabe:**
- Metriken-Tabelle (P/L%, MaxDD, Calmar, Win-Rate, ...)
- Trade-Liste (optional mit `--trades`)
- Monte-Carlo-Simulation (1000 Runs, optional mit `--mc 0` deaktivieren)

**Mit Trade-Liste:**
```bash
python -m backtest.run --ticker BTC-USD --period 2021_default --trades
```

**Referenzwerte v1.6.1 (2021-04-14 → 2023-10-31):**
- Trades: 42 | P/L: +145% | MaxDD: 32%

**Verfügbare Perioden** (`--period`):

| Name | Beschreibung |
|------|-------------|
| `2021_default` | 2021-04-14 → heute (Pine Script Default) |
| `btc_p1_bull_2017` | 2017 Bull: $900 → $20k |
| `btc_p2_bear_2018` | 2018 Bear: −84% |
| `btc_p3_sideways_2019` | 2019–2020 Seitwärts/Recovery |
| `btc_p4_bull_2020_2021` | COVID-Bull + ATH $69k |
| `btc_p5_bear_2022` | 2022 Bear: −78%, FTX |
| `btc_p6_bull_2023_2024` | ETF-Zulassung + Halving |
| `btc_p7_current_2025` | 2025+ (Out-of-Sample) |

**Benutzerdefinierte Periode:**
```bash
python -m backtest.run --ticker BTC-USD --period custom --start 2022-01-01 --end 2023-01-01
```

---

## 4. Parameter überschreiben

Alle Parameter aus `ticker_config.py` können per CLI überschrieben werden:

```bash
python -m backtest.run --ticker BTC-USD --period 2021_default \
  --slow 130 --fast 44 \
  --llong 3.0 --lshort 0.5 \
  --sl 6.0
```

| Flag | Bedeutung | BTC-USD Default |
|------|-----------|----------------|
| `--slow` | Slow MA Länge | 130 |
| `--fast` | Fast MA Länge | 44 |
| `--slow-type` | SMA oder EMA | SMA |
| `--llong` | Leverage Long | 3.0 |
| `--lshort` | Leverage Short | 0.5 |
| `--sl` | Stop Loss % (0 = aus) | 6.0 |
| `--no-shorts` | Nur Long-Trades | – |
| `--no-fast-ma` | Kein Fast MA (Slow-only) | – |

---

## 5. Optimierung

```bash
# Schnelle Optimierung BTC-USD (empfohlen zum Starten)
python -m backtest.run_optimize --ticker BTC-USD --mode btc_quick

# 7-Perioden Robustness-Test (findet Parameter die in allen BTC-Phasen funktionieren)
python -m backtest.run_optimize --ticker BTC-USD --mode btc_quick --robustness

# Vollständige Optimierung (dauert länger)
python -m backtest.run_optimize --ticker BTC-USD --mode btc_full
```

Ergebnisse werden als CSV in `backtest/results/` gespeichert.

---

## 6. Regressionstests

Nach jeder Code-Änderung an `strategy_amb.py` oder `engine.py`:

```bash
pytest backtest/tests/ -v
```

19 Tests prüfen Signal-Logik (Gruppen A/B/C/D/F) und die v1.6.1 Referenzwerte. Alle grün = Logik intakt.

---

## 7. Metrik-Glossar

| Metrik | Bedeutung | Gut wenn |
|--------|-----------|----------|
| **P/L%** | Gesamtrendite (kumuliert, mit Leverage) | > 0% |
| **MaxDD%** | Maximaler Drawdown vom Peak | < 40% |
| **Calmar** | Annualisierte Rendite / MaxDD — primäres Ranking | > 1.5 |
| **Win-Rate** | Anteil profitabler Trades | > 40% (Trend-Systeme oft niedriger) |
| **Profit Factor** | Summe Gewinne / Summe Verluste | > 1.5 |
| **Expectancy** | Erwarteter P/L pro Trade (%) | > 0 |
| **SL-Anzahl** | Anzahl Stop-Loss-Exits | Verhältnis SL/Trades < 40% |

**Liquidationsrisiko:** MaxDD ≥ 80% bei 3× Leverage = Wipe-out-Gefahr. Das System warnt automatisch.

**Calmar als Hauptmetrik:** Bevorzugt Strategien die gute Rendite bei kontrolliertem Drawdown erzielen — relevanter als reines P/L% für gehebelte Portfolios.

---

## 8. Neuen Ticker hinzufügen

1. Eintrag in `backtest/ticker_config.py` ergänzen:

```python
"MEIN-TICKER": AMBParams(
    slow_ma_len=130, slow_ma_type="SMA",
    fast_ma_len=44,  fast_ma_type="SMA",
    leverage_long=2.0, leverage_short=0.5,
    sl_enable=True, sl_risk_pct=8.0,
    signal_tf="D",
),
```

2. Optimierung laufen lassen um Leverage + SL-% zu kalibrieren:
```bash
python -m backtest.run_optimize --ticker MEIN-TICKER --mode quick --robustness
```

3. Faustregeln für Leverage:
   - Volatile Assets (BTC, ETH): Long 2–4×, Short 0.5–1×
   - Equities (VOO, SPY): Long 1.5–2×, Short 1×
   - Short-Leverage niedrig halten: SL-Preistoleranz = `sl_risk_pct / (100 × leverage_short)`

---

## 9. TradingView-Indikator einrichten

1. `AMB Dual MA Signal.pine` in TradingView Pine Editor einfügen
2. Chart: **BTC-USD Daily**
3. Inputs gemäss `ticker_config.py` einstellen:
   - Slow MA: EMA, 130
   - Fast MA: SMA, 60
   - Leverage Long: 3.75, Short: 0.5
   - Stop Loss: 3.0%
4. **4 Alerts anlegen** (je eine Condition):
   - `ENTER LONG` → Alert bei Signal
   - `EXIT LONG`
   - `ENTER SHORT`
   - `EXIT SHORT`
5. Alerts feuern nur auf **bestätigten Tageskerzen** (kein Repainting).

---

## 10. Projektstruktur

```
ambSwingTradeIndicator/
├── AMB Dual MA Signal.pine        ← Live TradingView Indikator
├── CHANGELOG.md                   ← Versionshistorie
├── CHANGES.md                     ← Formale Change Requests (CHG-001 ff.)
├── REQUIREMENTS.md                ← Strategieregeln + Change-Prozess
├── ROLES.md                       ← Team-Rollen (BA, Trading-Expert, Dev)
├── TESTCASES.md                   ← Manuelle TC-Matrix (Gruppen A–F)
├── BACKTEST_COMPARISON.md         ← Pine vs. Python Abgleich
└── backtest/
    ├── requirements.txt           ← Python-Abhängigkeiten
    ├── strategy_amb.py            ← Kernlogik (1:1 Spiegel von Pine)
    ├── ticker_config.py           ← Konfigurationen je Ticker
    ├── data.py                    ← Daten-Download + Caching
    ├── engine.py                  ← Metriken-Berechnung
    ├── optimize.py                ← Grid-Search
    ├── run.py                     ← CLI: Einzelner Backtest
    ├── run_optimize.py            ← CLI: Optimierung
    ├── montecarlo.py              ← Monte-Carlo-Simulation
    ├── report.py                  ← Ausgabe-Formatierung
    ├── diagnose_discrepancy.py    ← Diagnose-Export (Pine vs. Python)
    ├── tests/
    │   ├── test_signals.py        ← Unit-Tests Signal-Logik (synth.)
    │   └── test_regression.py     ← Regressions-Test v1.6.1
    ├── cache/                     ← Automatisch heruntergeladene OHLCV-Daten
    └── results/                   ← Optimierungs-Ergebnisse (CSV)
```

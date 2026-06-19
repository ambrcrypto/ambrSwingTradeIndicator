# Walk-Forward Analysis (WFA) Methodology

## 1. Context & Motivation
Historically, the AMB Swing Strategy was optimized using static historical periods (e.g., "2021 Bull Run", "2022 Bear Market"). While this produces robust "all-weather" parameters, it often sacrifices yield in current market regimes. 
To adapt to the fast-changing crypto market, we are implementing a rigorous **Out-of-Sample Walk-Forward Analysis**.

## 2. Data Strategy
* **Source:** Binance Spot (`BTC/USDT`) via CCXT.
* **Why:** `yfinance` aggregates data causing "fake wicks", triggering unrealistic stop-losses in backtests. Binance provides the highest liquidity reference starting from **August 17, 2017**.
* **Scope:** 2017-Present accurately covers exactly three major crypto cycles. Going back further (e.g., 2014) trains the model on pre-institutional, low-liquidity patterns that are no longer relevant.

## 3. The 3 Competing Scenarios
We test three distinct memory models to identify the most robust approach for future live trading. Rebalancing occurs semi-annually on **April 1st** and **October 1st**.

### A. The Sprinter (24-Month Rolling Window)
* **Memory:** Short-term. 
* **Mechanism:** Retrains at every checkpoint using *only* the preceding 24 months of data.
* **Hypothesis:** Adapts quickly to new regimes (e.g., ETF approval volatility) and forgets outdated market behavior. Expected to yield the best risk-adjusted returns (Calmar Ratio).

### B. The Elephant (Expanding Window)
* **Memory:** Long-term.
* **Mechanism:** Retrains at every checkpoint using *all* available data from August 2017 up to the checkpoint.
* **Hypothesis:** Finds ultra-stable, long-term parameter plateaus but may become too sluggish to adapt to recent market shifts.

### C. The Stubborn (Static Baseline v1.8.5)
* **Memory:** Set & Forget (Zero Rebalancing).
* **Mechanism:** Uses the current baseline parameters (`EMA 130 / SMA 60 / SL 3.0%`) for the entire out-of-sample period.
* **Hypothesis:** Serves as the benchmark. Should underperform dynamically rebalanced models over a 7-year horizon due to regime decay.

### D. The Halving Surfer (Rolling 48M)
* **Memory:** Full Crypto Cycle (4 Years).
* **Mechanism:** Retrains at every checkpoint using the preceding 48 months of data.
* **Hypothesis:** Built on the assumption that a 4-year lookback forces the optimizer to "digest" an entire Bitcoin Halving cycle (bull, bear, sideways) ensuring maximum robustness.

## 4. Engineering Rules (Trade Stitching)
* **Rule:** Parameters are *never* updated while a trade is open. 
* **Action:** If a checkpoint (e.g., April 1st) is reached during an open position, the old parameters remain active until the trade is closed (Flat state). The new parameters are applied exclusively to the *next* entry.

## 5. Results & Conclusion (2021-08 to 2026-06 OOS)
Extensive walk-forward testing revealed that **Scenario A (Testing purely on 24 months, rebalancing every 6 months)** drastically outperforms all other models.

Verified KPI from the exact consolidated run:
* **The Sprinter (24M Rolling):** Net P/L: 5790.82%, Max DD: 40.39%, Calmar: 30.411
* **The Elephant (Expanding):** Net P/L: 1739.87%, Max DD: 62.17%, Calmar: 5.933
* **The Stubborn (Baseline):** Net P/L: 735.94%, Max DD: 31.53%, Calmar: 4.951
* **The Cycle Surfer (48M):** Net P/L: 660.51%, Max DD: 57.82%, Calmar: 2.463

* **Why 48M and Expanding failed:** They force the model to adapt to 3-to-5-year-old market structures (e.g. 2018 volatility) that are highly irrelevant to current institutional market structures (2024+).
* **The Verdict:** The Krypto market memory is exceptionally short. A 24-month lookback perfectly balances capturing the current volatility regime while providing enough data points (trades) for statistically sound optimization.

**Production Rule:** Every 6 months (April 1st, October 1st), the bot's configurations must be re-optimized exclusively over the trailing 24 months of data to extract the optimal settings for the upcoming semester.

---
*Date established: 2026-06-15. Review this document whenever altering the backtesting frequency or methodology.*

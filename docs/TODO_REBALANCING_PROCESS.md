# Live Parameter Rebalancing Todo

**Background:** 
Based on the Walk-Forward Analysis results (from 2026-06-15), the quantitatively proven best configuration strategy for the AMB Dual MA Bot is a **semi-annual rebalancing (April 1st, October 1st) using exclusively a 24-month lookback period.**

## Todolist for moving to the new production standard:

### 1. Build Operational Rebalancing Tool
- [ ] Create `backtest/run_semiannual_update.py`.
- [ ] This script must:
  - Download the absolute latest Binance data (up to "today").
  - Filter strictly for the **last 24 months** from current date.
  - Run the `btc_quick` grid optimizer.
  - Output the finalized, production-ready Pine Script parameters (MA Types/Lengths, Leverage, SL %) and Health Monitor KPI Thresholds (`win_rate`, `calmar`, `max_dd`).

### 2. Update Pine Script (TradingView)
- [ ] Run the tool from Step 1 to get the exact parameters for the current halving year (Mid-2024 to Mid-2026 window).
- [ ] Update `AMB Dual MA Signal.pine`:
  - Central parameter defaults.
  - Health Monitor values (to stop bot if live execution drifts severely out of the 24M expected envelope).
- [ ] Verify the script logic correctly supports "Exit before Entry" for safe live flip scenarios.

### 3. Update Automation System
- [ ] Update the default execution parameters in `backtest/ticker_config.py` for BTC-USD.
- [ ] Update `REQUIREMENTS.md` with the new default parameter table.
- [ ] Create a new entry in `CHANGES.md` (e.g. CHG-012) documenting the switch to the 6-month / 24M lookback cadence.
- [ ] Bump version in `CHANGELOG.md`.

### 4. Deployment (ambTradingAutomation Workspace)
- [ ] Port the new verified default parameters over to the Live Python Bot (`ambTradingAutomation` workspace).
- [ ] Deploy the bot code to Hetzner VPS (`.\deploy\scripts\deploy.ps1 -Component app`).
- [ ] Perform Health Checks (`test_james_health.ps1`).

### 5. Clean up
- [ ] Organize the generated WFA reports into `backtest/results/walk_forward/`.
- [ ] Commit all code changes with descriptive git messages indicating the methodology switch.
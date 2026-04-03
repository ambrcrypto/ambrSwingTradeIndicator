"""
montecarlo.py – Bootstrap Monte Carlo simulation.

Takes a list of Trade objects (from a specific param set) and
shuffles the trade order N times to build a distribution of possible outcomes.

This answers: "How much of this P/L is luck vs. skill?"
Output: percentile distribution of P/L and MaxDD.

Usage:
    from backtest.montecarlo import run_montecarlo, print_mc_summary
    trades = run_strategy(df, params)
    mc = run_montecarlo(trades, params, n_simulations=1000)
    print_mc_summary(mc)
"""

from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from .strategy_amb import Trade, AMBParams


# ─────────────────────────────────────────────────────────────────────────────
# Result container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MCResult:
    n_simulations: int
    n_trades:      int
    # P/L distribution (percentiles)
    pl_p5:   float
    pl_p25:  float
    pl_p50:  float   # median
    pl_p75:  float
    pl_p95:  float
    pl_mean: float
    # MaxDD distribution
    dd_p5:   float
    dd_p50:  float
    dd_p75:  float
    dd_p95:  float
    # Calmar distribution
    calmar_p50: float
    calmar_p95: float
    # Probability of positive outcome
    prob_profit:    float   # % of sims with P/L > 0
    prob_liq_risk:  float   # % of sims with MaxDD >= 80%
    # Original (non-shuffled) result for comparison
    original_pl:  float
    original_dd:  float


# ─────────────────────────────────────────────────────────────────────────────
# Core simulation
# ─────────────────────────────────────────────────────────────────────────────

def _compound_pnl_and_dd(percs: np.ndarray, start_capital: float) -> tuple[float, float]:
    """Compute compound P/L% and MaxDD% from array of trade returns."""
    capital = start_capital
    peak    = capital
    max_dd  = 0.0
    for p in percs:
        capital *= (1.0 + p / 100.0)
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    pl_pct = (capital - start_capital) / start_capital * 100.0
    return pl_pct, max_dd


def run_montecarlo(
    trades:        list[Trade],
    params:        AMBParams,
    n_simulations: int = 2000,
    seed:          int = 42,
) -> MCResult:
    """
    Bootstrap simulation: shuffle trade sequence N times,
    compute P/L and MaxDD for each shuffle.
    """
    if not trades:
        return MCResult(
            n_simulations=0, n_trades=0,
            pl_p5=0, pl_p25=0, pl_p50=0, pl_p75=0, pl_p95=0, pl_mean=0,
            dd_p5=0, dd_p50=0, dd_p75=0, dd_p95=0,
            calmar_p50=0, calmar_p95=0,
            prob_profit=0, prob_liq_risk=0,
            original_pl=0, original_dd=0,
        )

    rng   = np.random.default_rng(seed)
    percs = np.array([t.pct for t in trades])
    n     = len(percs)
    cap   = params.start_capital

    # Original (sequential) result
    orig_pl, orig_dd = _compound_pnl_and_dd(percs, cap)

    # Monte Carlo
    pl_list: list[float] = []
    dd_list: list[float] = []

    for _ in range(n_simulations):
        shuffled = rng.choice(percs, size=n, replace=True)   # bootstrap with replacement
        pl, dd   = _compound_pnl_and_dd(shuffled, cap)
        pl_list.append(pl)
        dd_list.append(dd)

    pl_arr = np.array(pl_list)
    dd_arr = np.array(dd_list)

    # Calmar per sim
    calmar_arr = np.where(dd_arr > 0.1, pl_arr / dd_arr, np.where(pl_arr > 0, 999.0, 0.0))

    prob_profit   = float(np.mean(pl_arr > 0) * 100)
    prob_liq_risk = float(np.mean(dd_arr >= 80.0) * 100)

    return MCResult(
        n_simulations = n_simulations,
        n_trades      = n,
        pl_p5         = float(np.percentile(pl_arr,  5)),
        pl_p25        = float(np.percentile(pl_arr, 25)),
        pl_p50        = float(np.percentile(pl_arr, 50)),
        pl_p75        = float(np.percentile(pl_arr, 75)),
        pl_p95        = float(np.percentile(pl_arr, 95)),
        pl_mean       = float(np.mean(pl_arr)),
        dd_p5         = float(np.percentile(dd_arr,  5)),
        dd_p50        = float(np.percentile(dd_arr, 50)),
        dd_p75        = float(np.percentile(dd_arr, 75)),
        dd_p95        = float(np.percentile(dd_arr, 95)),
        calmar_p50    = float(np.percentile(calmar_arr, 50)),
        calmar_p95    = float(np.percentile(calmar_arr, 95)),
        prob_profit   = prob_profit,
        prob_liq_risk = prob_liq_risk,
        original_pl   = orig_pl,
        original_dd   = orig_dd,
    )

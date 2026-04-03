"""
engine.py – Compute performance metrics from a list of Trade objects.

Primary ranking metric: Calmar Ratio = Annualized Return / MaxDD
(maximizes return while controlling drawdown – ideal for leveraged risk portfolio)

Liquidation risk flag: MaxDD >= 80% (with 3x leverage, 33% price drop = wipe-out)
"""

from __future__ import annotations
import numpy as np
from datetime import datetime
from .strategy_amb import Trade, AMBParams


# ─────────────────────────────────────────────────────────────────────────────
# Core metrics computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(
    trades:       list[Trade],
    params:       AMBParams,
    period_start: str,
    period_end:   str,
) -> dict:
    """
    Compute full performance metrics from closed trades.

    Returns a flat dict with all metrics, ready for CSV export.
    """
    base: dict = {**params.as_dict(), "period_start": period_start, "period_end": period_end}

    if not trades:
        return {**base, **_empty_metrics()}

    percs = [t.pct for t in trades]

    # ── Compound equity curve ────────────────────────────────────────────────
    capital  = params.start_capital
    peak     = capital
    max_dd   = 0.0
    equity   = [capital]

    for p in percs:
        capital *= (1.0 + p / 100.0)
        equity.append(capital)
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    pl_pct    = (capital - params.start_capital) / params.start_capital * 100.0
    end_cap   = capital

    # ── Win / loss breakdown ────────────────────────────────────────────────
    wins      = [p for p in percs if p >= 0]
    losses    = [p for p in percs if p < 0]
    n_trades  = len(percs)
    win_rate  = len(wins)  / n_trades * 100.0 if n_trades else 0.0
    avg_win   = float(np.mean(wins))   if wins   else 0.0
    avg_loss  = float(np.mean(losses)) if losses else 0.0
    sum_wins  = sum(wins)
    sum_loss  = sum(losses)  # negative
    pf        = sum_wins / abs(sum_loss) if sum_loss < 0 else float("inf")
    expectancy = (win_rate / 100.0 * avg_win) + ((1.0 - win_rate / 100.0) * avg_loss)

    # ── Duration ─────────────────────────────────────────────────────────────
    t_start   = trades[0].entry_date
    t_end     = trades[-1].exit_date
    years     = max((t_end - t_start).days / 365.25, 0.1)
    ann_return = pl_pct / years

    # ── Calmar ratio (primary ranking) ───────────────────────────────────────
    # Higher = better.  Penalise near-zero DD to avoid INF.
    calmar = ann_return / max(max_dd, 0.1)

    # ── Per-trade Sharpe (trade-based, not time-based) ────────────────────────
    if n_trades >= 2:
        mu    = float(np.mean(percs))
        sigma = float(np.std(percs, ddof=1))
        sharpe_trade = mu / sigma if sigma > 0 else 0.0
    else:
        sharpe_trade = 0.0

    # ── SL stats ─────────────────────────────────────────────────────────────
    sl_hits = sum(1 for t in trades if t.exit_type == "SL")

    # ── Liquidation risk flag ────────────────────────────────────────────────
    # MaxDD >= 80% is effectively game-over territory for leveraged trading
    liq_risk = max_dd >= 80.0

    return {
        **base,
        # Core P/L
        "trades":        n_trades,
        "pl_pct":        round(pl_pct, 2),
        "ann_return":    round(ann_return, 2),
        "end_capital":   round(end_cap, 2),
        # Risk
        "max_dd":        round(max_dd, 2),
        "calmar":        round(calmar, 3),
        "liq_risk":      liq_risk,
        # Quality
        "win_rate":      round(win_rate, 2),
        "profit_factor": round(pf, 3),
        "expectancy":    round(expectancy, 2),
        "sharpe_trade":  round(sharpe_trade, 3),
        # Per-trade stats
        "avg_win":       round(avg_win, 2),
        "avg_loss":      round(avg_loss, 2),
        "max_win":       round(max(percs), 2),
        "max_loss":      round(min(percs), 2),
        "sl_hits":       sl_hits,
        "sl_hit_rate":   round(sl_hits / n_trades * 100, 1) if n_trades else 0,
    }


def _empty_metrics() -> dict:
    return {
        "trades": 0, "pl_pct": 0.0, "ann_return": 0.0, "end_capital": 0.0,
        "max_dd": 0.0, "calmar": 0.0, "liq_risk": False,
        "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0, "sharpe_trade": 0.0,
        "avg_win": 0.0, "avg_loss": 0.0, "max_win": 0.0, "max_loss": 0.0,
        "sl_hits": 0, "sl_hit_rate": 0.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: run strategy + compute metrics in one call
# ─────────────────────────────────────────────────────────────────────────────

def backtest(df, params: AMBParams, period_start: str, period_end: str) -> dict:
    """Run strategy on df and return metrics dict."""
    from .strategy_amb import run_strategy
    trades = run_strategy(df, params)
    return compute_metrics(trades, params, period_start, period_end)

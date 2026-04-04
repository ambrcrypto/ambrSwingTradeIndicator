"""
report.py – Rich terminal output for backtest results.

Tables:
  - Single run trade list
  - Metrics summary
  - Optimization top-N results
  - Cross-period robustness
  - Monte Carlo summary
"""

from __future__ import annotations
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from .strategy_amb import Trade, AMBParams
from .montecarlo import MCResult

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pct_color(val: float, *, good_above: float = 0) -> str:
    if val >= good_above:
        return "green"
    return "red"


def _fmt_pct(val: float, *, good_above: float = 0, decimals: int = 2) -> Text:
    color = _pct_color(val, good_above=good_above)
    sign  = "+" if val >= 0 else ""
    return Text(f"{sign}{val:.{decimals}f}%", style=color)


def _fmt_val(val, decimals: int = 2) -> str:
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


# ─────────────────────────────────────────────────────────────────────────────
# Single-run tables
# ─────────────────────────────────────────────────────────────────────────────

def print_trades(trades: list[Trade], params: AMBParams, ticker: str, period: str) -> None:
    """Print trade-by-trade table."""
    title = f"[bold cyan]Trades – {ticker}  {period}  {params.label()}[/bold cyan]"
    t = Table(title=title, box=box.SIMPLE_HEAD, show_lines=False)
    t.add_column("#",         style="dim",     width=4)
    t.add_column("Entry",     style="white",   width=11)
    t.add_column("Dir",       style="white",   width=5)
    t.add_column("EP",        style="white",   width=10)
    t.add_column("Exit",      style="white",   width=11)
    t.add_column("Type",      style="white",   width=6)
    t.add_column("XP",        style="white",   width=10)
    t.add_column("P/L %",     style="white",   width=9)

    for i, tr in enumerate(trades, 1):
        dir_str  = "[green]LONG[/green]"  if tr.direction == 1 else "[red]SHORT[/red]"
        type_col = "[red]SL[/red]" if tr.exit_type == "SL" else tr.exit_type
        pl_col   = _fmt_pct(tr.pct)
        t.add_row(
            str(i),
            str(tr.entry_date.date()),
            dir_str,
            f"{tr.entry_price:,.2f}",
            str(tr.exit_date.date()),
            type_col,
            f"{tr.exit_price:,.2f}",
            pl_col,
        )
    console.print(t)


def print_metrics(metrics: dict, ticker: str, period: str) -> None:
    """Print metrics summary card."""
    title = (
        f"[bold cyan]Metrics – {ticker}  {period}  "
        f"S{metrics['slow_ma_len']}{metrics['slow_ma_type'][0]}"
        f"/F{metrics['fast_ma_len']}{metrics['fast_ma_type'][0]}"
        f"  L{metrics['leverage_long']}x/{metrics['leverage_short']}x[/bold cyan]"
    )
    t = Table(title=title, box=box.ROUNDED, show_header=False, padding=(0, 2))
    t.add_column("Metric", style="dim cyan", width=18)
    t.add_column("Value",  style="white",    width=12)
    t.add_column("Metric", style="dim cyan", width=18)
    t.add_column("Value",  style="white",    width=12)

    rows = [
        ("Trades",        str(metrics["trades"]),
         "Win Rate",      f"{metrics['win_rate']:.1f}%"),
        ("P/L",           _fmt_pct(metrics["pl_pct"]),
         "Profit Factor", _fmt_val(metrics["profit_factor"])),
        ("Ann. Return",   _fmt_pct(metrics["ann_return"]),
         "Expectancy",    _fmt_pct(metrics["expectancy"])),
        ("Max DD",        _fmt_pct(-metrics["max_dd"], good_above=1),
         "Sharpe (trade)",_fmt_val(metrics["sharpe_trade"])),
        ("Calmar",        Text(f"{metrics['calmar']:.3f}",
                               style="bold green" if metrics["calmar"] > 5 else "yellow"),
         "SL Hits",       f"{metrics['sl_hits']}  ({metrics['sl_hit_rate']:.0f}%)"),
        ("Avg Win",       _fmt_pct(metrics["avg_win"]),
         "Avg Loss",      _fmt_pct(metrics["avg_loss"])),
        ("Max Win",       _fmt_pct(metrics["max_win"]),
         "Max Loss",      _fmt_pct(metrics["max_loss"])),
        ("End Capital",   f"${metrics['end_capital']:,.2f}",
         "Liq Risk",      Text("⚠ YES", style="bold red") if metrics["liq_risk"]
                          else Text("NO",  style="green")),
    ]
    for r in rows:
        t.add_row(*[str(x) if not isinstance(x, Text) else x for x in r])
    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Optimization results table
# ─────────────────────────────────────────────────────────────────────────────

def print_top_results(
    results:  list[dict],
    ticker:   str,
    period:   str,
    top_n:    int = 15,
    sort_by:  str = "calmar",
) -> None:
    """Print top-N optimization results."""
    rows = [r for r in results if not r.get("liq_risk", False)][:top_n]
    if not rows:
        console.print(f"[yellow]No valid results for {ticker} / {period}[/yellow]")
        return

    title = (
        f"[bold cyan]Top {len(rows)} results – {ticker}  {period}"
        f"  (sorted by {sort_by})[/bold cyan]"
    )
    t = Table(title=title, box=box.SIMPLE_HEAD, show_lines=False)

    t.add_column("#",      style="dim",   width=3)
    t.add_column("SlowMA", width=8)
    t.add_column("FastMA", width=8)
    t.add_column("LevL",   width=5)
    t.add_column("LevS",   width=5)
    t.add_column("SL",     width=6)
    t.add_column("Shrt",   width=5)
    t.add_column("Trades", width=7, justify="right")
    t.add_column("P/L%",   width=9,  justify="right")
    t.add_column("AnnRet", width=8,  justify="right")
    t.add_column("MaxDD",  width=8,  justify="right")
    t.add_column("Calmar", width=8,  justify="right")
    t.add_column("Win%",   width=7,  justify="right")
    t.add_column("PF",     width=6,  justify="right")
    t.add_column("Exp%",   width=7,  justify="right")

    for i, r in enumerate(rows, 1):
        sl_str = f"{r['sl_risk_pct']:.0f}%" if r["sl_enable"] else "off"
        calmar_v = float(r["calmar"])
        calmar_txt = Text(
            f"{calmar_v:.2f}",
            style="bold green" if calmar_v > 10 else ("green" if calmar_v > 5 else "yellow")
        )
        t.add_row(
            str(i),
            f"{r['slow_ma_len']}{r['slow_ma_type'][0]}",
            f"{r['fast_ma_len']}{r['fast_ma_type'][0]}",
            str(r["leverage_long"]),
            str(r["leverage_short"]),
            sl_str,
            "Y" if r["allow_shorts"] else "N",
            str(r["trades"]),
            _fmt_pct(float(r["pl_pct"])),
            _fmt_pct(float(r["ann_return"])),
            Text(f"-{float(r['max_dd']):.1f}%", style="red"),
            calmar_txt,
            f"{float(r['win_rate']):.1f}%",
            f"{float(r['profit_factor']):.2f}",
            _fmt_pct(float(r["expectancy"])),
        )
    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Cross-period robustness table
# ─────────────────────────────────────────────────────────────────────────────

def print_cross_period(
    period_results: dict[str, dict],
    ticker:  str,
    params:  AMBParams,
) -> None:
    """Show how one param set performs across all periods."""
    title = f"[bold cyan]Cross-Period Robustness – {ticker}  {params.label()}[/bold cyan]"
    t = Table(title=title, box=box.SIMPLE_HEAD)
    t.add_column("Period",   width=22)
    t.add_column("Dates",    width=24)
    t.add_column("Trades",   width=7,  justify="right")
    t.add_column("P/L%",     width=9,  justify="right")
    t.add_column("MaxDD",    width=8,  justify="right")
    t.add_column("Calmar",   width=8,  justify="right")
    t.add_column("Win%",     width=7,  justify="right")
    t.add_column("SL hits",  width=7,  justify="right")

    for pname, m in period_results.items():
        liq = m.get("liq_risk", False)
        row_style = "bold red" if liq else ""
        t.add_row(
            pname,
            f"{m['period_start']} -> {m['period_end']}",
            str(m["trades"]),
            _fmt_pct(float(m["pl_pct"])),
            Text(f"-{float(m['max_dd']):.1f}%", style="red"),
            Text(f"{float(m['calmar']):.2f}", style="green" if float(m['calmar']) > 5 else "yellow"),
            f"{float(m['win_rate']):.1f}%",
            str(m["sl_hits"]),
            style=row_style,
        )
    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo summary
# ─────────────────────────────────────────────────────────────────────────────

def print_montecarlo(mc: MCResult, ticker: str, params: AMBParams) -> None:
    title = (
        f"[bold cyan]Monte Carlo – {ticker}  {params.label()}"
        f"  ({mc.n_simulations} sims, {mc.n_trades} trades)[/bold cyan]"
    )
    t = Table(title=title, box=box.ROUNDED, show_header=True)
    t.add_column("Metric",      style="dim cyan", width=20)
    t.add_column("p5",    justify="right", width=10)
    t.add_column("p25",   justify="right", width=10)
    t.add_column("p50",   justify="right", width=10)
    t.add_column("p75",   justify="right", width=10)
    t.add_column("p95",   justify="right", width=10)
    t.add_column("Original",    justify="right", width=12)

    t.add_row(
        "P/L %",
        _fmt_pct(mc.pl_p5), _fmt_pct(mc.pl_p25), _fmt_pct(mc.pl_p50),
        _fmt_pct(mc.pl_p75), _fmt_pct(mc.pl_p95),
        _fmt_pct(mc.original_pl),
    )
    t.add_row(
        "Max DD %",
        Text(f"-{mc.dd_p5:.1f}%",  style="red"),
        Text("—", style="dim"),
        Text(f"-{mc.dd_p50:.1f}%", style="red"),
        Text(f"-{mc.dd_p75:.1f}%", style="red"),
        Text(f"-{mc.dd_p95:.1f}%", style="bold red"),
        Text(f"-{mc.original_dd:.1f}%", style="red"),
    )
    t.add_row(
        "Calmar",
        Text("—", style="dim"), Text("—", style="dim"),
        Text(f"{mc.calmar_p50:.2f}", style="green"),
        Text("—", style="dim"),
        Text(f"{mc.calmar_p95:.2f}", style="bold green"),
        Text("—", style="dim"),
    )

    console.print(t)
    console.print(
        f"  Prob Profit:    [{'green' if mc.prob_profit > 50 else 'red'}]"
        f"{mc.prob_profit:.1f}%[/]\n"
        f"  Prob Liq Risk:  [{'red' if mc.prob_liq_risk > 10 else 'green'}]"
        f"{mc.prob_liq_risk:.1f}%[/]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Multi-ticker summary
# ─────────────────────────────────────────────────────────────────────────────

def print_best_summary(
    all_results: dict[str, dict[str, list[dict]]],
    sort_by: str = "calmar",
) -> None:
    """Print one-line best result per ticker/period."""
    title = f"[bold cyan]Best Results Summary (sorted by {sort_by})[/bold cyan]"
    t = Table(title=title, box=box.SIMPLE_HEAD)
    t.add_column("Ticker",  width=8)
    t.add_column("Period",  width=22)
    t.add_column("Params",  width=32)
    t.add_column("P/L%",    width=9,  justify="right")
    t.add_column("MaxDD",   width=8,  justify="right")
    t.add_column("Calmar",  width=8,  justify="right")
    t.add_column("Trades",  width=7,  justify="right")

    for ticker, periods in all_results.items():
        for pname, rows in periods.items():
            if not rows:
                continue
            r   = rows[0]
            sl  = f"SL{r['sl_risk_pct']:.0f}%" if r["sl_enable"] else "noSL"
            lbl = (
                f"S{r['slow_ma_len']}{r['slow_ma_type'][0]}"
                f"/F{r['fast_ma_len']}{r['fast_ma_type'][0]}"
                f" L{r['leverage_long']}x/{r['leverage_short']}x {sl}"
            )
            t.add_row(
                ticker,
                pname,
                lbl,
                _fmt_pct(float(r["pl_pct"])),
                Text(f"-{float(r['max_dd']):.1f}%", style="red"),
                Text(f"{float(r['calmar']):.2f}", style="bold green" if float(r['calmar']) > 10 else "green"),
                str(r["trades"]),
            )
    console.print(t)

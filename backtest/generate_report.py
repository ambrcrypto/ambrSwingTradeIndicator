"""
generate_report.py – Erzeugt einen selbst-enthaltenen HTML-Report für Rolling-Optimize-Ergebnisse.

Kann standalone aufgerufen werden:
    python -m backtest.generate_report --prefix APRIL_ROLLING_BTCUSDT_bybit_20260614_153248

Oder wird automatisch am Ende von run_april_rolling_optimize aufgerufen.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


# ─────────────────────────────────────────────────────────────────────────────
# CSV helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(row: dict, key: str, default=0.0) -> float:
    try:
        return float(row.get(key, default))
    except (ValueError, TypeError):
        return float(default)


def _s(row: dict, key: str, default="") -> str:
    return str(row.get(key, default))


# ─────────────────────────────────────────────────────────────────────────────
# Data preparation
# ─────────────────────────────────────────────────────────────────────────────

def _prepare_data(
    coarse_all: list[dict],
    fine_best: list[dict],
    ls_checks: list[dict],
) -> dict:
    # Sort fine_best by anchor_year
    fine_sorted = sorted(fine_best, key=lambda r: _s(r, "anchor_year"))

    windows    = [_s(r, "anchor_year") for r in fine_sorted]
    pnl        = [round(_f(r, "pl_pct"), 2) for r in fine_sorted]
    max_dd     = [round(_f(r, "max_dd"), 2) for r in fine_sorted]
    slow_lens  = [int(_f(r, "slow_ma_len")) for r in fine_sorted]
    fast_lens  = [int(_f(r, "fast_ma_len")) for r in fine_sorted]
    lev_long   = [round(_f(r, "leverage_long"), 2) for r in fine_sorted]
    lev_short  = [round(_f(r, "leverage_short"), 2) for r in fine_sorted]
    sl_pct     = [round(_f(r, "sl_risk_pct"), 2) for r in fine_sorted]
    win_rate   = [round(_f(r, "win_rate"), 2) for r in fine_sorted]
    expectancy = [round(_f(r, "expectancy"), 2) for r in fine_sorted]
    ma_labels  = [
        f"{_s(r,'slow_ma_type')}{int(_f(r,'slow_ma_len'))} / {_s(r,'fast_ma_type')}{int(_f(r,'fast_ma_len'))}"
        for r in fine_sorted
    ]

    # MA-Type dominance: count wins per type-combo from coarse_all, per window
    # Group by anchor_year, then count which slow_ma_type+fast_ma_type combo
    # has the highest average pl_pct
    type_wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in coarse_all:
        year = _s(r, "anchor_year")
        combo = f"{_s(r,'slow_ma_type')}×{_s(r,'fast_ma_type')}"
        type_wins[year][combo] += 1  # count combos (all have same count, so rank instead)

    # Better: average pl_pct per type-combo per year
    type_pnl_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    type_pnl_cnt: dict[str, dict[str, int]]   = defaultdict(lambda: defaultdict(int))
    for r in coarse_all:
        year  = _s(r, "anchor_year")
        combo = f"{_s(r,'slow_ma_type')}×{_s(r,'fast_ma_type')}"
        type_pnl_sum[year][combo] += _f(r, "pl_pct")
        type_pnl_cnt[year][combo] += 1

    all_combos = sorted({
        f"{_s(r,'slow_ma_type')}×{_s(r,'fast_ma_type')}"
        for r in coarse_all
    })
    type_avg: dict[str, list[float]] = {combo: [] for combo in all_combos}
    for year in windows:
        for combo in all_combos:
            cnt = type_pnl_cnt[year].get(combo, 0)
            s   = type_pnl_sum[year].get(combo, 0.0)
            type_avg[combo].append(round(s / cnt, 2) if cnt else 0.0)

    # Scatter: pl_pct vs max_dd for all coarse combos (sampled to max 2000 pts)
    scatter_pts = []
    for i, r in enumerate(coarse_all):
        scatter_pts.append({
            "x": round(_f(r, "max_dd"), 2),
            "y": round(_f(r, "pl_pct"), 2),
            "year": _s(r, "anchor_year"),
            "ma": f"{_s(r,'slow_ma_type')}{int(_f(r,'slow_ma_len'))}/{_s(r,'fast_ma_type')}{int(_f(r,'fast_ma_len'))}",
        })
    # Sample if too large (keep 3000 max for performance)
    if len(scatter_pts) > 3000:
        step = len(scatter_pts) // 3000
        scatter_pts = scatter_pts[::step]

    # Long+Short vs Long-Only
    ls_windows   = [_s(r, "window_end")[:4] for r in ls_checks]
    ls_both      = [round(_f(r, "best_pl_long_short"), 2) for r in ls_checks]
    ls_long_only = [round(_f(r, "same_params_long_only_pl"), 2) for r in ls_checks]

    # Fine best table rows (all fields)
    table_rows = fine_sorted

    return {
        "windows": windows,
        "pnl": pnl,
        "max_dd": max_dd,
        "slow_lens": slow_lens,
        "fast_lens": fast_lens,
        "lev_long": lev_long,
        "lev_short": lev_short,
        "sl_pct": sl_pct,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "ma_labels": ma_labels,
        "all_combos": all_combos,
        "type_avg": type_avg,
        "scatter_pts": scatter_pts,
        "ls_windows": ls_windows,
        "ls_both": ls_both,
        "ls_long_only": ls_long_only,
        "table_rows": table_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HTML generation
# ─────────────────────────────────────────────────────────────────────────────

_COMBO_COLORS = {
    "SMA×SMA": "#3b82f6",
    "EMA×SMA": "#f59e0b",
    "SMA×EMA": "#10b981",
    "EMA×EMA": "#ef4444",
}

def _combo_color(combo: str) -> str:
    return _COMBO_COLORS.get(combo, "#8b5cf6")


def generate_html_report(
    path_coarse_all: Path,
    path_fine_best: Path,
    path_ls: Path,
    path_out: Path,
    ticker: str = "BTCUSDT",
    source: str = "bybit",
    metric: str = "pl_pct",
) -> None:
    coarse_all = _read_csv(path_coarse_all)
    fine_best  = _read_csv(path_fine_best)
    ls_checks  = _read_csv(path_ls)

    if not fine_best:
        path_out.write_text("<html><body>No data yet.</body></html>", encoding="utf-8")
        return

    d = _prepare_data(coarse_all, fine_best, ls_checks)

    # Build type_avg datasets for Chart.js
    type_datasets_json = json.dumps([
        {
            "label": combo,
            "data": d["type_avg"][combo],
            "backgroundColor": _combo_color(combo),
            "borderColor": _combo_color(combo),
            "borderWidth": 2,
            "fill": False,
            "tension": 0.3,
        }
        for combo in d["all_combos"]
    ])

    # Table HTML
    table_fields = [
        "anchor_year", "slow_ma_type", "slow_ma_len", "fast_ma_type", "fast_ma_len",
        "leverage_long", "leverage_short", "sl_risk_pct",
        "pl_pct", "max_dd", "win_rate", "expectancy", "profit_factor",
        "trades", "sl_hit_rate",
    ]
    table_header = "".join(f"<th>{f}</th>" for f in table_fields)
    table_body = ""
    for r in d["table_rows"]:
        pnl_val = _f(r, "pl_pct")
        color = "#22c55e" if pnl_val >= 0 else "#ef4444"
        cells = ""
        for f in table_fields:
            v = r.get(f, "")
            try:
                v = round(float(v), 2)
            except (ValueError, TypeError):
                pass
            style = f' style="color:{color};font-weight:bold"' if f == "pl_pct" else ""
            cells += f"<td{style}>{v}</td>"
        table_body += f"<tr>{cells}</tr>"

    # Scatter color map per year
    year_colors = ["#3b82f6","#f59e0b","#10b981","#ef4444","#8b5cf6","#ec4899","#14b8a6","#f97316"]
    unique_years = sorted({p["year"] for p in d["scatter_pts"]})
    year_color_map = {y: year_colors[i % len(year_colors)] for i, y in enumerate(unique_years)}

    scatter_datasets_json = json.dumps([
        {
            "label": f"Fenster {yr}",
            "data": [{"x": p["x"], "y": p["y"]} for p in d["scatter_pts"] if p["year"] == yr],
            "backgroundColor": year_color_map[yr] + "55",
            "pointRadius": 2,
        }
        for yr in unique_years
    ])

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AMB Rolling Optimize – {ticker} {source}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f172a; color: #e2e8f0; font-family: system-ui, sans-serif; padding: 24px; }}
  h1 {{ font-size: 1.5rem; color: #f8fafc; margin-bottom: 4px; }}
  .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 32px; }}
  h2 {{ font-size: 1rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em;
        margin: 32px 0 12px; border-bottom: 1px solid #1e293b; padding-bottom: 6px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 16px; }}
  .chart-wrap {{ position: relative; height: 280px; }}
  .chart-wrap-tall {{ position: relative; height: 340px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; margin-top: 8px; }}
  th {{ background: #0f172a; color: #64748b; text-transform: uppercase;
        font-size: 0.7rem; letter-spacing:.04em; padding: 6px 8px; text-align: left; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #1e293b; }}
  tr:hover td {{ background: #1e293b; }}
  .tag {{ display:inline-block; background:#3b82f620; color:#93c5fd;
          border: 1px solid #3b82f640; border-radius:4px; padding:1px 6px; font-size:0.75rem; }}
  @media(max-width:900px) {{ .grid-2, .grid-3 {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>AMB Rolling Optimize — {ticker} [{source}]</h1>
<p class="subtitle">Metrik: <strong>{metric}</strong> · Rollierende 1-Apr-Fenster · 07:00 Europe/Zurich</p>

<h2>Beste Parameter je Fenster (Fine Stage)</h2>
<div class="grid-2">
  <div class="card"><div class="chart-wrap">
    <canvas id="chartPnl"></canvas>
  </div></div>
  <div class="card"><div class="chart-wrap">
    <canvas id="chartDD"></canvas>
  </div></div>
</div>

<h2>Parameter-Drift über Zeit</h2>
<div class="grid-3">
  <div class="card"><div class="chart-wrap">
    <canvas id="chartSlowLen"></canvas>
  </div></div>
  <div class="card"><div class="chart-wrap">
    <canvas id="chartFastLen"></canvas>
  </div></div>
  <div class="card"><div class="chart-wrap">
    <canvas id="chartSL"></canvas>
  </div></div>
</div>
<div class="grid-2">
  <div class="card"><div class="chart-wrap">
    <canvas id="chartLevLong"></canvas>
  </div></div>
  <div class="card"><div class="chart-wrap">
    <canvas id="chartLevShort"></canvas>
  </div></div>
</div>

<h2>MA-Typ Dominanz (Ø PnL% nach Typ-Kombination, Coarse)</h2>
<div class="card"><div class="chart-wrap-tall">
  <canvas id="chartMaType"></canvas>
</div></div>

<h2>Long+Short vs Long-Only (gleiche Parameter)</h2>
<div class="card"><div class="chart-wrap">
  <canvas id="chartLS"></canvas>
</div></div>

<h2>PnL% vs MaxDD – alle Coarse-Kombinationen</h2>
<p style="color:#64748b;font-size:0.8rem;margin-bottom:8px">Je weiter rechts, desto höher der Drawdown. Je weiter oben, desto höher der Gewinn. Ideal: oben-links.</p>
<div class="card"><div class="chart-wrap-tall">
  <canvas id="chartScatter"></canvas>
</div></div>

<h2>Detailtabelle – Beste Parameter je Fenster</h2>
<div class="card" style="overflow-x:auto">
<table>
  <thead><tr>{table_header}</tr></thead>
  <tbody>{table_body}</tbody>
</table>
</div>

<script>
const W = {json.dumps(d["windows"])};
const chartDefaults = {{
  responsive: true, maintainAspectRatio: false,
  plugins: {{ legend: {{ labels: {{ color: "#94a3b8", boxWidth: 12 }} }} }},
  scales: {{
    x: {{ ticks: {{ color: "#64748b" }}, grid: {{ color: "#1e293b" }} }},
    y: {{ ticks: {{ color: "#64748b" }}, grid: {{ color: "#1e293b" }} }},
  }}
}};

function barChart(id, label, data, color) {{
  new Chart(document.getElementById(id), {{
    type: "bar",
    data: {{ labels: W, datasets: [{{ label, data, backgroundColor: color+"99", borderColor: color, borderWidth: 1 }}] }},
    options: {{ ...chartDefaults, plugins: {{ ...chartDefaults.plugins, title: {{ display: true, text: label, color: "#e2e8f0" }} }} }}
  }});
}}

function lineChart(id, label, data, color) {{
  new Chart(document.getElementById(id), {{
    type: "line",
    data: {{ labels: W, datasets: [{{ label, data, borderColor: color, backgroundColor: color+"22", fill: true, tension: 0.3, pointRadius: 4 }}] }},
    options: {{ ...chartDefaults, plugins: {{ ...chartDefaults.plugins, title: {{ display: true, text: label, color: "#e2e8f0" }} }} }}
  }});
}}

barChart("chartPnl",     "PnL % (Fine Best)",   {json.dumps(d["pnl"])},      "#22c55e");
barChart("chartDD",      "Max Drawdown %",       {json.dumps(d["max_dd"])},   "#ef4444");
lineChart("chartSlowLen","Slow MA Länge",         {json.dumps(d["slow_lens"])},"#f59e0b");
lineChart("chartFastLen","Fast MA Länge",         {json.dumps(d["fast_lens"])},"#3b82f6");
lineChart("chartSL",     "Stop Loss %",           {json.dumps(d["sl_pct"])},  "#ec4899");
lineChart("chartLevLong","Leverage Long",         {json.dumps(d["lev_long"])}, "#10b981");
lineChart("chartLevShort","Leverage Short",       {json.dumps(d["lev_short"])},"#8b5cf6");

// MA-Type dominance
new Chart(document.getElementById("chartMaType"), {{
  type: "line",
  data: {{ labels: W, datasets: {type_datasets_json} }},
  options: {{
    ...chartDefaults,
    plugins: {{ ...chartDefaults.plugins,
      title: {{ display: true, text: "Ø PnL% nach MA-Typ-Kombo (SlowType×FastType)", color: "#e2e8f0" }},
      legend: {{ display: true, labels: {{ color: "#94a3b8" }} }}
    }}
  }}
}});

// Long+Short vs Long-Only
new Chart(document.getElementById("chartLS"), {{
  type: "bar",
  data: {{
    labels: {json.dumps(d["ls_windows"])},
    datasets: [
      {{ label: "Long+Short", data: {json.dumps(d["ls_both"])},      backgroundColor: "#3b82f699", borderColor: "#3b82f6", borderWidth: 1 }},
      {{ label: "Long-Only",  data: {json.dumps(d["ls_long_only"])}, backgroundColor: "#f59e0b99", borderColor: "#f59e0b", borderWidth: 1 }},
    ]
  }},
  options: {{ ...chartDefaults, plugins: {{ ...chartDefaults.plugins, title: {{ display: true, text: "PnL%: Long+Short vs Long-Only", color: "#e2e8f0" }} }} }}
}});

// Scatter
new Chart(document.getElementById("chartScatter"), {{
  type: "scatter",
  data: {{ datasets: {scatter_datasets_json} }},
  options: {{
    ...chartDefaults,
    plugins: {{ ...chartDefaults.plugins,
      title: {{ display: true, text: "PnL% vs MaxDD (alle Coarse-Kombis)", color: "#e2e8f0" }},
      tooltip: {{ callbacks: {{ label: ctx => `${{ctx.raw.x.toFixed(1)}}% DD / ${{ctx.raw.y.toFixed(1)}}% PnL` }} }}
    }},
    scales: {{
      x: {{ title: {{ display: true, text: "Max Drawdown %", color: "#64748b" }}, ticks: {{ color: "#64748b" }}, grid: {{ color: "#1e293b" }} }},
      y: {{ title: {{ display: true, text: "PnL %", color: "#64748b" }}, ticks: {{ color: "#64748b" }}, grid: {{ color: "#1e293b" }} }},
    }}
  }}
}});
</script>
</body>
</html>"""

    path_out.write_text(html, encoding="utf-8")
    print(f"HTML Report: {path_out}")


# ─────────────────────────────────────────────────────────────────────────────
# Standalone CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Generiert HTML-Report für Rolling-Optimize-Ergebnisse")
    ap.add_argument("--prefix", required=True, help="Dateinamen-Präfix, z.B. APRIL_ROLLING_BTCUSDT_bybit_20260614_153248")
    ap.add_argument("--out", default=None, help="Ausgabe-HTML-Pfad (optional)")
    args = ap.parse_args()

    prefix = args.prefix
    path_coarse_all = RESULTS_DIR / f"{prefix}_coarse_all.csv"
    path_fine_best  = RESULTS_DIR / f"{prefix}_fine_best.csv"
    path_ls         = RESULTS_DIR / f"{prefix}_longshort_check.csv"
    path_out        = Path(args.out) if args.out else RESULTS_DIR / f"{prefix}_report.html"

    # Parse metadata from prefix
    parts = prefix.split("_")
    ticker = parts[2] if len(parts) > 2 else "BTCUSDT"
    source = parts[3] if len(parts) > 3 else "bybit"

    generate_html_report(
        path_coarse_all=path_coarse_all,
        path_fine_best=path_fine_best,
        path_ls=path_ls,
        path_out=path_out,
        ticker=ticker,
        source=source,
    )


if __name__ == "__main__":
    main()

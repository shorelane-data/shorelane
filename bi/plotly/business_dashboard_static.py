"""
Static export of the executive dashboard — same five charts and KPI cards as
the Dash app (bi/plotly/business_dashboard.py), rendered to one self-contained
HTML file for the public Pages site. Interactivity that needed a server
(the period dropdown) becomes pre-rendered sections behind a pure-JS switcher;
everything else (hover, zoom, legend toggles) is Plotly client-side as usual.

    python -m bi.plotly.business_dashboard_static                 # as-of today
    python -m bi.plotly.business_dashboard_static --as-of full    # full fixture

With an as-of date the tables pass through the arrival rule
(loaders/visibility.py) and periods anchor to the last fully-elapsed month, so
the page shows exactly what the live warehouse sees (the parity property) —
no credentials involved.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd
import plotly.io as pio
from plotly.offline import get_plotlyjs

import config
from bi import dashboard_data as dd
from bi.plotly import figures as fg
from loaders.visibility import visible_tables

FIG_CONFIG = {"displayModeBar": False, "responsive": True}


def last_elapsed_month(as_of: pd.Timestamp) -> pd.Timestamp:
    """Month-start of the last fully-elapsed month at as_of (ground-truth
    windows must never straddle the as-of date)."""
    m = as_of.to_period("M").to_timestamp()
    return m if as_of >= m + pd.offsets.MonthEnd(0) else m - pd.DateOffset(months=1)


def kpi_card(label: str, value: str, sub: str, delta_html: str) -> str:
    return (
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div>{delta_html}</div>'
    )


def delta_html(cur: float, prev: float | None, good_up: bool = True) -> str:
    if prev is None or prev == 0:
        return ""
    pct = (cur - prev) / abs(prev)
    positive = pct >= 0
    good = positive if good_up else not positive
    arrow = "▲" if positive else "▼"
    color = fg.GREEN if good else fg.RED
    return f'<div class="kpi-delta" style="color:{color}">{arrow} {abs(pct) * 100:.1f}% vs prior</div>'


def kpi_row(cur: dict, prev: dict | None) -> str:
    g = lambda k: (prev[k] if prev else None)
    return "".join([
        kpi_card("Revenue", fg.fmt_money(cur["recognized_revenue"]), "Recognized · GAAP",
                 delta_html(cur["recognized_revenue"], g("recognized_revenue"))),
        kpi_card("GMV", fg.fmt_money(cur["gmv"]), "Gross merchandise value",
                 delta_html(cur["gmv"], g("gmv"))),
        kpi_card("Active Customers", fg.fmt_int(cur["active_customers"]), "Ordered in period",
                 delta_html(cur["active_customers"], g("active_customers"))),
        kpi_card("New Customers", fg.fmt_int(cur["new_customers"]), "First order in period",
                 delta_html(cur["new_customers"], g("new_customers"))),
        kpi_card("Avg Order Value", fg.fmt_money(cur["aov"]), "GMV ÷ orders",
                 delta_html(cur["aov"], g("aov"))),
        kpi_card("Refund Rate", fg.fmt_pct(cur["refund_rate"]), "Refunds ÷ GMV",
                 delta_html(cur["refund_rate"], g("refund_rate"), good_up=False)),
    ])


def chart_card(title: str, fig, width: str) -> str:
    body = pio.to_html(fig, include_plotlyjs=False, full_html=False, config=FIG_CONFIG)
    return (
        f'<div class="chart-card" style="flex:1 1 {width}">'
        f'<div class="chart-title">{title}</div>{body}</div>'
    )


def period_section(tables, monthly: pd.DataFrame, period: str, end_month: pd.Timestamp, active: bool) -> str:
    start, end, months = dd.period_bounds(period, end_month)
    df = monthly[(monthly.month >= start) & (monthly.month <= end)]
    cur = dd.kpis(tables, start, end)
    pb = dd.prior_bounds(start, months)
    prev = dd.kpis(tables, pb[0], pb[1]) if pb else None

    ctx = (
        f'Showing <b>{start.strftime("%b %Y")} – {end.strftime("%b %Y")}</b> &nbsp;·&nbsp; '
        f'<b>{fg.fmt_money(cur["recognized_revenue"])}</b> recognized revenue'
    )
    charts = "".join([
        chart_card("Recognized Revenue by Month", fg.fig_revenue(df), "100%"),
        chart_card("Revenue by Channel", fg.fig_channel(tables, start, end), "300px"),
        chart_card("Customer Growth", fg.fig_customers(df), "420px"),
        chart_card("Orders & Average Order Value", fg.fig_orders_aov(df), "420px"),
        chart_card("Recognized Revenue vs Collected Cash", fg.fig_cash_health(df), "420px"),
    ])
    display = "block" if active else "none"
    return (
        f'<div class="period-section" id="sec-{period.replace(" ", "-")}" style="display:{display}">'
        f'<div class="ctx">{ctx}</div>'
        f'<div class="kpi-row">{kpi_row(cur, prev)}</div>'
        f'<div class="charts">{charts}</div></div>'
    )


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shorelane Commerce — Executive Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:'Inter',-apple-system,sans-serif; background:#f1f5f9; color:#0f172a; }}
  .topbar {{ background:#0f172a; color:#fff; padding:16px 28px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; }}
  .brand {{ display:flex; align-items:center; gap:12px; }}
  .brand .logo {{ font-size:22px; }}
  .brand h1 {{ font-size:18px; font-weight:700; margin:0; letter-spacing:-0.01em; }}
  .brand .sub {{ font-size:12px; color:#94a3b8; margin-top:2px; }}
  .badge {{ background:#1e293b; color:#38bdf8; font-size:11px; font-weight:600; padding:5px 10px; border-radius:999px; border:1px solid #334155; }}
  .controls {{ display:flex; align-items:center; justify-content:flex-end; gap:8px; padding:18px 28px 6px; flex-wrap:wrap; }}
  .controls .plabel {{ font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; margin-right:4px; }}
  .pbtn {{ font:inherit; font-size:13px; font-weight:600; padding:7px 14px; border-radius:8px; border:1px solid #e2e8f0; background:#fff; color:#475569; cursor:pointer; }}
  .pbtn.active {{ background:#2563eb; border-color:#2563eb; color:#fff; }}
  .ctx {{ font-size:13px; color:#475569; padding:4px 28px 0; }}
  .ctx b {{ color:#0f172a; }}
  .kpi-row {{ display:flex; flex-wrap:wrap; gap:16px; padding:14px 28px; }}
  .kpi-card {{ flex:1 1 160px; background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,0.04); }}
  .kpi-label {{ font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; }}
  .kpi-value {{ font-size:28px; font-weight:700; margin-top:6px; letter-spacing:-0.02em; }}
  .kpi-sub {{ font-size:11px; color:#94a3b8; margin-top:2px; }}
  .kpi-delta {{ font-size:12px; font-weight:600; margin-top:8px; }}
  .charts {{ display:flex; flex-wrap:wrap; gap:16px; padding:6px 28px 32px; }}
  .chart-card {{ background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,0.04); min-width:340px; overflow:hidden; }}
  .chart-title {{ font-size:14px; font-weight:600; color:#0f172a; margin-bottom:6px; }}
  .footer {{ padding:0 28px 28px; font-size:11px; color:#94a3b8; }}
  .footer a {{ color:#64748b; }}
</style>
<script>{plotlyjs}</script>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <div class="logo">🌊</div>
    <div><h1>Shorelane Commerce</h1><div class="sub">Executive Revenue Dashboard</div></div>
  </div>
  <div class="badge">● Revenue · Recognized (GAAP){asof_badge}</div>
</div>
<div class="controls">
  <span class="plabel">Period</span>
  {buttons}
</div>
{sections}
<div class="footer">{footer}</div>
<script>
function showPeriod(id, btn) {{
  document.querySelectorAll('.period-section').forEach(function(s) {{ s.style.display = 'none'; }});
  document.querySelectorAll('.pbtn').forEach(function(b) {{ b.classList.remove('active'); }});
  document.getElementById(id).style.display = 'block';
  btn.classList.add('active');
  window.dispatchEvent(new Event('resize'));
}}
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default="today", metavar="YYYY-MM-DD",
                    help='live-warehouse view date; "today" (default) or "full" for the whole fixture')
    ap.add_argument("--out", default=os.path.join("bi", "plotly", "business_dashboard.html"),
                    help="output HTML path")
    args = ap.parse_args()

    tables = dd.load_tables()
    as_of = None
    if args.as_of != "full":
        as_of = pd.Timestamp.now().normalize() if args.as_of == "today" else pd.Timestamp(args.as_of)
        tables = visible_tables(tables, as_of)

    end_month = last_elapsed_month(as_of) if as_of is not None else dd.data_end_month(tables)
    monthly = dd.monthly_metrics(tables)
    monthly = monthly[monthly.month <= end_month]

    periods = list(dd.PERIODS)
    buttons = "".join(
        f'<button class="pbtn{" active" if p == dd.DEFAULT_PERIOD else ""}" '
        f"onclick=\"showPeriod('sec-{p.replace(' ', '-')}', this)\">{p}</button>"
        for p in periods
    )
    sections = "".join(
        period_section(tables, monthly, p, end_month, active=(p == dd.DEFAULT_PERIOD))
        for p in periods
    )

    asof_badge = f" · as of {as_of.date()}" if as_of is not None else ""
    footer = (
        (f"Data as of {as_of.date()}" if as_of is not None else "Full dataset")
        + ' · <a href="../explore.html">About this data</a> · '
        + '<a href="../customers/">Customers</a> · <a href="../marketing/">Marketing</a> · '
        + '<a href="../subscriptions/">Subscriptions</a>'
    )

    html = PAGE.format(
        plotlyjs=get_plotlyjs(),
        asof_badge=asof_badge,
        buttons=buttons,
        sections=sections,
        footer=footer,
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

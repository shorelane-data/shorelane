"""Shared shell for the static Pages dashboards (marketing, subscriptions).

Same look as bi/plotly/business_dashboard_static.py: a topbar, a period switcher
that swaps pre-rendered sections client-side, KPI cards, chart cards, and a
one-line footer. No metric-definition prose on the page on purpose.
"""
from __future__ import annotations

import plotly.io as pio

from bi.plotly.business_dashboard_static import delta_html, kpi_card, last_elapsed_month  # noqa: F401

FIG_CONFIG = {"displayModeBar": False, "responsive": True}

CSS = """
  * { box-sizing: border-box; }
  body { margin:0; font-family:'Inter',-apple-system,sans-serif; background:#f1f5f9; color:#0f172a; }
  .topbar { background:#0f172a; color:#fff; padding:16px 28px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; }
  .brand { display:flex; align-items:center; gap:12px; }
  .brand .logo { font-size:22px; }
  .brand h1 { font-size:18px; font-weight:700; margin:0; letter-spacing:-0.01em; }
  .brand .sub { font-size:12px; color:#94a3b8; margin-top:2px; }
  .badge { background:#1e293b; color:#38bdf8; font-size:11px; font-weight:600; padding:5px 10px; border-radius:999px; border:1px solid #334155; }
  .controls { display:flex; align-items:center; justify-content:flex-end; gap:8px; padding:18px 28px 6px; flex-wrap:wrap; }
  .controls .plabel { font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; margin-right:4px; }
  .pbtn { font:inherit; font-size:13px; font-weight:600; padding:7px 14px; border-radius:8px; border:1px solid #e2e8f0; background:#fff; color:#475569; cursor:pointer; }
  .pbtn.active { background:#2563eb; border-color:#2563eb; color:#fff; }
  .ctx { font-size:13px; color:#475569; padding:4px 28px 0; }
  .ctx b { color:#0f172a; }
  .kpi-row { display:flex; flex-wrap:wrap; gap:16px; padding:14px 28px; }
  .kpi-card { flex:1 1 160px; background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,0.04); }
  .kpi-label { font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; }
  .kpi-value { font-size:28px; font-weight:700; margin-top:6px; letter-spacing:-0.02em; }
  .kpi-sub { font-size:11px; color:#94a3b8; margin-top:2px; }
  .kpi-delta { font-size:12px; font-weight:600; margin-top:8px; }
  .charts { display:flex; flex-wrap:wrap; gap:16px; padding:6px 28px 32px; }
  .chart-card { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,0.04); min-width:340px; overflow:hidden; }
  .chart-title { font-size:14px; font-weight:600; color:#0f172a; margin-bottom:6px; }
  .tbl { width:100%; border-collapse:collapse; font-size:13px; }
  .tbl th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:0.04em; color:#64748b; padding:8px 10px; border-bottom:1px solid #e2e8f0; }
  .tbl td { padding:8px 10px; border-bottom:1px solid #f1f5f9; }
  .tbl td.num, .tbl th.num { text-align:right; font-variant-numeric: tabular-nums; }
  .footer { padding:0 28px 28px; font-size:11px; color:#94a3b8; }
  .footer a { color:#64748b; }
"""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shorelane Commerce — {title}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{css}</style>
<script>{plotlyjs}</script>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <div class="logo">🌊</div>
    <div><h1>Shorelane Commerce</h1><div class="sub">{title}</div></div>
  </div>
  <div class="badge">● {badge}{asof_badge}</div>
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


def chart_card(title: str, fig, width: str) -> str:
    body = pio.to_html(fig, include_plotlyjs=False, full_html=False, config=FIG_CONFIG)
    return f'<div class="chart-card" style="flex:1 1 {width}"><div class="chart-title">{title}</div>{body}</div>'


def table_card(title: str, headers: list[tuple[str, bool]], rows: list[list[str]], width: str) -> str:
    th = "".join(f'<th class="{"num" if num else ""}">{h}</th>' for h, num in headers)
    body = "".join(
        "<tr>" + "".join(f'<td class="{"num" if headers[i][1] else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>"
        for r in rows
    ) or f'<tr><td colspan="{len(headers)}" style="color:#94a3b8">none in window</td></tr>'
    return (f'<div class="chart-card" style="flex:1 1 {width}"><div class="chart-title">{title}</div>'
            f'<table class="tbl"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>')


def period_buttons(periods: list[str], default: str) -> str:
    return "".join(
        f'<button class="pbtn{" active" if p == default else ""}" '
        f"onclick=\"showPeriod('sec-{p.replace(' ', '-')}', this)\">{p}</button>"
        for p in periods
    )


def section(period: str, active: bool, ctx: str, kpi_row_html: str, charts_html: str) -> str:
    display = "block" if active else "none"
    return (f'<div class="period-section" id="sec-{period.replace(" ", "-")}" style="display:{display}">'
            f'<div class="ctx">{ctx}</div><div class="kpi-row">{kpi_row_html}</div>'
            f'<div class="charts">{charts_html}</div></div>')


def footer(as_of, links: list[tuple[str, str]]) -> str:
    return ((f"Data as of {as_of.date()}" if as_of is not None else "Full dataset")
            + "".join(f' · <a href="{href}">{label}</a>' for label, href in links))

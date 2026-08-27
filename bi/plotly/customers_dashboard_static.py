"""
Static export of the customers dashboard for the public Pages site (/customers/).
Same construction as bi/plotly/business_dashboard_static.py: period sections are
pre-rendered behind a pure-JS switcher, plus a channel filter that restyles the
channel-aware charts client-side. All counts come from bi/customers_data.py at
the canonical customer grain; the identity-health section shows the alias-grain
fragmentation the canonical grain protects against.

    python -m bi.plotly.customers_dashboard_static                 # as-of today
    python -m bi.plotly.customers_dashboard_static --as-of full    # full fixture

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
from bi import customers_data as cd
from bi import dashboard_data as dd
from bi.plotly import customer_figures as cf
from bi.plotly import figures as fg
from bi.plotly.business_dashboard_static import delta_html, kpi_card, last_elapsed_month
from loaders.visibility import visible_tables

FIG_CONFIG = {"displayModeBar": False, "responsive": True}


def kpi_row(cur: dict, prev: dict | None) -> str:
    g = lambda k: (prev[k] if prev else None)
    return "".join([
        kpi_card("Current Customers", fg.fmt_int(cur["current_customers"]),
                 "Ordered in trailing 12 mo · dedup",
                 delta_html(cur["current_customers"], g("current_customers"))),
        kpi_card("Current Subscribers", fg.fmt_int(cur["current_subscribers"]),
                 "Active subscription term",
                 delta_html(cur["current_subscribers"], g("current_subscribers"))),
        kpi_card("Active Customers", fg.fmt_int(cur["active_customers"]), "Ordered in period",
                 delta_html(cur["active_customers"], g("active_customers"))),
        kpi_card("New Customers", fg.fmt_int(cur["new_customers"]), "First order in period",
                 delta_html(cur["new_customers"], g("new_customers"))),
        kpi_card("Returning Share", fg.fmt_pct(cur["returning_share"]), "Actives with a prior order",
                 delta_html(cur["returning_share"], g("returning_share"))),
        kpi_card("Multi-Channel", fg.fmt_int(cur["multi_channel_customers"]), "≥2 channels in period",
                 delta_html(cur["multi_channel_customers"], g("multi_channel_customers"))),
    ])


def chart_card(title: str, fig, width: str, channel_aware: bool = False) -> str:
    body = pio.to_html(fig, include_plotlyjs=False, full_html=False, config=FIG_CONFIG)
    cls = "chart-card channel-aware" if channel_aware else "chart-card"
    return (
        f'<div class="{cls}" style="flex:1 1 {width}">'
        f'<div class="chart-title">{title}</div>{body}</div>'
    )


def period_section(tables, monthly: pd.DataFrame, period: str, end_month: pd.Timestamp, active: bool) -> str:
    start, end, months = dd.period_bounds(period, end_month)
    df = monthly[(monthly.month >= start) & (monthly.month <= end)]
    cur = cd.kpis(tables, start, end)
    pb = dd.prior_bounds(start, months)
    prev = cd.kpis(tables, pb[0], pb[1]) if pb else None

    ctx = (
        f'Showing <b>{start.strftime("%b %Y")} – {end.strftime("%b %Y")}</b> &nbsp;·&nbsp; '
        f'<b>{fg.fmt_int(cur["current_customers"])}</b> current customers at window end'
    )
    charts = "".join([
        chart_card("Current Customers by Month", cf.fig_current_customers(df), "100%", channel_aware=True),
        chart_card("Current Customer Mix (at window end)", cf.fig_current_mix(cur), "300px"),
        chart_card("Active Customers by Month & Channel", cf.fig_active_by_channel(df), "420px", channel_aware=True),
        chart_card("New vs Returning Customers", cf.fig_new_returning(df), "420px"),
    ])
    display = "block" if active else "none"
    return (
        f'<div class="period-section" id="sec-{period.replace(" ", "-")}" style="display:{display}">'
        f'<div class="ctx">{ctx}</div>'
        f'<div class="kpi-row">{kpi_row(cur, prev)}</div>'
        f'<div class="charts">{charts}</div></div>'
    )


def identity_section(idq: dict, as_of_label: str) -> str:
    kpis_html = "".join([
        kpi_card("Source Aliases", fg.fmt_int(idq["alias_count"]), "Σ profile rows, 4 systems", ""),
        kpi_card("Resolution Null Rate", fg.fmt_pct(idq["null_rate"]), "Aliases missing a canonical ID", ""),
        kpi_card("Canonical Profiles", fg.fmt_int(idq["canonical_profiles"]), "app_db customers", ""),
        kpi_card("Ever-Ordered Customers", fg.fmt_int(idq["ordered_customers"]), "Canonical, ≥1 order", ""),
        kpi_card("Avg IDs / Customer", f'{idq["avg_source_ids_per_ordered_customer"]:.2f}',
                 "Resolved source IDs per ordered customer", ""),
        kpi_card("Pre-2021 Shopify Unlinked", fg.fmt_int(idq["pre_migration_shopify_missing"]),
                 "Permanent migration gap", ""),
    ])
    charts = "".join([
        chart_card("Source Aliases by Resolution Status",
                   cf.fig_identity_status(idq["by_system"], cd.STATUS_LABELS), "460px"),
        chart_card("Customer Count: Naive vs Canonical", cf.fig_naive_vs_canonical(idq), "460px"),
    ])
    return f"""
<div class="section-head">
  <h2>Identity health <span class="asof">as of {as_of_label}</span></h2>
  <p>Every customer above is counted at the <b>canonical grain</b> (one app_db ID per
  business customer). The same customer holds 2–4 IDs across Stripe, Shopify,
  Salesforce and app_db, and the 2021 migration permanently dropped a slice of the
  Shopify/Salesforce crosswalk — so summing per-system "customers", or inner-joining
  raw source IDs, silently over- or under-counts. See the
  <a href="https://github.com/shorelane-data/shorelane/blob/main/context/guides/customer_identity.md">identity
  resolution guide</a> and <code>dim_customers</code> / <code>fct_identity_resolution_quality</code>.</p>
</div>
<div class="kpi-row">{kpis_html}</div>
<div class="charts">{charts}</div>
"""


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shorelane Commerce — Customers Dashboard</title>
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
  .controls .plabel {{ font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; margin:0 4px 0 12px; }}
  .pbtn {{ font:inherit; font-size:13px; font-weight:600; padding:7px 14px; border-radius:8px; border:1px solid #e2e8f0; background:#fff; color:#475569; cursor:pointer; }}
  .pbtn.active {{ background:#2563eb; border-color:#2563eb; color:#fff; }}
  .cbtn.active {{ background:#0d9488; border-color:#0d9488; color:#fff; }}
  .ctx {{ font-size:13px; color:#475569; padding:4px 28px 0; }}
  .ctx b {{ color:#0f172a; }}
  .defs {{ margin:10px 28px 0; padding:12px 16px; background:#fff; border:1px solid #e2e8f0; border-radius:12px; font-size:12px; color:#475569; line-height:1.55; }}
  .defs b {{ color:#0f172a; }}
  .kpi-row {{ display:flex; flex-wrap:wrap; gap:16px; padding:14px 28px; }}
  .kpi-card {{ flex:1 1 160px; background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,0.04); }}
  .kpi-label {{ font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; }}
  .kpi-value {{ font-size:28px; font-weight:700; margin-top:6px; letter-spacing:-0.02em; }}
  .kpi-sub {{ font-size:11px; color:#94a3b8; margin-top:2px; }}
  .kpi-delta {{ font-size:12px; font-weight:600; margin-top:8px; }}
  .charts {{ display:flex; flex-wrap:wrap; gap:16px; padding:6px 28px 32px; }}
  .chart-card {{ background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,0.04); min-width:340px; overflow:hidden; }}
  .chart-title {{ font-size:14px; font-weight:600; color:#0f172a; margin-bottom:6px; }}
  .section-head {{ padding:8px 28px 0; border-top:1px solid #e2e8f0; margin-top:4px; }}
  .section-head h2 {{ font-size:16px; margin:14px 0 4px; }}
  .section-head .asof {{ font-size:12px; font-weight:500; color:#64748b; margin-left:6px; }}
  .section-head p {{ font-size:13px; color:#475569; max-width:920px; margin:4px 0 0; line-height:1.55; }}
  .footer {{ padding:0 28px 28px; font-size:11px; color:#94a3b8; }}
  .footer a {{ color:#64748b; }}
</style>
<script>{plotlyjs}</script>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <div class="logo">🌊</div>
    <div><h1>Shorelane Commerce</h1><div class="sub">Customers Dashboard</div></div>
  </div>
  <div class="badge">● Source of truth · Canonical customer grain{asof_badge}</div>
</div>
<div class="controls">
  <span class="plabel">Period</span>
  {period_buttons}
  <span class="plabel">Channel</span>
  {channel_buttons}
</div>
<div class="defs">
  <b>Current customer</b> — placed ≥1 order in the trailing 12 calendar months
  (Direct-to-Consumer and Marketplace). &nbsp;<b>Current subscriber</b> — a Business
  Subscription whose 12-month term covers the month; with a 12-month term this equals a
  subscription order in the trailing 12 months. &nbsp;All counts deduplicate to one
  canonical <code>app_db</code> customer ID — a customer buying in two channels counts once
  in totals. Definitions: <a href="https://github.com/shorelane-data/shorelane/blob/main/context/metrics/customers.yml">context/metrics/customers.yml</a>.
</div>
{sections}
{identity}
<div class="footer">{footer}</div>
<script>
function showPeriod(id, btn) {{
  document.querySelectorAll('.period-section').forEach(function(s) {{ s.style.display = 'none'; }});
  document.querySelectorAll('.pbtn:not(.cbtn)').forEach(function(b) {{ b.classList.remove('active'); }});
  document.getElementById(id).style.display = 'block';
  btn.classList.add('active');
  window.dispatchEvent(new Event('resize'));
  applyChannelFilter();
}}
var channelFilter = 'All';
function setChannel(label, btn) {{
  channelFilter = label;
  document.querySelectorAll('.cbtn').forEach(function(b) {{ b.classList.remove('active'); }});
  btn.classList.add('active');
  applyChannelFilter();
}}
function applyChannelFilter() {{
  document.querySelectorAll('.channel-aware .js-plotly-plot').forEach(function(gd) {{
    if (!gd.data) return;
    var vis = gd.data.map(function(t) {{
      var show = (channelFilter === 'All') || (t.name === channelFilter);
      return show ? true : 'legendonly';
    }});
    Plotly.restyle(gd, {{visible: vis}});
  }});
}}
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default="today", metavar="YYYY-MM-DD",
                    help='live-warehouse view date; "today" (default) or "full" for the whole fixture')
    ap.add_argument("--out", default=os.path.join("bi", "plotly", "customers_dashboard.html"),
                    help="output HTML path")
    args = ap.parse_args()

    tables = dd.load_tables()
    as_of = None
    if args.as_of != "full":
        as_of = pd.Timestamp.now().normalize() if args.as_of == "today" else pd.Timestamp(args.as_of)
        tables = visible_tables(tables, as_of)

    end_month = last_elapsed_month(as_of) if as_of is not None else dd.data_end_month(tables)
    monthly = cd.monthly_customer_metrics(tables)
    monthly = monthly[monthly.month <= end_month]

    periods = list(dd.PERIODS)
    period_buttons = "".join(
        f'<button class="pbtn{" active" if p == dd.DEFAULT_PERIOD else ""}" '
        f"onclick=\"showPeriod('sec-{p.replace(' ', '-')}', this)\">{p}</button>"
        for p in periods
    )
    channel_labels = ["All"] + [label for _, label, _ in cf.CHANNEL_SERIES]
    channel_buttons = "".join(
        f'<button class="pbtn cbtn{" active" if c == "All" else ""}" '
        f"onclick=\"setChannel('{c}', this)\">{c}</button>"
        for c in channel_labels
    )
    sections = "".join(
        period_section(tables, monthly, p, end_month, active=(p == dd.DEFAULT_PERIOD))
        for p in periods
    )

    # Identity health at the same snapshot the rest of the page shows. Tables are
    # already visibility-filtered when an as-of is set.
    idq_as_of = as_of if as_of is not None else pd.Timestamp(config.END_DATE)
    idq = cd.identity_quality(tables)
    identity = identity_section(idq, str(idq_as_of.date()))

    asof_badge = f" · as of {as_of.date()}" if as_of is not None else ""
    footer = (
        f"Figures derived from the seeded generators (dataset {config.DATASET_VERSION}, SEED={config.SEED})"
        + (f", filtered by the warehouse arrival rule as of {as_of.date()} — by the parity property this page "
           f"equals the live warehouse, with no credentials involved" if as_of is not None else "")
        + '. Validate with: <code>python -m bi.customers_data --anchor '
        + end_month.strftime("%Y-%m")
        + '</code> · <a href="../explore.html">About this data</a> · '
        + '<a href="../business/">Executive dashboard</a>'
    )

    html = PAGE.format(
        plotlyjs=get_plotlyjs(),
        asof_badge=asof_badge,
        period_buttons=period_buttons,
        channel_buttons=channel_buttons,
        sections=sections,
        identity=identity,
        footer=footer,
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

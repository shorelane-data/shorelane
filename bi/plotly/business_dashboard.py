"""
Shorelane Commerce — Executive Dashboard.

An interactive Plotly Dash app meant to look like a real company BI dashboard:
KPI scorecards + charts that all recompute when you change the period filter.
Headline "Revenue" is recognized_revenue (GAAP). The page itself carries no
metric definitions on purpose — like most company dashboards, the meaning of
the tiles is tribal knowledge that lives in context/metrics/, not on the page.

All figures are DERIVED from bi/dashboard_data.py (same deterministic source as
the warehouse). Validate with:  python -m bi.dashboard_data

    pip install -e ".[bi]"     # installs dash + plotly
    python -m bi.plotly.business_dashboard
    # open http://localhost:8050
"""
from __future__ import annotations

from dash import Dash, Input, Output, dcc, html

import config
from bi import dashboard_data as dd
from bi.plotly.figures import (
    GREEN,
    RED,
    fig_cash_health,
    fig_channel,
    fig_customers,
    fig_orders_aov,
    fig_revenue,
    fmt_int,
    fmt_money,
    fmt_pct,
)

# ---- load once (data is static + deterministic) --------------------------
TABLES = dd.load_tables()
MONTHLY = dd.monthly_metrics(TABLES)
END_MONTH = dd.data_end_month(TABLES)


# ---- KPI cards -----------------------------------------------------------
def _delta(cur: float, prev: float | None, good_up: bool = True):
    if prev is None or prev == 0:
        return None
    pct = (cur - prev) / abs(prev)
    positive = pct >= 0
    good = positive if good_up else not positive
    arrow = "▲" if positive else "▼"
    return html.Div(
        f"{arrow} {abs(pct) * 100:.1f}% vs prior",
        className="kpi-delta",
        style={"color": GREEN if good else RED},
    )


def kpi_card(label, value, sub, delta):
    children = [html.Div(label, className="kpi-label"), html.Div(value, className="kpi-value")]
    if sub:
        children.append(html.Div(sub, className="kpi-sub"))
    if delta is not None:
        children.append(delta)
    return html.Div(children, className="kpi-card")


def build_kpis(cur, prev):
    g = lambda k: (prev[k] if prev else None)
    return [
        kpi_card("Revenue", fmt_money(cur["recognized_revenue"]), "Recognized · GAAP",
                 _delta(cur["recognized_revenue"], g("recognized_revenue"))),
        kpi_card("GMV", fmt_money(cur["gmv"]), "Gross merchandise value",
                 _delta(cur["gmv"], g("gmv"))),
        kpi_card("Active Customers", fmt_int(cur["active_customers"]), "Ordered in period",
                 _delta(cur["active_customers"], g("active_customers"))),
        kpi_card("New Customers", fmt_int(cur["new_customers"]), "First order in period",
                 _delta(cur["new_customers"], g("new_customers"))),
        kpi_card("Avg Order Value", fmt_money(cur["aov"]), "GMV ÷ orders",
                 _delta(cur["aov"], g("aov"))),
        kpi_card("Refund Rate", fmt_pct(cur["refund_rate"]), "Refunds ÷ GMV",
                 _delta(cur["refund_rate"], g("refund_rate"), good_up=False)),
    ]


# ---- chart card wrapper --------------------------------------------------
def chart_card(title, graph_id, width="100%"):
    return html.Div(
        [html.Div(title, className="chart-title"), dcc.Graph(id=graph_id, config={"displayModeBar": False})],
        className="chart-card", style={"flex": f"1 1 {width}"},
    )


# ---- app -----------------------------------------------------------------
app = Dash(__name__, title="Shorelane Commerce — Executive Dashboard")

app.index_string = """
<!DOCTYPE html>
<html>
<head>
{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family:'Inter',-apple-system,sans-serif; background:#f1f5f9; color:#0f172a; }
  .topbar { background:#0f172a; color:#fff; padding:16px 28px; display:flex; align-items:center; justify-content:space-between; }
  .brand { display:flex; align-items:center; gap:12px; }
  .brand .logo { font-size:22px; }
  .brand h1 { font-size:18px; font-weight:700; margin:0; letter-spacing:-0.01em; }
  .brand .sub { font-size:12px; color:#94a3b8; margin-top:2px; }
  .badge { background:#1e293b; color:#38bdf8; font-size:11px; font-weight:600; padding:5px 10px; border-radius:999px; border:1px solid #334155; }
  .controls { display:flex; align-items:center; justify-content:space-between; padding:18px 28px 6px; }
  .controls .ctx { font-size:13px; color:#475569; }
  .controls .ctx b { color:#0f172a; }
  .period-wrap { display:flex; align-items:center; gap:10px; }
  .period-wrap label { font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; }
  .Select-control, .period-wrap .dash-dropdown { min-width:180px; }
  .kpi-row { display:flex; flex-wrap:wrap; gap:16px; padding:14px 28px; }
  .kpi-card { flex:1 1 160px; background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,0.04); }
  .kpi-label { font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; }
  .kpi-value { font-size:28px; font-weight:700; margin-top:6px; letter-spacing:-0.02em; }
  .kpi-sub { font-size:11px; color:#94a3b8; margin-top:2px; }
  .kpi-delta { font-size:12px; font-weight:600; margin-top:8px; }
  .charts { display:flex; flex-wrap:wrap; gap:16px; padding:6px 28px 32px; }
  .chart-card { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,0.04); min-width:340px; }
  .chart-title { font-size:14px; font-weight:600; color:#0f172a; margin-bottom:6px; }
  .footer { padding:0 28px 28px; font-size:11px; color:#94a3b8; }
</style>
</head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>
"""

app.layout = html.Div([
    html.Div(className="topbar", children=[
        html.Div(className="brand", children=[
            html.Div("🌊", className="logo"),
            html.Div([
                html.H1("Shorelane Commerce"),
                html.Div("Executive Revenue Dashboard", className="sub"),
            ]),
        ]),
        html.Div("● Revenue · Recognized (GAAP)", className="badge"),
    ]),
    html.Div(className="controls", children=[
        html.Div(id="ctx-line", className="ctx"),
        html.Div(className="period-wrap", children=[
            html.Label("Period"),
            dcc.Dropdown(
                id="period", options=[{"label": p, "value": p} for p in dd.PERIODS],
                value=dd.DEFAULT_PERIOD, clearable=False, style={"width": "200px"},
            ),
        ]),
    ]),
    html.Div(id="kpi-row", className="kpi-row"),
    html.Div(className="charts", children=[
        chart_card("Recognized Revenue by Month", "g-revenue", "100%"),
        chart_card("Revenue by Channel", "g-channel", "300px"),
        chart_card("Customer Growth", "g-customers", "420px"),
        chart_card("Orders & Average Order Value", "g-orders", "420px"),
        chart_card("Recognized Revenue vs Collected Cash", "g-cash", "420px"),
    ]),
    html.Div(
        f"Figures derived from generators (dataset {config.DATASET_VERSION}, SEED={config.SEED}). "
        "Validate with: python -m bi.dashboard_data",
        className="footer",
    ),
])


@app.callback(
    Output("kpi-row", "children"),
    Output("ctx-line", "children"),
    Output("g-revenue", "figure"),
    Output("g-channel", "figure"),
    Output("g-customers", "figure"),
    Output("g-orders", "figure"),
    Output("g-cash", "figure"),
    Input("period", "value"),
)
def update(period):
    start, end, months = dd.period_bounds(period, END_MONTH)
    df = MONTHLY[(MONTHLY.month >= start) & (MONTHLY.month <= end)]

    cur = dd.kpis(TABLES, start, end)
    pb = dd.prior_bounds(start, months)
    prev = dd.kpis(TABLES, pb[0], pb[1]) if pb else None

    ctx = html.Span([
        "Showing ", html.B(f"{start.strftime('%b %Y')} – {end.strftime('%b %Y')}"),
        "  ·  ", html.B(fmt_money(cur["recognized_revenue"])), " recognized revenue",
    ])
    return (
        build_kpis(cur, prev), ctx,
        fig_revenue(df), fig_channel(TABLES, start, end),
        fig_customers(df), fig_orders_aov(df), fig_cash_health(df),
    )


if __name__ == "__main__":
    app.run(debug=False, port=8050)

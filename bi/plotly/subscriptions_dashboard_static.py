"""
Static export of the FP&A subscriptions page for the public Pages site
(/subscriptions/): active subscribers by plan generation, ACV under contract,
starts / renewals / churn, churn rate by segment, ACV per seat, and the plan table.

    python -m bi.plotly.subscriptions_dashboard_static                 # as-of today
    python -m bi.plotly.subscriptions_dashboard_static --as-of full
"""
from __future__ import annotations

import argparse
import os

import pandas as pd
from plotly.offline import get_plotlyjs

from bi import dashboard_data as dd
from bi import subscriptions_data as sd
from bi.plotly import figures as fg
from bi.plotly import static_page as sp
from bi.plotly import subscription_figures as sf
from loaders.visibility import visible_tables


def kpi_row(cur: dict, prev: dict | None) -> str:
    g = lambda k: (prev[k] if prev else None)
    return "".join([
        sp.kpi_card("Active Subscribers", fg.fmt_int(cur["active_subscribers"]), "At window end",
                    sp.delta_html(cur["active_subscribers"], g("active_subscribers"))),
        sp.kpi_card("ACV Under Contract", fg.fmt_money(cur["acv_under_contract"]), "At window end",
                    sp.delta_html(cur["acv_under_contract"], g("acv_under_contract"))),
        sp.kpi_card("New Subscriptions", fg.fmt_int(cur["new_subscriptions"]), "First terms started",
                    sp.delta_html(cur["new_subscriptions"], g("new_subscriptions"))),
        sp.kpi_card("Renewal Rate", fg.fmt_pct(cur["renewal_rate"]), "Terms decided in period",
                    sp.delta_html(cur["renewal_rate"], g("renewal_rate"))),
        sp.kpi_card("ACV Churned", fg.fmt_money(cur["acv_churned"]), "Terms not renewed",
                    sp.delta_html(cur["acv_churned"], g("acv_churned"), good_up=False)),
        sp.kpi_card("ACV / Seat (New)", fg.fmt_money(cur["acv_per_seat_new"]), "New subscriptions",
                    sp.delta_html(cur["acv_per_seat_new"], g("acv_per_seat_new"))),
    ])


def period_section(tables, monthly: pd.DataFrame, period: str, end_month: pd.Timestamp, active: bool) -> str:
    start, end, months = dd.period_bounds(period, end_month)
    df = monthly[(monthly.month >= start) & (monthly.month <= end)]
    cur = sd.kpis(tables, start, end)
    pb = dd.prior_bounds(start, months)
    prev = sd.kpis(tables, pb[0], pb[1]) if pb else None
    q = sd.churn_by_segment_quarter(tables, start, end)
    plans = sd.by_plan(tables, end)
    ctx = (f'Showing <b>{start.strftime("%b %Y")} – {end.strftime("%b %Y")}</b> &nbsp;·&nbsp; '
           f'<b>{fg.fmt_int(cur["active_subscribers"])}</b> active subscribers at window end')
    charts = "".join([
        sp.chart_card("Active Subscribers by Plan Generation", sf.fig_active_by_generation(df), "100%"),
        sp.chart_card("New, Renewed, Churned by Month", sf.fig_starts_renewals_churn(df), "480px"),
        sp.chart_card("Renewal Churn Rate by Segment (quarter of term end)", sf.fig_churn_rate_by_segment(q), "420px"),
        sp.chart_card("ACV Under Contract", sf.fig_acv_under_contract(df), "420px"),
        sp.chart_card("ACV per Seat on New Subscriptions", sf.fig_acv_per_seat(df), "300px"),
        sp.table_card(f"Active Subscribers by Plan (as of {end:%b %d, %Y})",
                      [("Gen", True), ("Plan", False), ("Subscribers", True), ("Seats", True), ("ACV", True)],
                      [[str(r.plan_generation), r.plan_id, f"{r.active_subscribers:,}", f"{r.seats:,}", fg.fmt_money(r.acv)]
                       for r in plans.itertuples()], "420px"),
    ])
    return sp.section(period, active, ctx, kpi_row(cur, prev), charts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default="today", metavar="YYYY-MM-DD")
    ap.add_argument("--out", default=os.path.join("bi", "plotly", "subscriptions_dashboard.html"))
    args = ap.parse_args()

    tables = dd.load_tables()
    as_of = None
    if args.as_of != "full":
        as_of = pd.Timestamp.now().normalize() if args.as_of == "today" else pd.Timestamp(args.as_of)
        tables = visible_tables(tables, as_of)
    end_month = sp.last_elapsed_month(as_of) if as_of is not None else dd.data_end_month(tables)
    monthly = sd.monthly_subscriptions(tables)
    monthly = monthly[monthly.month <= end_month]

    periods = list(dd.PERIODS)
    sections = "".join(period_section(tables, monthly, p, end_month, active=(p == dd.DEFAULT_PERIOD)) for p in periods)
    html = sp.PAGE.format(
        title="Subscriptions (FP&A)", badge="Subscriptions · ACV", css=sp.CSS, plotlyjs=get_plotlyjs(),
        asof_badge=f" · as of {as_of.date()}" if as_of is not None else "",
        buttons=sp.period_buttons(periods, dd.DEFAULT_PERIOD), sections=sections,
        footer=sp.footer(as_of, [("About this data", "../explore.html"), ("Executive dashboard", "../business/"),
                                 ("Customers", "../customers/"), ("Marketing", "../marketing/")]),
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

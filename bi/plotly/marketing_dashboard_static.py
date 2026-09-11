"""
Static export of the marketing dashboard for the public Pages site (/marketing/).
Marketing's revenue is GMV; the page shows GMV by channel, consumer orders and AOV,
new customers, ad spend and CAC, category mix and margin, and active promotions.

    python -m bi.plotly.marketing_dashboard_static                 # as-of today
    python -m bi.plotly.marketing_dashboard_static --as-of full
"""
from __future__ import annotations

import argparse
import os

import pandas as pd
from plotly.offline import get_plotlyjs

from bi import dashboard_data as dd
from bi import marketing_data as md
from bi.plotly import figures as fg
from bi.plotly import marketing_figures as mf
from bi.plotly import static_page as sp
from loaders.visibility import visible_tables


def kpi_row(cur: dict, prev: dict | None) -> str:
    g = lambda k: (prev[k] if prev else None)
    return "".join([
        sp.kpi_card("GMV", fg.fmt_money(cur["gmv"]), "All channels · gross", sp.delta_html(cur["gmv"], g("gmv"))),
        sp.kpi_card("Consumer Orders", fg.fmt_int(cur["consumer_orders"]), "d2c + marketplace",
                    sp.delta_html(cur["consumer_orders"], g("consumer_orders"))),
        sp.kpi_card("Avg Order Value", fg.fmt_money(cur["aov"]), "Consumer", sp.delta_html(cur["aov"], g("aov"))),
        sp.kpi_card("New Customers", fg.fmt_int(cur["new_customers"]), "First order in period",
                    sp.delta_html(cur["new_customers"], g("new_customers"))),
        sp.kpi_card("Ad Spend", fg.fmt_money(cur["ad_spend"]), "All platforms", sp.delta_html(cur["ad_spend"], g("ad_spend"), good_up=False)),
        sp.kpi_card("CAC", fg.fmt_money(cur["cac"]), "Spend ÷ new d2c customers", sp.delta_html(cur["cac"], g("cac"), good_up=False)),
    ])


def period_section(tables, monthly: pd.DataFrame, period: str, end_month: pd.Timestamp, active: bool) -> str:
    start, end, months = dd.period_bounds(period, end_month)
    df = monthly[(monthly.month >= start) & (monthly.month <= end)]
    cur = md.kpis(tables, start, end)
    pb = dd.prior_bounds(start, months)
    prev = md.kpis(tables, pb[0], pb[1]) if pb else None
    cats = md.category_mix(tables, start, end)
    camp = md.campaigns(tables, start, end)
    ctx = (f'Showing <b>{start.strftime("%b %Y")} – {end.strftime("%b %Y")}</b> &nbsp;·&nbsp; '
           f'<b>{fg.fmt_money(cur["gmv"])}</b> GMV')
    charts = "".join([
        sp.chart_card("GMV by Channel", mf.fig_gmv_by_channel(df), "100%"),
        sp.chart_card("Consumer Orders & AOV", mf.fig_consumer_orders_aov(df), "420px"),
        sp.chart_card("Ad Spend vs New d2c Customers", mf.fig_spend_vs_new(df), "420px"),
        sp.chart_card("CAC by Month", mf.fig_cac(df), "300px"),
        sp.chart_card("Consumer Line Revenue by Category", mf.fig_category_mix(df), "480px"),
        sp.chart_card("Gross Margin by Category", mf.fig_category_margin(cats), "300px"),
        sp.chart_card("Promo Orders & Discount Dollars", mf.fig_promo_orders(df), "420px"),
        sp.table_card("Promotions in Window",
                      [("Code", False), ("Name", False), ("Window", False), ("Discount", True),
                       ("Orders", True), ("GMV", True), ("Discount $", True)],
                      [[r.promo_code, r.promo_name, f"{r.start_date:%b %d} – {r.end_date:%b %d, %Y}",
                        f"{r.discount_pct * 100:.0f}%", f"{r.orders:,}", fg.fmt_money(r.gmv), fg.fmt_money(r.discount_dollars)]
                       for r in camp.itertuples()], "420px"),
    ])
    return sp.section(period, active, ctx, kpi_row(cur, prev), charts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default="today", metavar="YYYY-MM-DD")
    ap.add_argument("--out", default=os.path.join("bi", "plotly", "marketing_dashboard.html"))
    args = ap.parse_args()

    tables = dd.load_tables()
    as_of = None
    if args.as_of != "full":
        as_of = pd.Timestamp.now().normalize() if args.as_of == "today" else pd.Timestamp(args.as_of)
        tables = visible_tables(tables, as_of)
    end_month = sp.last_elapsed_month(as_of) if as_of is not None else dd.data_end_month(tables)
    monthly = md.monthly_marketing(tables)
    monthly = monthly[monthly.month <= end_month]

    periods = list(dd.PERIODS)
    sections = "".join(period_section(tables, monthly, p, end_month, active=(p == dd.DEFAULT_PERIOD)) for p in periods)
    html = sp.PAGE.format(
        title="Marketing Dashboard", badge="Revenue · GMV", css=sp.CSS, plotlyjs=get_plotlyjs(),
        asof_badge=f" · as of {as_of.date()}" if as_of is not None else "",
        buttons=sp.period_buttons(periods, dd.DEFAULT_PERIOD), sections=sections,
        footer=sp.footer(as_of, [("About this data", "../explore.html"), ("Executive dashboard", "../business/"),
                                 ("Customers", "../customers/"), ("Subscriptions", "../subscriptions/")]),
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

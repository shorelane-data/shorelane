"""
Source-of-truth marketing metrics for the Shorelane marketing dashboard.

Marketing's "revenue" is GMV (see context/guides/personas.md). Everything here is
DERIVED from the same raw tables the warehouse loads, at the same rules the marts
apply: orders from real customers only (account_type = 'customer') and the 2022
channel rename coalesced. Consumer = d2c + marketplace.

    python -m bi.marketing_data --anchor 2025-12
    python -m bi.marketing_data --anchor 2025-12 --output context/ground_truth/marketing_dashboard.md
"""
from __future__ import annotations

import argparse
import pathlib

import pandas as pd

import config
from bi import dashboard_data as dd
from generators.common import canonical_channel
from generators.measures import eligible_order_ids

CONSUMER = ("d2c", "marketplace")
CATEGORIES = tuple(config.CATEGORIES)


def _orders(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Eligible orders at canonical channel grain with first-order flags."""
    o = tables["app_db__orders"]
    o = o[o.order_id.isin(eligible_order_ids(tables))].copy()
    o["channel"] = canonical_channel(o["channel"])
    o["month"] = o.order_date.dt.to_period("M").dt.to_timestamp()
    first = o.groupby("customer_id").order_date.transform("min")
    o["is_first_order"] = o.order_date == first
    return o


def _lines(tables: dict[str, pd.DataFrame], orders: pd.DataFrame) -> pd.DataFrame:
    lines = tables["app_db__order_lines"].merge(
        tables["app_db__products"][["sku", "category", "unit_cost"]], on="sku", how="left"
    )
    lines = lines[lines.order_id.isin(orders.order_id)].copy()
    lines["month"] = lines.created_at.dt.to_period("M").dt.to_timestamp()
    lines["discount_amount"] = (lines.quantity * lines.unit_price * lines.discount_pct).round(2)
    return lines


def monthly_marketing(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per month: GMV by channel, consumer orders, AOV, new customers,
    ad spend, promo orders and discount dollars, category line revenue."""
    o = _orders(tables)
    end_month = dd.data_end_month(tables)
    months = pd.date_range(config.START_DATE, end_month, freq="MS")

    gmv = o.pivot_table(index="month", columns="channel", values="gross_amount", aggfunc="sum").reindex(months, fill_value=0.0)
    for ch in ("d2c", "business_subscription", "marketplace"):
        if ch not in gmv.columns:
            gmv[ch] = 0.0
    cons = o[o.channel.isin(CONSUMER)]
    by_m = cons.groupby("month").agg(consumer_orders=("order_id", "size"), consumer_gmv=("gross_amount", "sum"))
    new = o[o.is_first_order].groupby("month").agg(new_customers=("customer_id", "size"))
    new_d2c = o[o.is_first_order & (o.channel == "d2c")].groupby("month").agg(new_d2c_customers=("customer_id", "size"))
    promo = cons[cons.promo_code.notna()].groupby("month").agg(promo_orders=("order_id", "size"))

    ads = tables["ads__daily_spend"].copy()
    ads["month"] = ads.spend_date.dt.to_period("M").dt.to_timestamp()
    spend = ads.groupby("month").agg(ad_spend=("spend_usd", "sum"), reported_conversions=("reported_conversions", "sum"))

    lines = _lines(tables, cons)
    cat = lines.pivot_table(index="month", columns="category", values="line_amount", aggfunc="sum").reindex(months, fill_value=0.0)
    cat.columns = [f"cat_{c}" for c in cat.columns]
    disc = lines.groupby("month").agg(discount_dollars=("discount_amount", "sum"))

    df = pd.DataFrame(index=months)
    df["gmv"] = gmv[["d2c", "business_subscription", "marketplace"]].sum(axis=1)
    df["gmv_d2c"] = gmv["d2c"]
    df["gmv_subscription"] = gmv["business_subscription"]
    df["gmv_marketplace"] = gmv["marketplace"]
    df = df.join([by_m, new, new_d2c, promo, spend, disc, cat]).fillna(0)
    df.index.name = "month"
    df["aov"] = (df.consumer_gmv / df.consumer_orders).replace([float("inf")], 0).fillna(0)
    df["cac"] = (df.ad_spend / df.new_d2c_customers).replace([float("inf")], 0).fillna(0)
    return df.reset_index()


def kpis(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    o = _orders(tables)
    in_p = o[(o.order_date >= start) & (o.order_date <= end)]
    cons = in_p[in_p.channel.isin(CONSUMER)]
    ads = tables["ads__daily_spend"]
    spend = float(ads[(ads.spend_date >= start) & (ads.spend_date <= end)].spend_usd.sum())
    new_d2c = int((in_p.is_first_order & (in_p.channel == "d2c")).sum())
    lines = _lines(tables, cons)
    return {
        "gmv": round(float(in_p.gross_amount.sum()), 2),
        "consumer_gmv": round(float(cons.gross_amount.sum()), 2),
        "consumer_orders": int(len(cons)),
        "aov": round(float(cons.gross_amount.mean()), 2) if len(cons) else 0.0,
        "new_customers": int(in_p.is_first_order.sum()),
        "new_d2c_customers": new_d2c,
        "ad_spend": round(spend, 2),
        "cac": round(spend / new_d2c, 2) if new_d2c else 0.0,
        "promo_orders": int(cons.promo_code.notna().sum()),
        "discount_dollars": round(float(lines.discount_amount.sum()), 2),
    }


def category_mix(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    o = _orders(tables)
    cons = o[o.channel.isin(CONSUMER) & (o.order_date >= start) & (o.order_date <= end)]
    lines = _lines(tables, cons)
    g = lines.groupby("category").agg(line_revenue=("line_amount", "sum"), units=("quantity", "sum"))
    g["cogs"] = lines.assign(c=lines.quantity * lines.unit_cost).groupby("category").c.sum()
    g["gross_margin"] = g.line_revenue - g.cogs
    g["margin_pct"] = g.gross_margin / g.line_revenue
    return g.reindex(CATEGORIES).fillna(0).reset_index()


def campaigns(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Promotions active in the window: orders carrying the code, GMV, discount dollars."""
    o = _orders(tables)
    cons = o[o.channel.isin(CONSUMER) & (o.order_date >= start) & (o.order_date <= end)]
    lines = _lines(tables, cons)
    rows = []
    for p in tables["app_db__promotions"].itertuples():
        if p.end_date < start or p.start_date > end:
            continue
        mine = cons[cons.promo_code == p.promo_code]
        rows.append({
            "promo_code": p.promo_code, "promo_name": p.promo_name,
            "start_date": p.start_date, "end_date": p.end_date, "discount_pct": p.discount_pct,
            "orders": int(len(mine)), "gmv": round(float(mine.gross_amount.sum()), 2),
            "discount_dollars": round(float(lines[lines.order_id.isin(mine.order_id)].discount_amount.sum()), 2),
        })
    return pd.DataFrame(rows, columns=["promo_code", "promo_name", "start_date", "end_date", "discount_pct",
                                       "orders", "gmv", "discount_dollars"])


def render_markdown(tables: dict[str, pd.DataFrame], anchor_month: pd.Timestamp) -> str:
    def kpi_table(period: str) -> str:
        start, end, _ = dd.period_bounds(period, anchor_month)
        k = kpis(tables, start, end)
        rows = [
            ("**GMV (all channels)**", f"**${k['gmv']:,.2f}**"),
            ("Consumer GMV (d2c + marketplace)", f"${k['consumer_gmv']:,.2f}"),
            ("Consumer orders", f"{k['consumer_orders']:,}"),
            ("Consumer AOV", f"${k['aov']:,.2f}"),
            ("New customers (first order in window)", f"{k['new_customers']:,}"),
            ("New d2c customers", f"{k['new_d2c_customers']:,}"),
            ("Ad spend", f"${k['ad_spend']:,.2f}"),
            ("CAC (ad spend ÷ new d2c customers)", f"${k['cac']:,.2f}"),
            ("Orders with a promo code", f"{k['promo_orders']:,}"),
            ("Discount dollars given", f"${k['discount_dollars']:,.2f}"),
        ]
        body = "\n".join(f"| {a} | {b} |" for a, b in rows)
        cats = category_mix(tables, start, end)
        cat_rows = "\n".join(
            f"| {r.category} | ${r.line_revenue:,.2f} | {r.margin_pct * 100:.2f}% |" for r in cats.itertuples()
        )
        camp = campaigns(tables, start, end)
        camp_rows = "\n".join(
            f"| {r.promo_code} | {r.start_date.date()} .. {r.end_date.date()} | {r.discount_pct * 100:.0f}% | {r.orders:,} | ${r.gmv:,.2f} | ${r.discount_dollars:,.2f} |"
            for r in camp.itertuples()
        ) or "| — | no promotions in window | | | | |"
        return (f"## {period} ({start.date()} .. {end.date()})\n\n| KPI | Value |\n|---|---:|\n{body}\n\n"
                f"Category line revenue (consumer orders):\n\n| Category | Line revenue | Margin % |\n|---|---:|---:|\n{cat_rows}\n\n"
                f"Promotions in window:\n\n| Code | Window | Discount | Orders | GMV | Discount $ |\n|---|---|---:|---:|---:|---:|\n{camp_rows}\n")

    return f"""# Ground truth — Marketing Dashboard KPIs

Dataset: **{config.DATASET_VERSION}** (SEED={config.SEED}). These figures are
**derived from the generated data** by `bi/marketing_data.py`, not hand-authored.
They are the numbers the marketing dashboard (`bi/plotly/marketing_dashboard_static.py`)
renders. Reproduce exactly with:

```
python -m bi.marketing_data --anchor {anchor_month.strftime('%Y-%m')} --output context/ground_truth/marketing_dashboard.md
```

Marketing's headline is **GMV** (full ticket, all channels, gross of refunds).
Orders from non-`customer` accounts are excluded; channels are canonical
(`direct` coalesced to `d2c`); "consumer" means d2c + marketplace. New customers
are first-ever orders. CAC divides ad spend by new d2c customers attributed in
the warehouse, never by platform-reported conversions. Windows are pinned to
fully elapsed months ending {anchor_month.strftime('%Y-%m')}.

{kpi_table('Last 12 Months')}
{kpi_table('Last 24 Months')}
"""


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--period", default=dd.DEFAULT_PERIOD, choices=list(dd.PERIODS))
    ap.add_argument("--anchor", default=None, metavar="YYYY-MM")
    ap.add_argument("--output", type=pathlib.Path, default=None)
    args = ap.parse_args()
    tables = dd.load_tables()
    end_month = pd.Timestamp(args.anchor + "-01") if args.anchor else dd.data_end_month(tables)
    if args.output is not None:
        if args.anchor is None:
            ap.error("--output requires --anchor (ground truth must be pinned)")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_markdown(tables, end_month))
        print(f"wrote {args.output}")
        return
    start, end, _ = dd.period_bounds(args.period, end_month)
    for k, v in kpis(tables, start, end).items():
        print(f"  {k:<20} {v:>16,}")


if __name__ == "__main__":
    _main()

"""Canonical reference measures for the SEEDED EVENTS (tier-2 / tier-3 ground truth).

Every figure here is derived from ``dataset.generate()`` over fully elapsed
calendar windows, so it is valid against both the full Parquet and the live
drip-fed warehouse. Diagnostic eval questions cite these values as the driver,
magnitude, and caveat an agent must find. Run the module to print or update the
committed ground truth:

    python -m generators.event_measures
    python -m generators.event_measures --output context/ground_truth/events.md
"""
from __future__ import annotations

import argparse
import pathlib
from collections.abc import Mapping

import pandas as pd

import config
from generators import dataset
from generators.common import canonical_channel
from generators.measures import eligible_order_ids


def _month(s: pd.Series) -> pd.Series:
    return s.dt.to_period("M").astype(str)


def _quarter(s: pd.Series) -> pd.Series:
    return s.dt.to_period("Q").astype(str)


def derive_event_measures(tables: Mapping[str, pd.DataFrame]) -> dict[str, dict]:
    keep = eligible_order_ids(tables)
    orders = tables["app_db__orders"]
    orders = orders[orders.order_id.isin(keep)].copy()
    orders["channel"] = canonical_channel(orders["channel"])
    orders["month"] = _month(orders.order_date)
    consumer = orders[orders.channel != "business_subscription"]
    lines = tables["app_db__order_lines"].merge(
        tables["app_db__products"][["sku", "category", "unit_cost"]], on="sku", how="left"
    )
    lines = lines[lines.order_id.isin(keep)].copy()
    lines["month"] = _month(lines.created_at)
    subs = tables["app_db__subscriptions"].merge(
        tables["app_db__customers"][["app_db_customer_id", "segment"]],
        left_on="customer_id", right_on="app_db_customer_id", how="left",
    )
    subs["start_month"] = _month(subs.term_start)
    subs["end_quarter"] = _quarter(subs.term_end)
    ships = tables["erp__supplier_shipments"]
    ads = tables["ads__daily_spend"].copy()
    ads["month"] = _month(ads.spend_date)
    tickets = tables["zendesk__tickets"].copy()
    tickets["month"] = _month(tickets.created_at)

    out: dict[str, dict] = {}

    # --- supplier outage: paper share of consumer line revenue collapses
    months = ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05", "2023-06"]
    by_m = lines[lines.month.isin(months)].groupby("month")
    paper = lines[(lines.category == "paper") & lines.month.isin(months)].groupby("month").line_amount.sum()
    total = by_m.line_amount.sum()
    ev = next(e for e in config.EVENTS if e["id"] == "supplier_outage_2023_03")
    window_ships = ships[(ships.category == "paper") & (ships.expected_date >= pd.Timestamp(ev["start"]))
                         & (ships.expected_date <= pd.Timestamp(ev["end"]))]
    out["supplier_outage_2023_03"] = {
        "window": f'{ev["start"]}..{ev["end"]}',
        "paper_line_revenue_by_month": {m: round(float(paper.get(m, 0.0)), 2) for m in months},
        "paper_share_of_line_revenue_by_month": {m: round(float(paper.get(m, 0.0) / total[m]), 4) for m in months},
        "consumer_orders_by_month": {m: int((consumer.month == m).sum()) for m in months},
        "paper_shipments_in_window": int(len(window_ships)),
        "paper_units_expected_in_window": int(window_ships.units_expected.sum()),
        "paper_units_received_in_window": int(window_ships.units_received.sum()),
        "delayed_shipment_ids": window_ships.shipment_id.tolist(),
    }

    # --- promo: order count spikes, AOV drops, discount dollars
    months = ["2024-07", "2024-08", "2024-09", "2024-10", "2024-11"]
    c = consumer[consumer.month.isin(months)]
    disc = lines[lines.month.isin(months)].assign(
        discount_amount=lambda d: (d.quantity * d.unit_price * d.discount_pct).round(2)
    ).groupby("month").discount_amount.sum()
    out["promo_back_to_business_2024_09"] = {
        "window": "2024-09-01..2024-09-30",
        "consumer_orders_by_month": {m: int((c.month == m).sum()) for m in months},
        "consumer_gmv_by_month": {m: round(float(c[c.month == m].gross_amount.sum()), 2) for m in months},
        "consumer_aov_by_month": {m: round(float(c[c.month == m].gross_amount.mean()), 2) for m in months},
        "promo_orders_by_month": {m: int(((c.month == m) & (c.promo_code == "BTB15")).sum()) for m in months},
        "discount_dollars_by_month": {m: round(float(disc.get(m, 0.0)), 2) for m in months},
    }

    # --- price increase: gen-3 price per seat steps, new starts dip
    months = ["2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09"]
    new = subs[subs.renewed_from_subscription_id.isna() & subs.start_month.isin(months)]
    prices = tables["app_db__plan_prices"]
    gen3 = tables["app_db__plans"].loc[tables["app_db__plans"].plan_generation == 3, "plan_id"]
    out["sub_price_increase_2025_05"] = {
        "effective_from": "2025-05-01",
        "gen3_price_per_seat": {
            pid: {str(r.effective_from.date()): float(r.annual_price_per_seat)
                  for r in prices[prices.plan_id == pid].itertuples()}
            for pid in gen3
        },
        "new_subscription_starts_by_month": {m: int((new.start_month == m).sum()) for m in months},
        "new_subscription_acv_per_seat_by_month": {
            m: round(float(new[new.start_month == m].acv.sum() / new[new.start_month == m].seats.sum()), 2)
            for m in months
        },
    }

    # --- enterprise churn: renewal outcomes for terms ending each quarter
    quarters = ["2022Q2", "2022Q3", "2022Q4", "2023Q1", "2023Q2"]
    ended = subs[subs.end_quarter.isin(quarters) & subs.status.isin(["renewed", "churned"])]
    churn = {}
    for q in quarters:
        for seg in ("smb", "enterprise"):
            g = ended[(ended.end_quarter == q) & (ended.segment == seg)]
            churn[f"{q}_{seg}"] = {
                "terms_up_for_renewal": int(len(g)),
                "churned": int((g.status == "churned").sum()),
                "churn_rate": round(float((g.status == "churned").mean()), 4) if len(g) else 0.0,
                "acv_churned": round(float(g.loc[g.status == "churned", "acv"].sum()), 2),
            }
    months = ["2022-07", "2022-08", "2022-09", "2022-10", "2022-11", "2022-12", "2023-01"]
    ent_billing = tickets[(tickets.category == "billing") & (tickets.requester_source_system == "salesforce")]
    out["enterprise_churn_2022_q4"] = {
        "window": "2022-10-01..2022-12-31",
        "renewal_outcomes": churn,
        "business_billing_tickets_by_month": {m: int((ent_billing.month == m).sum()) for m in months},
        "business_high_priority_billing_tickets_by_month": {
            m: int(((ent_billing.month == m) & ent_billing.priority.isin(["high", "urgent"])).sum()) for m in months
        },
    }

    # --- ad spend cut: spend, new d2c customers, share of new
    months = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    first = orders.groupby("customer_id").order_date.min()
    d2c = consumer[consumer.channel == "d2c"].copy()
    d2c["is_new"] = d2c.order_date.values == first.reindex(d2c.customer_id.values).values
    d = d2c[d2c.month.isin(months)]
    a = ads[ads.month.isin(months)]
    out["ad_spend_cut_2026_02"] = {
        "window": "2026-02-01..2026-04-30",
        "ad_spend_by_month": {m: round(float(a[a.month == m].spend_usd.sum()), 2) for m in months},
        "d2c_orders_by_month": {m: int((d.month == m).sum()) for m in months},
        "new_d2c_customers_by_month": {m: int(d[d.month == m].is_new.sum()) for m in months},
        "new_customer_share_of_d2c_orders_by_month": {
            m: round(float(d[d.month == m].is_new.mean()), 4) for m in months
        },
    }

    # --- prescriptive substrate: 2025 gross margin by category (consumer lines)
    y = lines[lines.created_at.dt.year == 2025]
    margin = y.assign(cogs=lambda d: d.quantity * d.unit_cost).groupby("category").agg(
        revenue=("line_amount", "sum"), cogs=("cogs", "sum"), units=("quantity", "sum")
    )
    margin["gross_margin"] = margin.revenue - margin.cogs
    margin["gross_margin_pct"] = margin.gross_margin / margin.revenue
    out["category_margin_2025"] = {
        cat: {"revenue": round(float(r.revenue), 2), "cogs": round(float(r.cogs), 2),
              "gross_margin": round(float(r.gross_margin), 2),
              "gross_margin_pct": round(float(r.gross_margin_pct), 4), "units": int(r.units)}
        for cat, r in margin.iterrows()
    }
    return out


def _table(d: Mapping, label: str, value_fmt) -> str:
    rows = "\n".join(f"| {k} | {value_fmt(v)} |" for k, v in d.items())
    return f"| {label} | Value |\n|---|---:|\n{rows}\n"


def render_markdown(m: Mapping[str, dict]) -> str:
    money = lambda v: f"${v:,.2f}"  # noqa: E731
    pct = lambda v: f"{v * 100:.2f}%"  # noqa: E731
    num = lambda v: f"{v:,}"  # noqa: E731
    so, pr, pi, ch, ad, mg = (m["supplier_outage_2023_03"], m["promo_back_to_business_2024_09"],
                              m["sub_price_increase_2025_05"], m["enterprise_churn_2022_q4"],
                              m["ad_spend_cut_2026_02"], m["category_margin_2025"])
    churn_rows = "\n".join(
        f"| {k.replace('_', ' ')} | {v['terms_up_for_renewal']:,} | {v['churned']:,} | {v['churn_rate'] * 100:.2f}% | ${v['acv_churned']:,.2f} |"
        for k, v in ch["renewal_outcomes"].items()
    )
    margin_rows = "\n".join(
        f"| {cat} | ${v['revenue']:,.2f} | ${v['cogs']:,.2f} | ${v['gross_margin']:,.2f} | {v['gross_margin_pct'] * 100:.2f}% | {v['units']:,} |"
        for cat, v in mg.items()
    )
    price_rows = "\n".join(
        f"| {pid} | " + " → ".join(f"{d}: ${p:,.2f}" for d, p in hist.items()) + " |"
        for pid, hist in pi["gen3_price_per_seat"].items()
    )
    return f"""# Ground truth — seeded events (diagnostic and prescriptive substrate)

Dataset: **{config.DATASET_VERSION}** (SEED={config.SEED}). These figures are
**derived from the generated data** by `generators/event_measures.py`, not
hand-authored. Every window is a fully elapsed calendar period, so the figures
are valid against both the full fixture and the live drip-fed warehouse.
Reproduce exactly with:

```
python -m generators.event_measures --output context/ground_truth/events.md
```

Orders from non-`customer` accounts (`app_db__customers.account_type` in
`test`, `internal`) are excluded throughout, matching `fct_revenue`. Channels are
at canonical grain (`direct` coalesced to `d2c`).

## 1. Supplier outage — {so['window']} (cause: `erp__supplier_shipments`)

North Paper Mills shipped **{so['paper_units_received_in_window']:,} of
{so['paper_units_expected_in_window']:,}** expected units across
{so['paper_shipments_in_window']} scheduled shipments in the window
(`status = 'delayed'`: {", ".join(so['delayed_shipment_ids'])}).

{_table(so['paper_line_revenue_by_month'], 'Paper line revenue by month', money)}
{_table(so['paper_share_of_line_revenue_by_month'], 'Paper share of consumer line revenue', pct)}
{_table(so['consumer_orders_by_month'], 'Consumer orders by month', num)}
## 2. Back to Business promo — {pr['window']} (cause: `app_db__promotions`, code `BTB15`)

{_table(pr['consumer_orders_by_month'], 'Consumer orders by month', num)}
{_table(pr['consumer_gmv_by_month'], 'Consumer GMV by month', money)}
{_table(pr['consumer_aov_by_month'], 'Consumer AOV by month', money)}
{_table(pr['promo_orders_by_month'], 'Orders carrying BTB15 by month', num)}
{_table(pr['discount_dollars_by_month'], 'Discount dollars given by month', money)}
## 3. Gen-3 subscription price increase — effective {pi['effective_from']} (cause: `app_db__plan_prices`)

| Plan | Annual price per seat history |
|---|---|
{price_rows}

{_table(pi['new_subscription_starts_by_month'], 'New subscription starts by month', num)}
{_table(pi['new_subscription_acv_per_seat_by_month'], 'New-subscription ACV per seat by month', money)}
## 4. Enterprise churn — {ch['window']} (cause: `zendesk__tickets`)

Renewal outcomes for terms ending in each quarter (`status` in `renewed`, `churned`):

| Quarter / segment | Up for renewal | Churned | Churn rate | ACV churned |
|---|---:|---:|---:|---:|
{churn_rows}

{_table(ch['business_billing_tickets_by_month'], 'Business (Salesforce-requester) billing tickets by month', num)}
{_table(ch['business_high_priority_billing_tickets_by_month'], 'of which high/urgent priority', num)}
## 5. Paid-media cut — {ad['window']} (cause: `ads__daily_spend`)

{_table(ad['ad_spend_by_month'], 'Ad spend by month (all platforms)', money)}
{_table(ad['d2c_orders_by_month'], 'd2c orders by month', num)}
{_table(ad['new_d2c_customers_by_month'], 'New d2c customers by month (first-ever order)', num)}
{_table(ad['new_customer_share_of_d2c_orders_by_month'], 'New-customer share of d2c orders', pct)}
## 6. Prescriptive substrate — 2025 gross margin by category (consumer order lines)

| Category | Line revenue | COGS (qty × unit_cost) | Gross margin | Margin % | Units |
|---|---:|---:|---:|---:|---:|
{margin_rows}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, help="write Markdown here instead of stdout")
    args = parser.parse_args(argv)
    markdown = render_markdown(derive_event_measures(dataset.generate()))
    if args.output is None:
        print(markdown, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown)
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

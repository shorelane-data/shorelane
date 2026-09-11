"""
Source-of-truth customer metrics for the Shorelane customers dashboard.

Like bi/dashboard_data.py, everything here is DERIVED from the same raw tables
the warehouse loads, so the dashboard is a thing you can validate agent answers
against. Counts are at the CANONICAL customer grain (app_db__orders.customer_id
== dim_customers.app_db_customer_id) — never at source-alias grain, which is the
identity-fragmentation trap (see context/guides/customer_identity.md).

Definitions (the human-confirmed context; see context/metrics/customers.yml):

  current customer     d2c / marketplace: placed >=1 order in the trailing 12
                       calendar months (month grain, window end inclusive).
  current subscriber   business_subscription: an order whose 12-month ratable
                       term (config.SUBSCRIPTION_TERM_MONTHS) covers the month —
                       equivalently, a subscription order in the trailing 12
                       calendar months.
  active customer      ordered at least once inside the selected period.
  new customer         first-ever order falls inside the selected period.

The trailing window equals the subscription term on purpose: at month grain the
subscriber rule and the trailing-year rule coincide, so "current customers" is
one consistent series with channel-specific semantics.

Run it to print the source-of-truth KPI table (the numbers to validate against):

    python -m bi.customers_data                    # default period
    python -m bi.customers_data --anchor 2025-12   # pin to fully-elapsed months

The identity-health block always applies the arrival rule at the window end, so
its figures match what the live warehouse's crosswalk sees on that date.
"""
from __future__ import annotations

import argparse
import pathlib

import pandas as pd

import config
from bi import dashboard_data as dd
from loaders.visibility import visible_tables

# Trailing window for "current" — deliberately the subscription term, so the
# subscriber rule and the trailing-year rule coincide at month grain.
CURRENT_WINDOW_MONTHS = config.SUBSCRIPTION_TERM_MONTHS

CHANNELS = ("d2c", "business_subscription", "marketplace")

SOURCE_TABLES = (
    ("app_db", "app_db__customers", "app_db_customer_id"),
    ("stripe", "stripe__customers", "stripe_customer_id"),
    ("shopify", "shopify__customers", "shopify_customer_id"),
    ("salesforce", "salesforce__customers", "salesforce_customer_id"),
)

STATUS_LABELS = {
    "resolved": "Resolved",
    "unresolved_migration_gap": "Unresolved — 2021 migration gap",
    "unresolved_sync_lag": "Unresolved — sync lag",
}


def _orders_with_month(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    o = tables["app_db__orders"].copy()
    o["month"] = o.order_date.dt.to_period("M").dt.to_timestamp()
    return o


def current_sets(o: pd.DataFrame, end_month: pd.Timestamp) -> dict[str, set]:
    """Canonical-customer sets that are 'current' as of end_month (inclusive)."""
    w_start = end_month - pd.DateOffset(months=CURRENT_WINDOW_MONTHS - 1)
    w = o[(o.month >= w_start) & (o.month <= end_month)]
    sets = {ch: set(w.loc[w.channel == ch, "customer_id"]) for ch in CHANNELS}
    sets["total"] = set(w.customer_id)
    return sets


def monthly_customer_metrics(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per month from START to the last order month: active customers by
    channel, new vs returning, and the current-customer series per channel."""
    o = _orders_with_month(tables)
    end_month = dd.data_end_month(tables)
    months = pd.date_range(config.START_DATE, end_month, freq="MS")

    active = (
        o.groupby(["month", "channel"]).customer_id.nunique().unstack(fill_value=0)
    ).reindex(months, fill_value=0)
    active_total = o.groupby("month").customer_id.nunique().reindex(months, fill_value=0)

    first_month = o.groupby("customer_id").order_date.min().dt.to_period("M").dt.to_timestamp()
    new_customers = first_month.value_counts().sort_index().reindex(months, fill_value=0)

    cur_rows = []
    for m in months:
        s = current_sets(o, m)
        cur_rows.append(
            {
                "month": m,
                "current_customers": len(s["total"]),
                "current_d2c": len(s["d2c"]),
                "current_subscribers": len(s["business_subscription"]),
                "current_marketplace": len(s["marketplace"]),
            }
        )
    cur = pd.DataFrame(cur_rows).set_index("month")

    df = pd.DataFrame(index=months)
    df.index.name = "month"
    for ch in CHANNELS:
        df[f"active_{ch}"] = active[ch] if ch in active.columns else 0
    df["active_customers"] = active_total
    df["new_customers"] = new_customers
    df["returning_customers"] = df["active_customers"] - df["new_customers"]
    df = df.join(cur)
    return df.reset_index()


def kpis(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp,
         channel: str | None = None) -> dict[str, float | None]:
    """Headline customer KPI bundle for a period. 'Current' figures are the
    point-in-time snapshot at the period's last month.

    With ``channel`` set, every count is restricted to that channel: current =
    ordered in that channel in the trailing window; active = ordered in that
    channel in the period; new = first-ever order (any channel) fell in the
    period AND was placed in that channel. Current subscribers is only defined
    for business_subscription and multi-channel is undefined for a single
    channel (both returned as None)."""
    o = _orders_with_month(tables)
    s = current_sets(o, end.to_period("M").to_timestamp())
    first_order = o.groupby("customer_id").order_date.min()
    in_p = o[(o.order_date >= start) & (o.order_date <= end)]

    if channel is None:
        active = int(in_p.customer_id.nunique())
        new = int(((first_order >= start) & (first_order <= end)).sum())
        multi = int((in_p.groupby("customer_id").channel.nunique() >= 2).sum())
        return {
            "current_customers": len(s["total"]),
            "current_subscribers": len(s["business_subscription"]),
            "current_d2c": len(s["d2c"]),
            "current_marketplace": len(s["marketplace"]),
            "active_customers": active,
            "new_customers": new,
            "returning_share": round(1 - new / active, 4) if active else 0.0,
            "multi_channel_customers": multi,
        }

    ch = in_p[in_p.channel == channel]
    active = int(ch.customer_id.nunique())
    is_first = ch.order_date.values == first_order.reindex(ch.customer_id.values).values
    new = int(ch.loc[is_first, "customer_id"].nunique())
    return {
        "current_customers": len(s[channel]),
        "current_subscribers": len(s["business_subscription"]) if channel == "business_subscription" else None,
        "current_d2c": len(s["d2c"]),
        "current_marketplace": len(s["marketplace"]),
        "active_customers": active,
        "new_customers": new,
        "returning_share": round(1 - new / active, 4) if active else 0.0,
        "multi_channel_customers": None,
    }


def identity_quality(tables: dict[str, pd.DataFrame]) -> dict:
    """Identity-health aggregates at source-alias grain, mirroring the dbt
    int_customer_identity / fct_identity_resolution_quality classification.
    Pass visibility-filtered tables to get a specific as-of snapshot."""
    frames = []
    for system, table, col in SOURCE_TABLES:
        src = tables[table]
        frames.append(
            pd.DataFrame(
                {
                    "source_system": system,
                    "source_customer_id": src[col].astype("string"),
                    "created_at": pd.to_datetime(src["created_at"]),
                }
            )
        )
    aliases = pd.concat(frames, ignore_index=True)
    xw = tables["app_db__customer_id_crosswalk"]
    resolved = aliases.merge(
        xw[["source_system", "source_customer_id", "app_db_customer_id"]],
        on=["source_system", "source_customer_id"],
        how="left",
        validate="one_to_one",
    )

    migration = pd.Timestamp(config.IDENTITY_MIGRATION_DATE)
    unresolved = resolved.app_db_customer_id.isna()
    gap = (
        unresolved
        & resolved.source_system.isin(["shopify", "salesforce"])
        & (resolved.created_at < migration)
    )
    resolved["resolution_status"] = "resolved"
    resolved.loc[unresolved, "resolution_status"] = "unresolved_sync_lag"
    resolved.loc[gap, "resolution_status"] = "unresolved_migration_gap"

    by_system = (
        resolved.groupby(["source_system", "resolution_status"]).size().unstack(fill_value=0)
    )
    for status in STATUS_LABELS:
        if status not in by_system.columns:
            by_system[status] = 0
    by_system = by_system[list(STATUS_LABELS)]

    orders = tables["app_db__orders"]
    ordered_ids = pd.Index(orders.customer_id.unique())
    ra = resolved[resolved.app_db_customer_id.notna()]
    ids_per_customer = ra.groupby("app_db_customer_id").size()
    avg_ids_ordered = float(ids_per_customer.reindex(ordered_ids).dropna().mean())

    alias_count = int(len(resolved))
    unresolved_count = int(unresolved.sum())
    return {
        "by_system": by_system,
        "alias_count": alias_count,
        "unresolved_count": unresolved_count,
        "null_rate": round(unresolved_count / alias_count, 6) if alias_count else 0.0,
        "canonical_profiles": int(len(tables["app_db__customers"])),
        "ordered_customers": int(orders.customer_id.nunique()),
        "avg_source_ids_per_ordered_customer": round(avg_ids_ordered, 3),
        "pre_migration_shopify_missing": int(
            (gap & (resolved.source_system == "shopify")).sum()
        ),
        "pre_migration_salesforce_missing": int(
            (gap & (resolved.source_system == "salesforce")).sum()
        ),
    }


# ---------------------------------------------------------------------------
# CLI: print the validation table, or derive the ground-truth markdown.
# ---------------------------------------------------------------------------

def _kpi_lines(k: dict[str, float]) -> list[str]:
    return [
        f"  {'Current customers':<28} {k['current_customers']:>10,}",
        f"  {'Current subscribers':<28} {k['current_subscribers']:>10,}",
        f"  {'Current d2c customers':<28} {k['current_d2c']:>10,}",
        f"  {'Current marketplace cust.':<28} {k['current_marketplace']:>10,}",
        f"  {'Active customers (period)':<28} {k['active_customers']:>10,}",
        f"  {'New customers (period)':<28} {k['new_customers']:>10,}",
        f"  {'Returning share':<28} {k['returning_share'] * 100:>9.2f}%",
        f"  {'Multi-channel customers':<28} {k['multi_channel_customers']:>10,}",
    ]


def render_markdown(tables: dict[str, pd.DataFrame], anchor_month: pd.Timestamp) -> str:
    """Derived ground truth for the customers dashboard, pinned to fully-elapsed
    months ending at anchor_month. Never hand-edit the output."""
    as_of = (anchor_month + pd.offsets.MonthEnd(0)).normalize()
    idq = identity_quality(visible_tables(tables, as_of))

    def kpi_table(period: str) -> str:
        start, end, _ = dd.period_bounds(period, anchor_month)
        k = kpis(tables, start, end)
        rows = [
            ("Current customers (at window end)", f"{k['current_customers']:,}"),
            ("Current subscribers (at window end)", f"{k['current_subscribers']:,}"),
            ("Current d2c customers (at window end)", f"{k['current_d2c']:,}"),
            ("Current marketplace customers (at window end)", f"{k['current_marketplace']:,}"),
            ("Active customers (ordered in window)", f"{k['active_customers']:,}"),
            ("New customers (first order in window)", f"{k['new_customers']:,}"),
            ("Returning share of actives", f"{k['returning_share'] * 100:.2f}%"),
            ("Multi-channel customers (in window)", f"{k['multi_channel_customers']:,}"),
        ]
        body = "\n".join(f"| {label} | {value} |" for label, value in rows)
        return (
            f"## {period} ({start.date()} .. {end.date()})\n\n"
            f"| KPI | Value |\n|---|---:|\n{body}\n"
        )

    sys_rows = "\n".join(
        f"| {system} | {int(row['resolved']):,} | {int(row['unresolved_migration_gap']):,} "
        f"| {int(row['unresolved_sync_lag']):,} |"
        for system, row in idq["by_system"].iterrows()
    )
    return f"""# Ground truth — Customers Dashboard KPIs

Dataset: **{config.DATASET_VERSION}** (SEED={config.SEED}). These figures are
**derived from the generated data** by `bi/customers_data.py`, not hand-authored.
They are the source-of-truth numbers the customers dashboard
(`bi/plotly/customers_dashboard_static.py`) renders. Reproduce exactly with:

```
python -m bi.customers_data --anchor {anchor_month.strftime('%Y-%m')} --output context/ground_truth/customers_dashboard.md
```

All counts are at the **canonical customer grain** (`app_db__orders.customer_id`
== `dim_customers.app_db_customer_id`), never at source-alias grain — counting
per-system customer rows double-counts (see the identity block below and
`context/guides/customer_identity.md`). Definitions live in
`context/metrics/customers.yml`; the trailing "current" window is
{CURRENT_WINDOW_MONTHS} calendar months, equal to the subscription term, so the
current-subscriber rule (active ratable term) and the trailing-year rule
coincide at month grain. Windows are pinned to fully-elapsed months ending
{anchor_month.strftime('%Y-%m')}, so the figures are valid against both the full
fixture and the live drip-fed warehouse.

{kpi_table('Last 12 Months')}
{kpi_table('All Time')}
## Identity health (arrival rule applied as of {as_of.date()})

| Measure | Derived value |
|---|---:|
| Source aliases (4 systems, sum of profile rows) | {idq['alias_count']:,} |
| Unresolved aliases | {idq['unresolved_count']:,} |
| Resolution null rate | {idq['null_rate']:.6f} |
| Canonical app profiles | {idq['canonical_profiles']:,} |
| Ever-ordered canonical customers | {idq['ordered_customers']:,} |
| Avg source IDs per ordered customer | {idq['avg_source_ids_per_ordered_customer']:.3f} |
| Pre-migration Shopify aliases missing from crosswalk | {idq['pre_migration_shopify_missing']:,} |
| Pre-migration Salesforce aliases missing from crosswalk | {idq['pre_migration_salesforce_missing']:,} |

Aliases by source system and resolution status:

| Source system | Resolved | 2021 migration gap | Sync lag |
|---|---:|---:|---:|
{sys_rows}
"""


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--period", default=dd.DEFAULT_PERIOD, choices=list(dd.PERIODS))
    ap.add_argument("--anchor", default=None, metavar="YYYY-MM",
                    help="pin the window end to this month instead of the data's last order month")
    ap.add_argument("--output", type=pathlib.Path, default=None,
                    help="write the derived ground-truth markdown here (requires --anchor)")
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
    k = kpis(tables, start, end)
    print(f"Shorelane source-of-truth customer KPIs — {args.period} ({start.date()} .. {end.date()})")
    print(f"  (dataset {config.DATASET_VERSION}, canonical grain = app_db customer_id)\n")
    print("\n".join(_kpi_lines(k)))

    idq = identity_quality(visible_tables(tables, end))
    print(f"\n  Identity health (as of {end.date()}):")
    print(f"    {'Source aliases':<26} {idq['alias_count']:>10,}")
    print(f"    {'Resolution null rate':<26} {idq['null_rate'] * 100:>9.2f}%")
    print(f"    {'Canonical app profiles':<26} {idq['canonical_profiles']:>10,}")
    print(f"    {'Ever-ordered customers':<26} {idq['ordered_customers']:>10,}")
    print(f"    {'Avg IDs / ordered customer':<26} {idq['avg_source_ids_per_ordered_customer']:>10.3f}")


if __name__ == "__main__":
    _main()

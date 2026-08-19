"""
Source-of-truth metrics for the Shorelane executive dashboard.

Everything here is DERIVED from the same raw tables the warehouse loads, so the
dashboard is a thing you can validate agent answers against — not a second source
of generation logic. Revenue reuses the canonical generators/measures.py
(five_revenues); customer / order / refund dimensions are aggregated here.

Headline "Revenue" = recognized_revenue (GAAP), the canonical default from
context/metrics/revenue.yml.

Run it to print the source-of-truth KPI table (the numbers to validate against):

    python -m bi.dashboard_data                # default period (Last 12 Months)
    python -m bi.dashboard_data --period "All Time"

Periods anchor to the last month with orders. With the v2 timeline extending
past "today", pass --anchor YYYY-MM to pin the window end to a fully-elapsed
month instead — that's how context/ground_truth/business_dashboard.md stays
valid against both the full fixture and the live drip-fed warehouse.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

import config
from generators import dataset
from generators.dataset import RAW_TABLES
from generators.measures import five_revenues

# Period filter options, keyed to a trailing window length in months (None = all).
PERIODS: dict[str, int | None] = {
    "Last 6 Months": 6,
    "Last 12 Months": 12,
    "Last 24 Months": 24,
    "All Time": None,
}
DEFAULT_PERIOD = "Last 12 Months"

CHANNEL_LABELS = {
    "d2c": "Direct-to-Consumer",
    "business_subscription": "Business Subscriptions",
    "marketplace": "Marketplace",
}

def load_tables() -> dict[str, pd.DataFrame]:
    """Prefer the generated Parquet in data/raw (what the warehouse loaded);
    fall back to regenerating in-memory. Both are the same deterministic source."""
    if all(os.path.exists(os.path.join(config.RAW_DIR, f"{n}.parquet")) for n in RAW_TABLES):
        tables = {n: pd.read_parquet(os.path.join(config.RAW_DIR, f"{n}.parquet")) for n in RAW_TABLES}
    else:
        tables = dataset.generate()
    # Normalize date dtypes (Parquet round-trips fine; be defensive anyway).
    tables["app_db__orders"]["order_date"] = pd.to_datetime(tables["app_db__orders"]["order_date"])
    tables["app_db__revenue_recognition"]["recognition_date"] = pd.to_datetime(
        tables["app_db__revenue_recognition"]["recognition_date"]
    )
    tables["stripe__refunds"]["refund_date"] = pd.to_datetime(tables["stripe__refunds"]["refund_date"])
    return tables


def data_end_month(tables: dict[str, pd.DataFrame]) -> pd.Timestamp:
    """Month-start of the latest month that actually has orders. The dashboard
    timeline ends here so we don't show the lonely recognition tail of subs that
    keep recognizing after the last order."""
    last = tables["app_db__orders"].order_date.max()
    return last.to_period("M").to_timestamp()


def period_bounds(period: str, end_month: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, int | None]:
    """(start, end, n_months) for a named period, anchored to the data's last month."""
    months = PERIODS[period]
    end = (end_month + pd.offsets.MonthEnd(0)).normalize()
    if months is None:
        start = pd.Timestamp(config.START_DATE)
    else:
        start = (end_month - pd.DateOffset(months=months - 1)).normalize()
    return start, end, months


def prior_bounds(start: pd.Timestamp, months: int | None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """The immediately-preceding equal-length window, for delta % calculations."""
    if months is None:
        return None
    return start - pd.DateOffset(months=months), start - pd.Timedelta(days=1)


def monthly_metrics(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per month from START to the last order month, every measure the
    dashboard charts need. Revenue columns come from the canonical five_revenues."""
    orders = tables["app_db__orders"]
    refunds = tables["stripe__refunds"]
    end_month = data_end_month(tables)
    months = pd.date_range(config.START_DATE, end_month, freq="MS")

    # Revenue measures per month (canonical reference, looped per month).
    rev_rows = []
    for m in months:
        m_end = (m + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        rev_rows.append(five_revenues(tables, m.strftime("%Y-%m-%d"), m_end))
    rev = pd.DataFrame(rev_rows, index=months)

    # Order / customer dimensions.
    o = orders.copy()
    o["month"] = o.order_date.dt.to_period("M").dt.to_timestamp()
    by_month = o.groupby("month").agg(
        orders=("order_id", "size"),
        active_customers=("customer_id", "nunique"),
    )

    first_order_month = o.groupby("customer_id")["order_date"].min().dt.to_period("M").dt.to_timestamp()
    new_customers = first_order_month.value_counts().sort_index().rename("new_customers")

    # Refunds.
    r = refunds.copy()
    r["month"] = r.refund_date.dt.to_period("M").dt.to_timestamp()
    refunds_by_month = r.groupby("month").agg(
        refund_amount=("refund_amount", "sum"),
        refund_count=("refund_id", "size"),
    )

    df = rev.join([by_month, new_customers, refunds_by_month])
    df = df.reindex(months).fillna(0)
    df.index.name = "month"  # after reindex — reindex swaps in `months`, whose name is unset
    df["cumulative_customers"] = df["new_customers"].cumsum()
    df["aov"] = (df["gmv"] / df["orders"]).fillna(0)
    # Refunds as a share of GMV (a clean "leakage" rate for the cash-health view).
    df["refund_rate"] = (df["refund_amount"] / df["gmv"]).replace([float("inf")], 0).fillna(0)
    return df.reset_index()


def revenue_by_channel(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Recognized revenue split by channel for a period (recognition joined to orders)."""
    rec = tables["app_db__revenue_recognition"].merge(
        tables["app_db__orders"][["order_id", "channel"]], on="order_id", how="left"
    )
    mask = (rec.recognition_date >= start) & (rec.recognition_date <= end)
    grp = rec[mask].groupby("channel")["amount"].sum()
    out = grp.reset_index()
    out["channel_label"] = out["channel"].map(CHANNEL_LABELS).fillna(out["channel"])
    return out.sort_values("amount", ascending=False)


def kpis(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    """Headline KPI bundle for a period. Revenue is recognized (GAAP)."""
    orders = tables["app_db__orders"]
    refunds = tables["stripe__refunds"]
    rev = five_revenues(tables, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    in_orders = orders[(orders.order_date >= start) & (orders.order_date <= end)]
    first_order = orders.groupby("customer_id")["order_date"].min()
    new_customers = int(((first_order >= start) & (first_order <= end)).sum())
    n_orders = int(len(in_orders))
    refund_amount = float(
        refunds[(refunds.refund_date >= start) & (refunds.refund_date <= end)].refund_amount.sum()
    )

    return {
        "recognized_revenue": rev["recognized_revenue"],
        "gmv": rev["gmv"],
        "net_revenue": rev["net_revenue"],
        "billed_revenue": rev["billed_revenue"],
        "collected_cash": rev["collected_cash"],
        "active_customers": int(in_orders.customer_id.nunique()),
        "new_customers": new_customers,
        "orders": n_orders,
        "aov": round(rev["gmv"] / n_orders, 2) if n_orders else 0.0,
        "refund_amount": round(refund_amount, 2),
        "refund_rate": round(refund_amount / rev["gmv"], 4) if rev["gmv"] else 0.0,
    }


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default=DEFAULT_PERIOD, choices=list(PERIODS))
    ap.add_argument("--anchor", default=None, metavar="YYYY-MM",
                    help="pin the window end to this month instead of the data's last order month")
    args = ap.parse_args()

    tables = load_tables()
    end_month = pd.Timestamp(args.anchor + "-01") if args.anchor else data_end_month(tables)
    start, end, months = period_bounds(args.period, end_month)
    k = kpis(tables, start, end)

    print(f"Shorelane source-of-truth KPIs — {args.period} ({start.date()} .. {end.date()})")
    print(f"  (dataset {config.DATASET_VERSION}, revenue = recognized_revenue / GAAP)\n")
    print(f"  {'Revenue (recognized)':<24} ${k['recognized_revenue']:>14,.2f}")
    print(f"  {'GMV':<24} ${k['gmv']:>14,.2f}")
    print(f"  {'Net revenue':<24} ${k['net_revenue']:>14,.2f}")
    print(f"  {'Collected cash':<24} ${k['collected_cash']:>14,.2f}")
    print(f"  {'Active customers':<24} {k['active_customers']:>15,}")
    print(f"  {'New customers':<24} {k['new_customers']:>15,}")
    print(f"  {'Orders':<24} {k['orders']:>15,}")
    print(f"  {'Avg order value':<24} ${k['aov']:>14,.2f}")
    print(f"  {'Refund rate (of GMV)':<24} {k['refund_rate'] * 100:>14.2f}%")

    print("\n  Revenue by channel:")
    for _, row in revenue_by_channel(tables, start, end).iterrows():
        print(f"    {row['channel_label']:<24} ${row['amount']:>14,.2f}")


if __name__ == "__main__":
    _main()

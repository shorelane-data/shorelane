"""
Source-of-truth subscription metrics for the FP&A subscriptions page.

Derived from the same raw tables the warehouse loads, at the marts' rules:
real customers only, one row per 12-month term. "Active subscribers at D" are
customers with a term containing D — never status = 'active' (that only marks
terms whose outcome is not yet known) and never is_current plans (that drops
every grandfathered generation).

    python -m bi.subscriptions_data --anchor 2025-12
    python -m bi.subscriptions_data --anchor 2025-12 --output context/ground_truth/subscriptions_dashboard.md
"""
from __future__ import annotations

import argparse
import pathlib

import pandas as pd

import config
from bi import dashboard_data as dd

GENERATIONS = (1, 2, 3)
SEGMENTS = ("smb", "enterprise")


def _terms(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = tables["app_db__customers"]
    real = set(c.loc[c.account_type == "customer", "app_db_customer_id"])
    s = tables["app_db__subscriptions"]
    s = s[s.customer_id.isin(real)].copy()
    s = s.merge(tables["app_db__plans"][["plan_id", "plan_generation", "tier"]], on="plan_id", how="left")
    s = s.merge(c[["app_db_customer_id", "segment"]], left_on="customer_id", right_on="app_db_customer_id", how="left")
    s["is_first_term"] = s.renewed_from_subscription_id.isna()
    return s


def active_at(terms: pd.DataFrame, at: pd.Timestamp) -> pd.DataFrame:
    return terms[(terms.term_start <= at) & (terms.term_end >= at)]


def monthly_subscriptions(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per month: active subscribers (at month end) by generation, ACV under
    contract, new starts, renewals, churned terms and ACV, ACV per seat on new starts."""
    t = _terms(tables)
    end_month = dd.data_end_month(tables)
    months = pd.date_range(config.START_DATE, end_month, freq="MS")
    rows = []
    t["start_month"] = t.term_start.dt.to_period("M").dt.to_timestamp()
    t["end_month"] = t.term_end.dt.to_period("M").dt.to_timestamp()
    for m in months:
        me = (m + pd.offsets.MonthEnd(0)).normalize()
        a = active_at(t, me)
        started = t[t.start_month == m]
        ended = t[(t.end_month == m) & t.status.isin(["renewed", "churned"])]
        new = started[started.is_first_term]
        row = {
            "month": m,
            "active_subscribers": int(a.customer_id.nunique()),
            "acv_under_contract": round(float(a.acv.sum()), 2),
            "new_starts": int(len(new)),
            "renewals": int((~started.is_first_term).sum()),
            "terms_ended": int(len(ended)),
            "churned_terms": int((ended.status == "churned").sum()),
            "acv_churned": round(float(ended.loc[ended.status == "churned", "acv"].sum()), 2),
            "acv_per_seat_new": round(float(new.acv.sum() / new.seats.sum()), 2) if new.seats.sum() else 0.0,
        }
        for g in GENERATIONS:
            row[f"active_gen{g}"] = int(a.loc[a.plan_generation == g, "customer_id"].nunique())
        for seg in SEGMENTS:
            e = ended[ended.segment == seg]
            row[f"churn_rate_{seg}"] = round(float((e.status == "churned").mean()), 4) if len(e) else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def kpis(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    t = _terms(tables)
    a = active_at(t, end)
    started = t[(t.term_start >= start) & (t.term_start <= end)]
    new = started[started.is_first_term]
    ended = t[(t.term_end >= start) & (t.term_end <= end) & t.status.isin(["renewed", "churned"])]
    decided = len(ended)
    return {
        "active_subscribers": int(a.customer_id.nunique()),
        "acv_under_contract": round(float(a.acv.sum()), 2),
        "new_subscriptions": int(len(new)),
        "new_acv": round(float(new.acv.sum()), 2),
        "renewal_rate": round(float((ended.status == "renewed").mean()), 4) if decided else 0.0,
        "churned_terms": int((ended.status == "churned").sum()),
        "acv_churned": round(float(ended.loc[ended.status == "churned", "acv"].sum()), 2),
        "acv_per_seat_new": round(float(new.acv.sum() / new.seats.sum()), 2) if new.seats.sum() else 0.0,
        "grandfathered_share": round(float(a.loc[a.plan_generation != 3, "customer_id"].nunique() / a.customer_id.nunique()), 4) if len(a) else 0.0,
    }


def by_plan(tables: dict[str, pd.DataFrame], at: pd.Timestamp) -> pd.DataFrame:
    t = _terms(tables)
    a = active_at(t, at)
    g = a.groupby(["plan_generation", "plan_id"]).agg(
        active_subscribers=("customer_id", "nunique"), seats=("seats", "sum"), acv=("acv", "sum")
    ).reset_index()
    return g.sort_values(["plan_generation", "plan_id"], ignore_index=True)


def churn_by_segment_quarter(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    t = _terms(tables)
    e = t[(t.term_end >= start) & (t.term_end <= end) & t.status.isin(["renewed", "churned"])].copy()
    e["quarter"] = e.term_end.dt.to_period("Q").dt.to_timestamp()
    g = e.groupby(["quarter", "segment"]).agg(
        up_for_renewal=("subscription_id", "size"),
        churned=("status", lambda s: int((s == "churned").sum())),
        acv_churned=("acv", lambda s: 0.0),
    ).reset_index()
    churned_acv = e[e.status == "churned"].groupby(["quarter", "segment"]).acv.sum()
    g["acv_churned"] = [round(float(churned_acv.get((q, s), 0.0)), 2) for q, s in zip(g.quarter, g.segment)]
    g["churn_rate"] = g.churned / g.up_for_renewal
    return g


def render_markdown(tables: dict[str, pd.DataFrame], anchor_month: pd.Timestamp) -> str:
    as_of = (anchor_month + pd.offsets.MonthEnd(0)).normalize()

    def kpi_table(period: str) -> str:
        start, end, _ = dd.period_bounds(period, anchor_month)
        k = kpis(tables, start, end)
        rows = [
            ("**Active subscribers (at window end)**", f"**{k['active_subscribers']:,}**"),
            ("ACV under contract (at window end)", f"${k['acv_under_contract']:,.2f}"),
            ("Grandfathered share (gen 1–2) of active", f"{k['grandfathered_share'] * 100:.2f}%"),
            ("New subscriptions (first terms started)", f"{k['new_subscriptions']:,}"),
            ("New ACV", f"${k['new_acv']:,.2f}"),
            ("ACV per seat on new subscriptions", f"${k['acv_per_seat_new']:,.2f}"),
            ("Renewal rate (terms decided in window)", f"{k['renewal_rate'] * 100:.2f}%"),
            ("Churned terms", f"{k['churned_terms']:,}"),
            ("ACV churned", f"${k['acv_churned']:,.2f}"),
        ]
        body = "\n".join(f"| {a} | {b} |" for a, b in rows)
        return f"## {period} ({start.date()} .. {end.date()})\n\n| KPI | Value |\n|---|---:|\n{body}\n"

    plan_rows = "\n".join(
        f"| {r.plan_generation} | {r.plan_id} | {r.active_subscribers:,} | {r.seats:,} | ${r.acv:,.2f} |"
        for r in by_plan(tables, as_of).itertuples()
    )
    return f"""# Ground truth — Subscriptions Dashboard KPIs

Dataset: **{config.DATASET_VERSION}** (SEED={config.SEED}). These figures are
**derived from the generated data** by `bi/subscriptions_data.py`, not hand-authored.
They are the numbers the FP&A subscriptions page (`bi/plotly/subscriptions_dashboard_static.py`)
renders. Reproduce exactly with:

```
python -m bi.subscriptions_data --anchor {anchor_month.strftime('%Y-%m')} --output context/ground_truth/subscriptions_dashboard.md
```

Real customers only. One row per 12-month term; renewals are new terms. "Active
at D" = a term containing D, at customer grain. Renewal rate = renewed ÷ (renewed
+ churned) among terms that ended in the window; terms still running are not
decided and are excluded. Windows are pinned to fully elapsed months ending
{anchor_month.strftime('%Y-%m')}.

{kpi_table('Last 12 Months')}
{kpi_table('Last 24 Months')}
## Active subscribers by plan as of {as_of.date()}

| Generation | Plan | Active subscribers | Seats | ACV |
|---|---|---:|---:|---:|
{plan_rows}
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
        print(f"  {k:<22} {v:>16,}")


if __name__ == "__main__":
    _main()

"""Gold derivations for the benchmark question bank.

Every graded number in the bank comes from a function in this module, run over
the generated raw tables (never typed by hand, per CLAUDE.md). A spec names the
function and its parameters; ``evals/build_bank.py`` calls it and writes the
result into the generated bank file.

Each function returns a ``Derived``: the gold (a value, a result set, or the
evidence a diagnostic judge checks) plus the **silent-fail values**, the numbers
the plausible-wrong paths produce. The wrong paths are computed here, next to
the right one, so a trap that stops biting (its wrong value equals the gold)
fails the build instead of going unnoticed.

The functions are generic and parameterized. Private holdout specs (kept in
shorelane-bench until publication) reuse them with their own parameters, so the
derivation logic stays public and single-sourced while the questions stay
private.

Rules shared by every function (the marts' rules, see dbt/models/marts):
- real customers only: ``app_db__customers.account_type == 'customer'``;
- canonical channel: pre-2022-06-01 ``direct`` is ``d2c``;
- windows are inclusive calendar dates.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from generators.common import canonical_channel
from generators.identity_measures import derive_identity_measures
from generators.measures import eligible_order_ids, five_revenues

Tables = Mapping[str, pd.DataFrame]

MEASURES = ("recognized_revenue", "gmv", "net_revenue", "billed_revenue", "collected_cash")


@dataclass
class Derived:
    value: float | int | None = None
    components: dict[str, Any] = field(default_factory=dict)
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    silent_fail: dict[str, Any] = field(default_factory=dict)


DERIVERS: dict[str, Callable[..., Derived]] = {}


def deriver(fn: Callable[..., Derived]) -> Callable[..., Derived]:
    DERIVERS[fn.__name__] = fn
    return fn


# --------------------------------------------------------------------------- helpers

def _ts(d: str) -> pd.Timestamp:
    return pd.Timestamp(d)


def _day(s: pd.Series) -> pd.Series:
    """Calendar date of a timestamp column (staging casts these to DATE)."""
    return s.dt.normalize()


def _between(s: pd.Series, start: str, end: str) -> pd.Series:
    d = _day(s)
    return (d >= _ts(start)) & (d <= _ts(end))


def _money(x: float) -> float:
    return round(float(x), 2)


def _ratio(x: float) -> float:
    return round(float(x), 4)


def real_customer_ids(t: Tables) -> pd.Index:
    c = t["app_db__customers"]
    return pd.Index(c.loc[c.account_type == "customer", "app_db_customer_id"])


def orders(t: Tables) -> pd.DataFrame:
    """fct_orders: eligible orders, canonical channel, raw label, first-order flag."""
    o = t["app_db__orders"]
    o = o[o.order_id.isin(eligible_order_ids(dict(t)))].copy()
    o["channel_raw"] = o["channel"]
    o["channel"] = canonical_channel(o["channel"])
    o["is_first_order"] = o.order_date == o.groupby("customer_id").order_date.transform("min")
    return o


def all_orders(t: Tables) -> pd.DataFrame:
    """stg_orders: every account type, raw channel label (the unfiltered path)."""
    return t["app_db__orders"]


def subscription_terms(t: Tables) -> pd.DataFrame:
    """fct_subscriptions: terms of real customers with plan generation and segment."""
    s = t["app_db__subscriptions"]
    s = s[s.customer_id.isin(real_customer_ids(t))].copy()
    s = s.merge(t["app_db__plans"][["plan_id", "plan_name", "plan_generation", "is_current"]], on="plan_id", how="left")
    s = s.merge(t["app_db__customers"][["app_db_customer_id", "segment"]],
                left_on="customer_id", right_on="app_db_customer_id", how="left")
    s["is_first_term"] = s.renewed_from_subscription_id.isna()
    s["term_start_date"] = _day(s.term_start)
    s["term_end_date"] = _day(s.term_end)
    return s


def _active_at(terms: pd.DataFrame, at: str) -> pd.DataFrame:
    d = _ts(at)
    return terms[(terms.term_start_date <= d) & (terms.term_end_date >= d)]


def _quarter_label(s: pd.Series) -> pd.Series:
    return s.dt.to_period("Q").astype(str)  # e.g. 2022Q4


# --------------------------------------------------------------------------- revenue

@deriver
def revenue_measure(t: Tables, *, measure: str, start: str, end: str) -> Derived:
    """One of the five revenues for a window; the other four are the wrong answers."""
    rev = five_revenues(dict(t), start, end)
    return Derived(value=rev[measure], silent_fail={m: rev[m] for m in MEASURES if m != measure})


@deriver
def revenue_measure_hygiene(t: Tables, *, measure: str, start: str, end: str) -> Derived:
    """A revenue measure where the wrong path is the unfiltered staging sum
    (test and internal accounts included). Only defined for order-date measures."""
    rev = five_revenues(dict(t), start, end)
    o = all_orders(t)
    in_p = o[_between(o.order_date, start, end)]
    column = {"gmv": "gross_amount"}[measure]
    return Derived(value=rev[measure], silent_fail={
        "staging_including_test_and_internal": _money(in_p[column].sum()),
    })


@deriver
def last_full_quarter_revenue(t: Tables, *, measure: str, start: str, end: str, as_of: str) -> Derived:
    """'Last quarter' relative to the snapshot's as_of: the most recent fully
    elapsed calendar quarter. Wrong paths: the current partial quarter, a
    trailing 90 days, and a different measure for the same quarter."""
    rev = five_revenues(dict(t), start, end)
    cur_q_start = _ts(as_of).to_period("Q").start_time.strftime("%Y-%m-%d")
    trailing_start = (_ts(as_of) - pd.Timedelta(days=89)).strftime("%Y-%m-%d")
    return Derived(
        value=rev[measure],
        silent_fail={
            "current_partial_quarter": five_revenues(dict(t), cur_q_start, as_of)[measure],
            "trailing_90_days": five_revenues(dict(t), trailing_start, as_of)[measure],
            **{f"same_quarter_{m}": rev[m] for m in MEASURES if m != measure},
        },
    )


@deriver
def ytd_growth(t: Tables, *, measure: str, as_of: str) -> Derived:
    """Year-to-date through as_of vs the same calendar span a year earlier.
    Wrong path: comparing the partial year to the full prior year."""
    end = _ts(as_of)
    start = pd.Timestamp(year=end.year, month=1, day=1)
    prior_start = pd.Timestamp(year=end.year - 1, month=1, day=1)
    prior_end = end - pd.DateOffset(years=1)
    f = "%Y-%m-%d"
    ytd = five_revenues(dict(t), start.strftime(f), end.strftime(f))[measure]
    prior = five_revenues(dict(t), prior_start.strftime(f), prior_end.strftime(f))[measure]
    prior_full = five_revenues(dict(t), prior_start.strftime(f), f"{end.year - 1}-12-31")[measure]
    return Derived(
        value=_ratio(ytd / prior - 1),
        components={"ytd": ytd, "prior_ytd": prior},
        silent_fail={
            "growth_vs_full_prior_year": _ratio(ytd / prior_full - 1),
            "prior_full_year": prior_full,
        },
    )


@deriver
def five_revenues_by_quarter(t: Tables, *, start: str, end: str) -> Derived:
    quarters = pd.period_range(start, end, freq="Q")
    rows = []
    for q in quarters:
        rev = five_revenues(dict(t), q.start_time.strftime("%Y-%m-%d"), q.end_time.strftime("%Y-%m-%d"))
        rows.append([str(q), *(rev[m] for m in MEASURES)])
    return Derived(columns=["quarter", *MEASURES], rows=rows)


@deriver
def orders_count(t: Tables, *, start: str, end: str) -> Derived:
    """Eligible orders in a window. Wrong path: the unfiltered staging count."""
    o = orders(t)
    raw = all_orders(t)
    return Derived(
        value=int(_between(o.order_date, start, end).sum()),
        silent_fail={"staging_including_test_and_internal": int(_between(raw.order_date, start, end).sum())},
    )


@deriver
def marketplace_take(t: Tables, *, start: str, end: str) -> Derived:
    """Marketplace commission (net_amount) on orders placed in the window.
    Wrong path: the retail value (gross_amount, i.e. marketplace GMV)."""
    o = orders(t)
    m = o[(o.channel == "marketplace") & _between(o.order_date, start, end)]
    return Derived(
        value=_money(m.net_amount.sum()),
        components={"effective_take_rate": _ratio(m.net_amount.sum() / m.gross_amount.sum())},
        silent_fail={"marketplace_gmv": _money(m.gross_amount.sum())},
    )


@deriver
def d2c_gmv_by_year(t: Tables, *, start: str, end: str) -> Derived:
    """d2c GMV per calendar year at canonical channel grain. Wrong path: grouping
    on the raw label, which drops every pre-rename ('direct') order."""
    o = orders(t)
    o = o[_between(o.order_date, start, end)]
    years = range(_ts(start).year, _ts(end).year + 1)
    canon = o[o.channel == "d2c"].groupby(o.order_date.dt.year).gross_amount.sum()
    raw = o[o.channel_raw == "d2c"].groupby(o.order_date.dt.year).gross_amount.sum()
    return Derived(
        columns=["year", "d2c_gmv"],
        rows=[[y, _money(canon.get(y, 0.0))] for y in years],
        silent_fail={f"raw_label_d2c_gmv_{y}": _money(raw.get(y, 0.0))
                     for y in years if round(raw.get(y, 0.0), 2) != round(canon.get(y, 0.0), 2)},
    )


@deriver
def recognized_by_channel(t: Tables, *, start: str, end: str) -> Derived:
    """Recognized revenue split by the canonical channel of the originating
    order. Wrong paths: order-date net_amount by channel (the fct_orders
    shortcut), and the unfiltered split the executive dashboard draws."""
    o = orders(t)
    rec = t["app_db__revenue_recognition"]
    rec = rec[_between(rec.recognition_date, start, end)]
    split = rec.merge(o[["order_id", "channel"]], on="order_id", how="inner").groupby("channel").amount.sum()
    by_order_date = o[_between(o.order_date, start, end)].groupby("channel").net_amount.sum()
    raw = rec.merge(all_orders(t)[["order_id", "channel"]], on="order_id").assign(
        channel=lambda d: canonical_channel(d.channel)).groupby("channel").amount.sum()
    chans = sorted(split.index)
    return Derived(
        columns=["channel", "recognized_revenue"],
        rows=[[c, _money(split[c])] for c in chans],
        silent_fail={
            **{f"order_date_net_amount_{c}": _money(by_order_date.get(c, 0.0)) for c in chans},
            **{f"unfiltered_{c}": _money(raw.get(c, 0.0)) for c in chans
               if _money(raw.get(c, 0.0)) != _money(split[c])},
        },
    )


@deriver
def recognized_by_channel_by_quarter(t: Tables, *, start: str, end: str, as_of: str) -> Derived:
    """Recognized revenue per calendar quarter, split by the canonical channel of
    the originating order, with each channel's share of the quarter (the mix).
    start/end bound complete quarters. Wrong paths: order-date net_amount by
    channel (billed upfront, so subscription renewals make the mix lurch), GMV by
    channel (marketplace at gross instead of take), and a window rolled forward
    to include the partial quarter containing as_of."""
    o = orders(t)
    rec = t["app_db__revenue_recognition"].merge(o[["order_id", "channel"]], on="order_id", how="inner")

    def split(lo, hi):
        rows = []
        for q in pd.period_range(lo, hi, freq="Q"):
            qs, qe = q.start_time.strftime("%Y-%m-%d"), q.end_time.strftime("%Y-%m-%d")
            r = rec[_between(rec.recognition_date, qs, qe)].groupby("channel").amount.sum()
            w = o[_between(o.order_date, qs, qe)]
            net, gross = w.groupby("channel").net_amount.sum(), w.groupby("channel").gross_amount.sum()
            for c in sorted(set(r.index) | set(net.index)):
                rows.append((str(q), c, r.get(c, 0.0), net.get(c, 0.0), gross.get(c, 0.0)))
        df = pd.DataFrame(rows, columns=["quarter", "channel", "recognized", "net", "gross"])
        for m in ("recognized", "net", "gross"):
            df[f"{m}_share"] = df[m] / df.groupby("quarter")[m].transform("sum")
        return df

    df = split(_ts(start), _ts(end))
    n_q = len(pd.period_range(start, end, freq="Q"))
    cur_q = _ts(as_of).to_period("Q")
    rolled = split((cur_q - (n_q - 1)).start_time, _ts(as_of))

    silent = {}
    for r in df.itertuples():
        silent[f"order_date_net_amount_{r.quarter}_{r.channel}"] = _money(r.net)
        silent[f"order_date_net_share_{r.quarter}_{r.channel}"] = _ratio(r.net_share)
        silent[f"gmv_share_{r.quarter}_{r.channel}"] = _ratio(r.gross_share)
    for r in rolled[rolled.quarter == str(cur_q)].itertuples():
        silent[f"partial_quarter_{r.quarter}_{r.channel}"] = _money(r.recognized)

    return Derived(
        columns=["quarter", "channel", "recognized_revenue", "share_of_quarter"],
        rows=[[r.quarter, r.channel, _money(r.recognized), _ratio(r.recognized_share)] for r in df.itertuples()],
        silent_fail=silent,
    )


# --------------------------------------------------------------------------- identity

@deriver
def identity(t: Tables, *, measure: str, as_of: str, components: list[str] | None = None,
             silent_fail: list[str] | None = None) -> Derived:
    """Pass-through to generators/identity_measures.py (the identity reference)."""
    m = derive_identity_measures(dict(t), as_of=as_of, gmv_start="2024-01-01", gmv_end="2024-12-31")
    return Derived(
        value=m[measure],
        components={k: m[k] for k in components or []},
        silent_fail={k: m[k] for k in silent_fail or []},
    )


# --------------------------------------------------------------------------- customers

@deriver
def current_customers(t: Tables, *, start: str, end: str) -> Derived:
    """Canonical customers with >= 1 eligible order in the trailing window
    (twelve full calendar months ending at the snapshot month). Wrong paths:
    including test/internal accounts, summing per-channel counts, and counting
    every app profile ever created."""
    o = orders(t)
    w = o[_between(o.order_date, start, end)]
    raw = all_orders(t)
    rw = raw[_between(raw.order_date, start, end)]
    c = t["app_db__customers"]
    return Derived(
        value=int(w.customer_id.nunique()),
        silent_fail={
            "including_test_and_internal": int(rw.customer_id.nunique()),
            "sum_of_channel_counts": int(w.groupby("channel").customer_id.nunique().sum()),
            "all_profiles_created": int((_day(c.created_at) <= _ts(end)).sum()),
        },
    )


@deriver
def new_customers(t: Tables, *, start: str, end: str) -> Derived:
    """Canonical customers whose first-ever eligible order is in the window.
    Wrong paths: app profiles created in the window, and first orders counted
    per channel (a returning customer's first purchase in a new channel)."""
    o = orders(t)
    first = o.groupby("customer_id").order_date.min()
    first_by_channel = o.groupby(["customer_id", "channel"]).order_date.min()
    c = t["app_db__customers"]
    return Derived(
        value=int(_between(first, start, end).sum()),
        silent_fail={
            "profiles_created": int(_between(c.created_at, start, end).sum()),
            "first_order_per_channel": int(_between(first_by_channel, start, end).sum()),
        },
    )


@deriver
def multi_channel_customers(t: Tables, *, start: str, end: str) -> Derived:
    """Customers with orders in >= 2 canonical channels in the window. Wrong
    path: raw labels, where a pre-rename 'direct' order and a later 'd2c'
    order look like two channels."""
    o = orders(t)
    w = o[_between(o.order_date, start, end)]
    return Derived(
        value=int((w.groupby("customer_id").channel.nunique() >= 2).sum()),
        silent_fail={"raw_channel_labels": int((w.groupby("customer_id").channel_raw.nunique() >= 2).sum())},
    )


# --------------------------------------------------------------------------- subscriptions

@deriver
def active_subscribers(t: Tables, *, at: str) -> Derived:
    """Customers with a term containing `at`. Wrong paths: status = 'active',
    current-generation plans only, counting terms, and counting seats."""
    s = subscription_terms(t)
    a = _active_at(s, at)
    return Derived(
        value=int(a.customer_id.nunique()),
        silent_fail={
            "status_active": int(s.loc[s.status == "active", "customer_id"].nunique()),
            "current_generation_only": int(a.loc[a.is_current, "customer_id"].nunique()),
            "seats": int(a.seats.sum()),
        },
    )


@deriver
def active_subscribers_by_generation(t: Tables, *, at: str) -> Derived:
    s = subscription_terms(t)
    a = _active_at(s, at)
    g = a.groupby("plan_generation").agg(subs=("customer_id", "nunique"), acv=("acv", "sum"))
    return Derived(
        columns=["plan_generation", "active_subscribers", "acv_under_contract"],
        rows=[[int(k), int(r.subs), _money(r.acv)] for k, r in g.iterrows()],
        silent_fail={"current_generation_only_total": int(a.loc[a.is_current, "customer_id"].nunique())},
    )


@deriver
def renewal_rate(t: Tables, *, start: str, end: str) -> Derived:
    """Renewed / (renewed + churned) among terms ending in the window, counted
    in terms. Wrong paths: an ACV-weighted rate (dollar retention, a different
    metric), and renewals as a share of all terms started in the window."""
    s = subscription_terms(t)
    ended = s[_between(s.term_end, start, end) & s.status.isin(["renewed", "churned"])]
    started = s[_between(s.term_start, start, end)]
    return Derived(
        value=_ratio((ended.status == "renewed").mean()),
        components={"terms_decided": int(len(ended)), "churned_terms": int((ended.status == "churned").sum())},
        silent_fail={
            "acv_weighted": _ratio(ended.loc[ended.status == "renewed", "acv"].sum() / ended.acv.sum()),
            "renewal_share_of_terms_started": _ratio((~started.is_first_term).mean()),
        },
    )


@deriver
def new_subscriptions(t: Tables, *, start: str, end: str) -> Derived:
    """First terms started in the window. Wrong path: every term started
    (renewals are new term rows)."""
    s = subscription_terms(t)
    started = s[_between(s.term_start, start, end)]
    return Derived(
        value=int(started.is_first_term.sum()),
        components={"new_acv": _money(started.loc[started.is_first_term, "acv"].sum())},
        silent_fail={"all_terms_started": int(len(started))},
    )


@deriver
def churn_by_segment_quarter(t: Tables, *, start: str, end: str) -> Derived:
    s = subscription_terms(t)
    e = s[_between(s.term_end, start, end) & s.status.isin(["renewed", "churned"])].copy()
    e["quarter"] = _quarter_label(e.term_end_date)
    rows = []
    for (q, seg), g in e.groupby(["quarter", "segment"]):
        churned = int((g.status == "churned").sum())
        rows.append([q, seg, int(len(g)), churned, _ratio(churned / len(g))])
    return Derived(columns=["quarter", "segment", "terms_up_for_renewal", "churned", "churn_rate"], rows=rows)


@deriver
def avg_price_per_seat_active(t: Tables, *, at: str, plan_id: str) -> Derived:
    """Seat-weighted price actually paid on a plan's active terms at `at`.
    Wrong path: the plan's current catalog price (dim_plans)."""
    s = subscription_terms(t)
    a = _active_at(s, at)
    a = a[a.plan_id == plan_id]
    prices = t["app_db__plan_prices"]
    p = prices[prices.plan_id == plan_id].sort_values("effective_from")
    return Derived(
        value=_money(a.acv.sum() / a.seats.sum()),
        silent_fail={"current_catalog_price": float(p.annual_price_per_seat.iloc[-1])},
    )


# --------------------------------------------------------------------------- marketing

def _new_d2c(o: pd.DataFrame, start: str, end: str) -> int:
    return int((o.is_first_order & (o.channel == "d2c") & _between(o.order_date, start, end)).sum())


@deriver
def d2c_cac(t: Tables, *, start: str, end: str) -> Derived:
    """Paid-media spend / new d2c customers (first-ever order in d2c). Wrong
    paths: the platforms' self-reported conversions, and the fct_marketing_spend
    day total summed across platform rows (a fanout)."""
    o = orders(t)
    ads = t["ads__daily_spend"]
    a = ads[_between(ads.spend_date, start, end)]
    spend = float(a.spend_usd.sum())
    new = _new_d2c(o, start, end)
    fanned = _fanned_new_d2c(t, start, end)
    return Derived(
        value=_money(spend / new),
        components={"ad_spend": _money(spend), "new_d2c_customers": new},
        silent_fail={
            "per_platform_reported_conversions": _money(spend / a.reported_conversions.sum()),
            "fanned_out_attributed_customers": _money(spend / fanned),
        },
    )


def _fanned_new_d2c(t: Tables, start: str, end: str) -> int:
    o = orders(t)
    first = o[o.is_first_order & (o.channel == "d2c")]
    per_day = _day(first.order_date).value_counts()
    ads = t["ads__daily_spend"]
    a = ads[_between(ads.spend_date, start, end)]
    return int(_day(a.spend_date).map(per_day).fillna(0).sum())


@deriver
def new_d2c_customers(t: Tables, *, start: str, end: str) -> Derived:
    """New d2c customers. Wrong paths: fct_marketing_spend's day total summed
    over platform rows, and platform-reported conversions."""
    o = orders(t)
    ads = t["ads__daily_spend"]
    a = ads[_between(ads.spend_date, start, end)]
    return Derived(
        value=_new_d2c(o, start, end),
        silent_fail={
            "fanned_out_marketing_spend_rows": _fanned_new_d2c(t, start, end),
            "platform_reported_conversions": int(a.reported_conversions.sum()),
        },
    )


@deriver
def ad_spend_by_platform(t: Tables, *, start: str, end: str) -> Derived:
    ads = t["ads__daily_spend"]
    a = ads[_between(ads.spend_date, start, end)]
    g = a.groupby("platform").spend_usd.sum()
    return Derived(columns=["platform", "spend_usd"], rows=[[p, _money(v)] for p, v in g.items()])


@deriver
def promo_usage(t: Tables, *, promo_code: str, start: str, end: str) -> Derived:
    """Orders carrying a promo code and the line-level discount dollars on them."""
    o = orders(t)
    m = o[(o.promo_code == promo_code) & _between(o.order_date, start, end)]
    lines = t["app_db__order_lines"]
    ln = lines[lines.order_id.isin(m.order_id)]
    # Summed unrounded and rounded once: per-line rounding differs between
    # pandas (float, half-to-even) and SQL (decimal, half-up) by cents.
    discount = (ln.quantity * ln.unit_price * ln.discount_pct).sum()
    return Derived(value=int(len(m)), components={"discount_dollars": _money(discount),
                                                  "promo_gmv": _money(m.gross_amount.sum())})


@deriver
def category_margin(t: Tables, *, start: str, end: str) -> Derived:
    """Consumer line revenue, cost and gross margin by category (fct_order_lines)."""
    o = orders(t)
    lines = t["app_db__order_lines"].merge(t["app_db__products"][["sku", "category", "unit_cost"]], on="sku")
    lines = lines.merge(o[["order_id", "order_date"]], on="order_id")
    lines = lines[_between(lines.order_date, start, end)]
    lines["cost"] = lines.quantity * lines.unit_cost
    g = lines.groupby("category").agg(rev=("line_amount", "sum"), cost=("cost", "sum"))
    return Derived(
        columns=["category", "line_revenue", "gross_margin", "margin_pct"],
        rows=[[c, _money(r.rev), _money(r.rev - r.cost), _ratio((r.rev - r.cost) / r.rev)] for c, r in g.iterrows()],
    )


@deriver
def gmv_of_orders_with_category(t: Tables, *, category: str, start: str, end: str) -> Derived:
    """GMV of orders containing at least one line in `category`. Wrong path:
    joining lines to orders and summing the order's gross_amount once per line."""
    o = orders(t)
    o = o[_between(o.order_date, start, end)]
    lines = t["app_db__order_lines"].merge(t["app_db__products"][["sku", "category"]], on="sku")
    hit = lines[lines.category == category]
    joined = hit.merge(o[["order_id", "gross_amount"]], on="order_id")
    return Derived(
        value=_money(o[o.order_id.isin(hit.order_id)].gross_amount.sum()),
        silent_fail={
            "summed_per_matching_line": _money(joined.gross_amount.sum()),
            "category_line_amount_only": _money(joined.line_amount.sum()),
        },
    )


# --------------------------------------------------------------------------- operations

@deriver
def open_tickets_at(t: Tables, *, at: str) -> Derived:
    """Tickets created on or before `at` and not resolved by then. Wrong paths:
    today's status = 'open' (as of the snapshot, not `at`), and tickets
    created in the month."""
    k = t["zendesk__tickets"]
    d = _ts(at)
    created = _day(k.created_at) <= d
    unresolved = k.resolved_at.isna() | (_day(k.resolved_at) > d)
    month_start = d.to_period("M").start_time
    return Derived(
        value=int((created & unresolved).sum()),
        silent_fail={
            "status_open_at_snapshot": int((k.status == "open").sum()),
            "created_in_month": int(((_day(k.created_at) >= month_start) & created).sum()),
        },
    )


@deriver
def shipments_in_transit_at(t: Tables, *, at: str) -> Derived:
    """Shipments due on or before `at` and not received by then. Wrong path:
    status = 'in_transit' at the snapshot."""
    s = t["erp__supplier_shipments"]
    d = _ts(at)
    due = _day(s.expected_date) <= d
    pending = s.received_date.isna() | (_day(s.received_date) > d)
    return Derived(
        value=int((due & pending).sum()),
        silent_fail={"status_in_transit_at_snapshot": int((s.status == "in_transit").sum())},
    )


@deriver
def tickets_by_category(t: Tables, *, start: str, end: str) -> Derived:
    k = t["zendesk__tickets"]
    g = k[_between(k.created_at, start, end)].groupby("category").size()
    return Derived(columns=["category", "tickets"], rows=[[c, int(n)] for c, n in g.items()])


# --------------------------------------------------------------------------- diagnostics

@deriver
def event_evidence(t: Tables, *, event: str, keys: list[str]) -> Derived:
    """The derived figures a diagnostic judge checks, from generators/event_measures.py."""
    from generators.event_measures import derive_event_measures

    m = derive_event_measures(t)[event]
    return Derived(evidence={k: m[k] for k in keys})


# --------------------------------------------------------------------------- unanswerable

@deriver
def refusal(t: Tables) -> Derived:
    """No gold number: the data cannot answer. Absent-term checks live in the builder."""
    return Derived()


def schema_columns(t: Tables) -> set[str]:
    """Every raw column name, lower-cased (for the unanswerable absent-term check)."""
    return {c.lower() for df in t.values() for c in df.columns} | {n.lower() for n in t}


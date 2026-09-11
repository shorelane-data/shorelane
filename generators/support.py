"""Zendesk support tickets (stream 28), generated AFTER identity so requesters are
keyed by source-native ids (Salesforce for business accounts, Stripe for consumers).

  zendesk__tickets  one row per ticket: requester (source system + id), created_at,
                    category, priority, status, resolved_at

The enterprise-churn event (config.EVENTS: enterprise_churn_2022_q4) is planted here
as a burst of high-priority billing tickets from enterprise subscribers in the
months before their Q4 2022 renewals fail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from generators.common import make_rng

_CONSUMER_CATEGORIES = (("shipping", 0.45), ("product", 0.30), ("billing", 0.15), ("account", 0.10))
_BUSINESS_CATEGORIES = (("technical", 0.40), ("billing", 0.30), ("onboarding", 0.20), ("account", 0.10))
_PRIORITIES = (("low", 0.45), ("normal", 0.40), ("high", 0.12), ("urgent", 0.03))


def _pick(rng: np.random.Generator, table, n: int) -> np.ndarray:
    labels = [t[0] for t in table]
    probs = np.array([t[1] for t in table]) / sum(t[1] for t in table)
    return rng.choice(labels, size=n, p=probs)


def _requester_lookup(tables: dict[str, pd.DataFrame]) -> tuple[pd.Series, pd.DataFrame]:
    xw = tables["app_db__customer_id_crosswalk"]
    sf = xw[xw.source_system == "salesforce"].drop_duplicates("app_db_customer_id")
    salesforce_by_app = pd.Series(sf.source_customer_id.values, index=sf.app_db_customer_id.values)
    stripe = xw[xw.source_system == "stripe"].merge(
        tables["stripe__customers"][["stripe_customer_id", "created_at"]],
        left_on="source_customer_id", right_on="stripe_customer_id", how="left",
    )[["app_db_customer_id", "source_customer_id", "created_at"]]
    return salesforce_by_app, stripe.sort_values(["app_db_customer_id", "created_at"], kind="stable")


def _stripe_id_at(stripe: pd.DataFrame, app_ids: np.ndarray, dates: np.ndarray) -> np.ndarray:
    """Latest Stripe alias created on or before each date (None if unresolved)."""
    out = np.full(len(app_ids), None, dtype=object)
    groups = {k: (g.created_at.values.astype("datetime64[D]"), g.source_customer_id.values)
              for k, g in stripe.groupby("app_db_customer_id")}
    for i, (app_id, d) in enumerate(zip(app_ids, dates.astype("datetime64[D]"))):
        g = groups.get(app_id)
        if g is None:
            continue
        pos = np.searchsorted(g[0], d, side="right") - 1
        out[i] = g[1][max(pos, 0)]
    return out


def generate(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    rng = make_rng(stream=28)
    orders = tables["app_db__orders"]
    customers = tables["app_db__customers"].set_index("app_db_customer_id")
    subs = tables["app_db__subscriptions"]
    end = np.datetime64(config.END_DATE)

    # Consumer-order tickets.
    consumer = orders[orders.channel != "business_subscription"]
    hit = rng.random(len(consumer)) < config.TICKET_RATE_CONSUMER
    c = consumer[hit]
    c_dates = c.order_date.values.astype("datetime64[D]") + rng.integers(1, 21, size=len(c)).astype("timedelta64[D]")
    c_frame = pd.DataFrame({
        "app_db_customer_id": c.customer_id.values,
        "created_at": c_dates,
        "category": _pick(rng, _CONSUMER_CATEGORIES, len(c)),
        "priority": _pick(rng, _PRIORITIES, len(c)),
        "related_order_id": c.order_id.values,
        "related_subscription_id": None,
    })

    # Subscription-term tickets.
    counts = rng.poisson(config.TICKETS_PER_SUBSCRIPTION_TERM, size=len(subs))
    idx = np.repeat(np.arange(len(subs)), counts)
    span = (subs.term_end.values.astype("datetime64[D]") - subs.term_start.values.astype("datetime64[D]")).astype(int)
    offs = np.floor(rng.random(len(idx)) * (span[idx] + 1)).astype(int)
    s_dates = subs.term_start.values.astype("datetime64[D]")[idx] + offs.astype("timedelta64[D]")
    s_frame = pd.DataFrame({
        "app_db_customer_id": subs.customer_id.values[idx],
        "created_at": s_dates,
        "category": _pick(rng, _BUSINESS_CATEGORIES, len(idx)),
        "priority": _pick(rng, _PRIORITIES, len(idx)),
        "related_order_id": None,
        "related_subscription_id": subs.subscription_id.values[idx],
    })

    # Seeded event: enterprise billing-ticket burst.
    frames = [c_frame, s_frame]
    segment = customers.segment
    for ev in config.EVENTS:
        spec = ev["effect"].get("tickets")
        if not spec:
            continue
        w0, w1 = np.datetime64(spec["start"]), np.datetime64(spec["end"])
        active = subs[(subs.term_start.values.astype("datetime64[D]") <= w1)
                      & (subs.term_end.values.astype("datetime64[D]") >= w0)]
        active = active[segment.reindex(active.customer_id.values).values == spec["segment"]]
        extra = rng.poisson(spec["mean_extra"], size=len(active))
        eidx = np.repeat(np.arange(len(active)), extra)
        e_dates = w0 + np.floor(rng.random(len(eidx)) * ((w1 - w0).astype(int) + 1)).astype(int).astype("timedelta64[D]")
        frames.append(pd.DataFrame({
            "app_db_customer_id": active.customer_id.values[eidx],
            "created_at": e_dates,
            "category": spec["category"],
            "priority": rng.choice(["high", "urgent"], size=len(eidx), p=[0.7, 0.3]),
            "related_order_id": None,
            "related_subscription_id": active.subscription_id.values[eidx],
        }))

    t = pd.concat(frames, ignore_index=True)
    t = t[t.created_at <= end].copy()
    t["created_at"] = pd.to_datetime(t["created_at"])
    t = t.sort_values(["created_at", "app_db_customer_id", "related_order_id", "related_subscription_id"],
                      kind="stable", ignore_index=True)
    t["ticket_id"] = [f"zd_{i + 1:07d}" for i in range(len(t))]

    resolve_days = rng.integers(0, 15, size=len(t))
    t["resolved_at"] = t["created_at"] + pd.to_timedelta(resolve_days, unit="D")
    t.loc[t.resolved_at > pd.Timestamp(config.END_DATE), "resolved_at"] = pd.NaT
    t["status"] = np.where(t.resolved_at.isna(), "open", "solved")

    # Requester identity: Salesforce for business segments, Stripe for consumers,
    # falling back to the app id where the crosswalk cannot resolve.
    salesforce_by_app, stripe = _requester_lookup(tables)
    is_business = segment.reindex(t.app_db_customer_id.values).isin(["smb", "enterprise"]).values
    sf_ids = salesforce_by_app.reindex(t.app_db_customer_id.values).values
    st_ids = _stripe_id_at(stripe, t.app_db_customer_id.values, t.created_at.values)
    system = np.where(is_business & pd.notna(sf_ids), "salesforce",
                      np.where(~is_business & pd.notna(st_ids), "stripe", "app_db"))
    source_id = np.where(system == "salesforce", sf_ids,
                         np.where(system == "stripe", st_ids, t.app_db_customer_id.values))
    t["requester_source_system"] = system
    t["requester_source_id"] = pd.Series(source_id, dtype="string")
    for col in ("related_order_id", "related_subscription_id"):
        t[col] = t[col].astype("string")

    tickets = t[["ticket_id", "requester_source_system", "requester_source_id", "created_at",
                 "category", "priority", "status", "resolved_at",
                 "related_order_id", "related_subscription_id"]].reset_index(drop=True)
    return {**tables, "zendesk__tickets": tickets}

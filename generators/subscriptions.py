"""Business subscriptions: plans, price history, and per-term rows (stream 21).

  app_db__plans          one row per plan across three grandfathered generations
  app_db__plan_prices    price history per plan (the 2025 gen-3 increase lands here)
  app_db__subscriptions  one row per 12-month TERM; renewals chain via
                         renewed_from_subscription_id. Only the final term of a
                         subscription is 'active' or 'churned'; earlier terms are 'renewed'.

Each term produces one business_subscription order (in generators/orders.py) whose
amount is seats x the plan's price per seat effective at term start. Customers stay
on their original plan at renewal (grandfathering) — the debt-item-#4 trap: only gen-3
plans are `is_current`, but every generation is a live subscription base.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from generators import timeline
from generators.common import make_rng, triangular


def generate_plans() -> tuple[pd.DataFrame, pd.DataFrame]:
    plan_rows, price_rows = [], []
    price_events = [ev["effect"]["price"] for ev in config.EVENTS if "price" in ev["effect"]]
    for gen, spec in config.PLAN_GENERATIONS.items():
        for plan_id, (name, price, tier) in spec["plans"].items():
            plan_rows.append((plan_id, name, gen, tier, pd.Timestamp(spec["launched_at"]),
                              pd.Timestamp(spec["retired_at"]) if spec["retired_at"] else pd.NaT,
                              spec["retired_at"] is None))
            price_rows.append((plan_id, pd.Timestamp(spec["launched_at"]), price))
            for pe in price_events:
                if pe["plan_generation"] == gen:
                    price_rows.append((plan_id, pd.Timestamp(pe["effective_from"]),
                                       round(price * pe["factor"], 2)))
    plans = pd.DataFrame(plan_rows, columns=["plan_id", "plan_name", "plan_generation", "tier",
                                             "launched_at", "retired_at", "is_current"])
    prices = pd.DataFrame(price_rows, columns=["plan_id", "effective_from", "annual_price_per_seat"])
    prices = prices.sort_values(["plan_id", "effective_from"], kind="stable", ignore_index=True)
    return plans, prices


def _price_at(prices: pd.DataFrame, plan_ids: np.ndarray, dates: np.ndarray) -> np.ndarray:
    out = np.empty(len(plan_ids), dtype=float)
    for plan_id, grp in prices.groupby("plan_id"):
        mask = plan_ids == plan_id
        if not mask.any():
            continue
        eff = grp["effective_from"].values.astype("datetime64[D]")
        pos = np.searchsorted(eff, dates[mask].astype("datetime64[D]"), side="right") - 1
        out[mask] = grp["annual_price_per_seat"].values[np.clip(pos, 0, len(eff) - 1)]
    return out


def _plan_for(gen_spec: dict, tier: str, rng: np.random.Generator) -> str:
    candidates = [pid for pid, (_, _, t) in gen_spec["plans"].items() if t == tier]
    return candidates[int(rng.integers(len(candidates)))]


def _generation_at(date: np.datetime64) -> dict:
    for gen, spec in config.PLAN_GENERATIONS.items():
        lo = np.datetime64(spec["launched_at"])
        hi = np.datetime64(spec["retired_at"]) if spec["retired_at"] else np.datetime64(config.END_DATE)
        if lo <= date <= hi:
            return spec
    raise ValueError(f"no plan generation covers {date}")


def generate() -> dict[str, pd.DataFrame | np.ndarray]:
    """Return plans, prices, and the term table keyed by business-customer index."""
    rng = make_rng(stream=21)
    plans, prices = generate_plans()
    n = config.N_NEW_SUBSCRIPTIONS
    starts = timeline.draw_dates(rng, "business_subscription", n)
    segment = np.where(rng.random(n) < config.ENTERPRISE_SHARE_OF_NEW_SUBSCRIPTIONS,
                       "enterprise", "smb")
    plan_ids = np.array([_plan_for(_generation_at(d), s, rng) for d, s in zip(starts, segment)],
                        dtype=object)
    seats = np.empty(n, dtype=int)
    for seg, (lo, mode, hi) in config.SEATS.items():
        m = segment == seg
        seats[m] = np.round(triangular(rng, lo, mode, hi, int(m.sum()))).astype(int)

    end = np.datetime64(config.END_DATE)
    term_rows = []          # (biz_idx, term_index, term_start)
    alive = np.ones(n, dtype=bool)
    k = 0
    while alive.any():
        term_start = (pd.DatetimeIndex(starts) + pd.DateOffset(months=config.SUBSCRIPTION_TERM_MONTHS * k)).values.astype("datetime64[D]")
        due = alive & (term_start <= end)
        if k > 0:
            hazard = timeline.renewal_churn_hazard(term_start, segment)
            churned = rng.random(n) < hazard      # one draw per sub per opportunity (fixed order)
            due &= ~churned
        alive = due
        for i in np.flatnonzero(due):
            term_rows.append((i, k, term_start[i]))
        k += 1

    terms = pd.DataFrame(term_rows, columns=["biz_idx", "term_index", "term_start"])
    terms["term_start"] = pd.to_datetime(terms["term_start"])
    terms = terms.sort_values(["term_start", "biz_idx"], kind="stable", ignore_index=True)
    terms["segment"] = segment[terms.biz_idx.values]
    terms["plan_id"] = plan_ids[terms.biz_idx.values]
    terms["seats"] = seats[terms.biz_idx.values]
    terms["term_end"] = terms["term_start"] + pd.DateOffset(months=config.SUBSCRIPTION_TERM_MONTHS) - pd.Timedelta(days=1)
    terms["price_per_seat"] = _price_at(prices, terms.plan_id.values, terms.term_start.values)
    terms["acv"] = np.round(terms.seats * terms.price_per_seat, 2)
    terms["subscription_id"] = [f"sub_{i:07d}" for i in range(len(terms))]

    # Renewal chain + status. Last term: 'churned' if a renewal was possible and
    # rejected, 'active' if the next term would start after END_DATE.
    prev = terms.groupby("biz_idx")["subscription_id"].shift(1)
    terms["renewed_from_subscription_id"] = prev.astype("string")
    last_term = terms.groupby("biz_idx")["term_index"].transform("max") == terms["term_index"]
    next_start = terms["term_start"] + pd.DateOffset(months=config.SUBSCRIPTION_TERM_MONTHS)
    status = np.where(~last_term, "renewed",
                      np.where(next_start <= pd.Timestamp(config.END_DATE), "churned", "active"))
    terms["status"] = status
    terms["cancelled_at"] = pd.NaT
    terms.loc[terms.status == "churned", "cancelled_at"] = terms.loc[terms.status == "churned", "term_end"]
    terms["cancelled_at"] = pd.to_datetime(terms["cancelled_at"])

    return {
        "plans": plans,
        "prices": prices,
        "terms": terms,
        "business_created_at": pd.to_datetime(starts),   # index == biz_idx
        "business_segment": segment,
    }

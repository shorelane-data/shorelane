"""Order-intensity curve: base x growth x seasonality x seeded-event multipliers.

Every dated draw in v4 (consumer orders, subscription starts, sign-ups, ad spend,
shipments) samples days in proportion to `intensity(channel)`, so growth,
seasonality, and the EVENTS calendar are visible in every series the same way.
The functions here are pure (no RNG); callers pass their own stream.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from generators.common import in_window


def day_range() -> pd.DatetimeIndex:
    return pd.date_range(config.START_DATE, config.END_DATE, freq="D")


def growth(days: pd.DatetimeIndex) -> np.ndarray:
    years = (days - pd.Timestamp(config.START_DATE)).days.to_numpy() / 365.25
    return (1.0 + config.GROWTH_RATE_ANNUAL) ** years


def seasonality(days: pd.DatetimeIndex, table: dict[int, float]) -> np.ndarray:
    return np.array([table[m] for m in days.month], dtype=float)


def event_volume_multiplier(days, channel: str) -> np.ndarray:
    """Product of every event's volume effect on `channel` over the given days."""
    mult = np.ones(len(days), dtype=float)
    for ev in config.EVENTS:
        vol = ev["effect"].get("volume", {})
        if channel in vol:
            mult[in_window(days, ev["start"], ev["end"])] *= vol[channel]
    return mult


def intensity(channel: str) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Daily relative order intensity for a channel over the whole timeline."""
    days = day_range()
    table = (config.SEASONALITY_SUBSCRIPTION if channel == "business_subscription"
             else config.SEASONALITY_CONSUMER)
    w = growth(days) * seasonality(days, table) * event_volume_multiplier(days, channel)
    return days, w


def draw_dates(rng: np.random.Generator, channel: str, n: int,
               start: str | None = None, end: str | None = None) -> np.ndarray:
    """Draw n sorted dates (datetime64[D]) in proportion to the channel intensity,
    optionally restricted to [start, end]."""
    days, w = intensity(channel)
    w = w.copy()
    if start is not None:
        w[days < pd.Timestamp(start)] = 0.0
    if end is not None:
        w[days > pd.Timestamp(end)] = 0.0
    idx = rng.choice(len(days), size=n, p=w / w.sum())
    return np.sort(days.values[idx].astype("datetime64[D]"))


def new_customer_share(dates, channel: str) -> np.ndarray:
    """Per-order probability that the order comes from a brand-new customer."""
    share = np.full(len(dates), config.NEW_CUSTOMER_SHARE[channel], dtype=float)
    for ev in config.EVENTS:
        eff = ev["effect"].get("new_customer_share", {})
        if channel in eff:
            share[in_window(dates, ev["start"], ev["end"])] *= eff[channel]
    return share


def category_weights(dates) -> np.ndarray:
    """(n_dates, n_categories) category-mix weights with event category effects."""
    cats = list(config.CATEGORIES)
    base = np.array([config.CATEGORIES[c][0] for c in cats], dtype=float)
    w = np.tile(base, (len(dates), 1))
    for ev in config.EVENTS:
        shares = ev["effect"].get("category_share", {})
        if not shares:
            continue
        mask = in_window(dates, ev["start"], ev["end"])
        for cat, factor in shares.items():
            w[mask, cats.index(cat)] *= factor
    return w / w.sum(axis=1, keepdims=True)


def ad_spend_multiplier(days) -> np.ndarray:
    mult = np.ones(len(days), dtype=float)
    for ev in config.EVENTS:
        factor = ev["effect"].get("ad_spend")
        if factor is not None:
            mult[in_window(days, ev["start"], ev["end"])] *= factor
    return mult


def renewal_churn_hazard(renewal_dates, segments: np.ndarray) -> np.ndarray:
    """Per-renewal churn probability: segment base hazard x event overrides."""
    hazard = np.array([config.RENEWAL_CHURN_HAZARD[s] for s in segments], dtype=float)
    for ev in config.EVENTS:
        override = ev["effect"].get("renewal_hazard", {})
        if not override:
            continue
        mask = in_window(renewal_dates, ev["start"], ev["end"])
        for seg, h in override.items():
            hazard[mask & (segments == seg)] = h
    return hazard

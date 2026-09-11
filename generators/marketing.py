"""Promotions + paid media (stream 27).

  app_db__promotions   one row per promo code (window, discount, channels)
  ads__daily_spend     one row per platform-day: spend, clicks, impressions, and the
                       platform's SELF-REPORTED conversions (inflated vs warehouse-
                       attributed new customers — debt item #5, context deferred)

The ad-spend cut event (config.EVENTS: ad_spend_cut_2026_02) is planted here as a
three-month spend collapse across every platform.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from generators import timeline
from generators.common import make_rng


def generate_promotions() -> pd.DataFrame:
    rows = [
        (p["promo_code"], p["name"], pd.Timestamp(p["start"]), pd.Timestamp(p["end"]),
         p["discount_pct"], ",".join(p["channels"]))
        for p in config.PROMOTIONS
    ]
    return pd.DataFrame(rows, columns=["promo_code", "promo_name", "start_date", "end_date",
                                       "discount_pct", "eligible_channels"])


def generate_ad_spend(rng: np.random.Generator) -> pd.DataFrame:
    frames = []
    for platform, (start, daily, cpc, cvr, inflation) in config.AD_PLATFORMS.items():
        days = pd.date_range(start, config.END_DATE, freq="D")
        base = daily * timeline.growth(days) * timeline.seasonality(days, config.SEASONALITY_CONSUMER)
        spend = np.round(base * timeline.ad_spend_multiplier(days) * rng.lognormal(0, 0.15, size=len(days)), 2)
        clicks = np.round(spend / cpc).astype(int)
        impressions = clicks * rng.integers(28, 52, size=len(days))
        reported = np.round(clicks * cvr * inflation).astype(int)
        frames.append(pd.DataFrame({
            "spend_date": days, "platform": platform, "spend_usd": spend,
            "impressions": impressions, "clicks": clicks, "reported_conversions": reported,
        }))
    return pd.concat(frames, ignore_index=True)


def generate(rng: np.random.Generator | None = None) -> dict[str, pd.DataFrame]:
    """Promotions + ad spend. Pass the stream-27 RNG so orders.py can continue the
    same stream for promo attachment; a fresh one is made otherwise."""
    rng = make_rng(stream=27) if rng is None else rng
    return {
        "app_db__promotions": generate_promotions(),
        "ads__daily_spend": generate_ad_spend(rng),
    }


def promo_attach(rng: np.random.Generator, dates, channels) -> np.ndarray:
    """Per-order promo_code (or None): the first promo whose window and channel
    match, attached with its attach_rate. Uses the caller's stream 27 RNG after
    generate() so the draw order is fixed."""
    from generators.common import in_window
    codes = np.full(len(dates), None, dtype=object)
    u = rng.random(len(dates))
    for p in config.PROMOTIONS:
        mask = in_window(dates, p["start"], p["end"]) & np.isin(channels, p["channels"]) & (u < p["attach_rate"])
        mask &= codes == None  # noqa: E711  (first matching promo wins)
        codes[mask] = p["promo_code"]
    return codes

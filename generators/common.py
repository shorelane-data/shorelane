"""Deterministic RNG + small helpers. All randomness in the project funnels
through here so a single SEED reproduces the entire dataset.

RNG stream registry (config.SEED + stream). Never reuse a stream; never
insert a draw into an existing stream's sequence (it perturbs everything after).

   1   legacy v1-v3 order dates/amounts (retired in v4; kept reserved)
   2   subscription invoice collection jitter + bad debt
   3   refund selection + lag
  10-17 customer identity fragmentation (see generators/identity.py)
  20   consumer order dates + channels
  21   subscription starts, segments, plans, seats, renewals
  22   never-ordered sign-ups, test/internal account selection
  23   product catalog
  24   supplier shipments
  25   consumer order -> customer assignment
  26   order lines
  27   promotions attach + paid-media spend
  28   support tickets
  30+  reserved for future debt items
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def make_rng(stream: int = 0) -> np.random.Generator:
    """Return an independent, reproducible RNG.

    Use distinct `stream` ints for distinct generators so adding a new generator
    never perturbs the output of existing ones (which would break ground truth).
    """
    return np.random.default_rng(config.SEED + stream)


def triangular(rng: np.random.Generator, lo: float, mode: float, hi: float, n: int) -> np.ndarray:
    """Triangular draw — cheap stand-in for a skewed order-value distribution."""
    return rng.triangular(lo, mode, hi, size=n)


def random_dates(rng: np.random.Generator, start: str, end: str, n: int) -> np.ndarray:
    """Uniform random dates in [start, end] as numpy datetime64[D]."""
    s = np.datetime64(start)
    e = np.datetime64(end)
    span = (e - s).astype(int)
    offsets = rng.integers(0, span + 1, size=n)
    return s + offsets.astype("timedelta64[D]")


CONSUMER_CHANNELS = ("d2c", "marketplace")
ALL_CHANNELS = ("d2c", "business_subscription", "marketplace")


def canonical_channel(channel: pd.Series) -> pd.Series:
    """Coalesce the 2022 channel rename: 'direct' (pre-rename d2c) -> 'd2c'.

    This is the rule context/ documents; raw and staging tables do NOT apply it.
    """
    return channel.replace({config.LEGACY_D2C_LABEL: "d2c"})


def in_window(dates, start: str, end: str) -> np.ndarray:
    """Boolean mask for dates within [start, end] inclusive (day precision)."""
    d = pd.DatetimeIndex(pd.to_datetime(dates))
    return np.asarray((d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end)))

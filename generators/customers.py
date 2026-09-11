"""Customer lifecycle: who places each consumer order (stream 25) and the sign-up
pool (stream 22).

Consumer orders are drawn order-first (dates from the intensity curve), then
assigned to customers with a recency pool: each order is either from a NEW
customer (probability = timeline.new_customer_share, which the ad-spend cut
lowers) or from a customer active in the trailing REPEAT_WINDOW_DAYS. Business
customers join the pool when a subscription term starts, so they also place
d2c/marketplace orders. That produces real cohorts, retention curves, and a
"new vs returning" series with known causes.

Customer keys are integers here; chronological `cust_XXXXXX` ids are assigned in
`build_customer_table` once every customer's creation date is known.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from generators import timeline
from generators.common import make_rng

KEY_INTERNAL_START = -1_000  # internal accounts get keys -1000.. -996; never collide


def assign_consumer_orders(
    dates: np.ndarray,            # datetime64[D], sorted
    channels: np.ndarray,         # canonical channel per order
    business_term_starts: np.ndarray,   # datetime64[D], sorted
    business_keys: np.ndarray,          # int key per term start
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[int, bool]]:
    """Return (customer_key, is_new_customer, is_internal) per order plus the
    set of consumer keys flagged as test accounts."""
    rng = make_rng(stream=25)
    n = len(dates)
    day = dates.astype("datetime64[D]").astype(np.int64)
    biz_day = business_term_starts.astype("datetime64[D]").astype(np.int64)

    p_new = np.empty(n, dtype=float)
    for ch in config.CONSUMER_CHANNEL_MIX:
        m = channels == ch
        p_new[m] = timeline.new_customer_share(dates[m], ch)
    u_new = rng.random(n)
    u_pick = rng.random(n)
    u_internal = rng.random(n)
    u_test = rng.random(n)
    u_internal_key = rng.integers(0, config.N_INTERNAL_ACCOUNTS, size=n)

    n_biz = int(business_keys.max()) + 1 if len(business_keys) else 0
    next_key = n_biz
    active: list[int] = []
    last: dict[int, int] = {}
    test_accounts: dict[int, bool] = {}
    customer_key = np.empty(n, dtype=np.int64)
    is_new = np.zeros(n, dtype=bool)
    is_internal = np.zeros(n, dtype=bool)
    biz_ptr = 0
    rebuild_at = day[0] + 30 if n else 0

    for i in range(n):
        d = int(day[i])
        while biz_ptr < len(biz_day) and biz_day[biz_ptr] <= d:
            key = int(business_keys[biz_ptr])
            if key not in last:
                active.append(key)
            last[key] = int(biz_day[biz_ptr])
            biz_ptr += 1
        if d >= rebuild_at:
            active = [k for k in active if d - last[k] <= config.REPEAT_WINDOW_DAYS]
            rebuild_at = d + 30
        if u_internal[i] < config.INTERNAL_ORDER_RATE:
            key = KEY_INTERNAL_START + int(u_internal_key[i])
            is_internal[i] = True
        elif u_new[i] < p_new[i] or not active:
            key = next_key
            next_key += 1
            active.append(key)
            is_new[i] = True
            test_accounts[key] = bool(u_test[i] < config.TEST_ACCOUNT_RATE)
        else:
            key = active[int(u_pick[i] * len(active))]
        last[key] = d
        customer_key[i] = key
    return customer_key, is_new, is_internal, test_accounts


def build_customer_table(
    keys_created_at: pd.Series,          # key -> created_at (business + consumer + internal)
    segment_by_key: pd.Series,           # key -> 'consumer' | 'smb' | 'enterprise'
    account_type_by_key: pd.Series,      # key -> customer | test | internal
    acquisition_by_key: pd.Series,       # key -> first channel (canonical)
) -> tuple[pd.DataFrame, pd.Series]:
    """Add never-ordered sign-ups (stream 22), sort everyone chronologically, and
    assign `cust_XXXXXX` ids. Returns the table and a key -> id map."""
    rng = make_rng(stream=22)
    n_ordered = len(keys_created_at)
    n_signups = int(round(n_ordered * config.NEVER_ORDERED_ACCOUNT_SHARE))
    signup_dates = timeline.draw_dates(rng, "d2c", n_signups)
    signup_keys = np.arange(n_signups) + 10_000_000

    frame = pd.DataFrame({
        "key": np.concatenate([keys_created_at.index.to_numpy(), signup_keys]),
        "created_at": np.concatenate([keys_created_at.to_numpy().astype("datetime64[D]"), signup_dates]),
        "segment": np.concatenate([segment_by_key.reindex(keys_created_at.index).to_numpy(),
                                   np.full(n_signups, "consumer", dtype=object)]),
        "account_type": np.concatenate([account_type_by_key.reindex(keys_created_at.index).to_numpy(),
                                        np.full(n_signups, "customer", dtype=object)]),
        "acquisition_channel": np.concatenate([acquisition_by_key.reindex(keys_created_at.index).to_numpy(),
                                               np.full(n_signups, "signup", dtype=object)]),
    })
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    frame = frame.sort_values(["created_at", "key"], kind="stable", ignore_index=True)
    frame["app_db_customer_id"] = [f"cust_{i + 1:06d}" for i in range(len(frame))]
    key_to_id = pd.Series(frame["app_db_customer_id"].values, index=frame["key"].values)
    customers = frame[["app_db_customer_id", "created_at", "segment", "account_type",
                       "acquisition_channel"]].reset_index(drop=True)
    return customers, key_to_id

"""
Shorelane Commerce — central configuration.

EVERYTHING about the dataset is pinned here so the data is reproducible and the
authored ground truth stays valid. Changing SEED or any economic constant is a
BREAKING CHANGE: it invalidates context/ground_truth/*. Bump DATASET_VERSION and
re-derive ground truth when you do.

See CLAUDE.md for the design contract.
"""
from __future__ import annotations

DATASET_VERSION = "shorelane-v3"

# Master seed. All randomness derives from this. Do not introduce unseeded RNG.
SEED = 20190401

# Business timeline (founded 2019). Extends past "today" so the live pipeline
# (shorelane-pipeline) can drip-feed rows daily until END_DATE: the loader's
# --as-of filter hides future-dated rows, keeping the warehouse "live" while the
# Parquet stays canonical and fully deterministic.
START_DATE = "2019-01-01"
END_DATE = "2027-12-31"

# Scale knob for the vertical slice. Production target is millions of rows; this
# is sized to run in seconds while still making the five revenues diverge cleanly.
# Scaled with the v2 timeline extension to keep ~4.6 orders/day density.
N_ORDERS = 15000

# Identity-fragmentation fixture. These values are versioned raw-data semantics.
IDENTITY_MIGRATION_DATE = "2021-07-01"
IDENTITY_CROSSWALK_DROP_RATE = 0.12
STRIPE_ACCOUNT_RECREATION_RATE = 0.06

# ---------------------------------------------------------------------------
# Channel mix (must sum to 1.0). Three revenue streams, per the Shorelane brief.
# ---------------------------------------------------------------------------
CHANNEL_MIX = {
    "d2c": 0.55,                  # direct-to-consumer, paid immediately
    "business_subscription": 0.25,  # net-30 terms, recognized ratably
    "marketplace": 0.20,         # 3rd-party sellers, we keep a take rate
}

# ---------------------------------------------------------------------------
# Economics that make the FIVE REVENUES diverge. This is the planted trap.
# ---------------------------------------------------------------------------

# Marketplace: buyer pays full gross; Shorelane keeps only the take.
# GMV counts the full gross; net revenue counts only the take. <-- the wedge.
MARKETPLACE_TAKE_RATE_RANGE = (0.15, 0.25)

# Business subscriptions: billed upfront for a term, net-30 collection,
# recognized ratably across the term.
SUBSCRIPTION_TERM_MONTHS = 12
NET_TERMS_DAYS = 30
# Fraction of net-30 invoices that are never collected (bad debt). Makes
# collected_cash < billed_revenue beyond just timing.
BAD_DEBT_RATE = 0.04

# Refunds: a fraction of d2c + marketplace orders are refunded N days later.
# Reduces net_revenue and collected_cash; GMV is reported gross of refunds.
REFUND_RATE = 0.06
REFUND_LAG_DAYS_RANGE = (3, 45)

# Order value distribution (USD), lognormal-ish via min/mode/max per channel.
ORDER_VALUE_USD = {
    "d2c": (20, 85, 600),
    "business_subscription": (1200, 4800, 36000),  # annual contract value
    "marketplace": (15, 60, 900),
}

# ---------------------------------------------------------------------------
# The question the eval set targets first. Ground truth is derived for this.
# ---------------------------------------------------------------------------
TARGET_PERIOD = {"label": "Q1 2024", "start": "2024-01-01", "end": "2024-03-31"}

# Output
RAW_DIR = "data/raw"
GCS_BUCKET = ""  # set to gs://your-bucket to enable upload in emit.py

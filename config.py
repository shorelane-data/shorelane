"""
Shorelane Commerce — central configuration.

EVERYTHING about the dataset is pinned here so the data is reproducible and the
authored ground truth stays valid. Changing SEED or any economic constant is a
BREAKING CHANGE: it invalidates context/ground_truth/*. Bump DATASET_VERSION and
re-derive ground truth when you do.

v4 (2026-09) is the "business dynamics" release: growth, seasonality, a customer
lifecycle, a product catalog with unit cost, subscription plan generations, and a
calendar of SEEDED EVENTS with known causes, so diagnostic ("why") and
prescriptive ("what should we do") questions have derivable answers. See
CLAUDE.md for the design contract and `EVENTS` below for the causal calendar.
"""
from __future__ import annotations

DATASET_VERSION = "shorelane-v4"

# Master seed. All randomness derives from this. Do not introduce unseeded RNG.
SEED = 20190401

# Business timeline (founded 2019). Extends past "today" so the live pipeline
# (shorelane-pipeline) can drip-feed rows daily until END_DATE: the loader's
# --as-of filter hides future-dated rows, keeping the warehouse "live" while the
# Parquet stays canonical and fully deterministic.
START_DATE = "2019-01-01"
END_DATE = "2027-12-31"

# ---------------------------------------------------------------------------
# Scale. Consumer-channel orders (d2c + marketplace) are drawn exactly; new
# subscription starts are drawn exactly; subscription RENEWALS are emergent from
# the churn hazard, so total orders land a little above the sum of the two.
# ---------------------------------------------------------------------------
N_CONSUMER_ORDERS = 84_000
N_NEW_SUBSCRIPTIONS = 7_500
NEVER_ORDERED_ACCOUNT_SHARE = 0.12   # sign-ups that never order (the "pool over-counts" trap)

# ---------------------------------------------------------------------------
# Business dynamics: the order-intensity curve is base x growth x seasonality x
# event multipliers (generators/timeline.py).
# ---------------------------------------------------------------------------
GROWTH_RATE_ANNUAL = 0.14   # compounding volume growth from START_DATE

# Office supplies: back-to-school (Aug/Sep), Q4 B2B budget flush, January lull.
SEASONALITY_CONSUMER = {1: 0.82, 2: 0.88, 3: 0.98, 4: 0.96, 5: 0.95, 6: 0.92,
                        7: 0.90, 8: 1.14, 9: 1.20, 10: 1.02, 11: 1.08, 12: 1.15}
# B2B contracts book in the Q4 budget flush and go quiet in Q1 — which is exactly
# why recognized_revenue (ratable from prior bookings) EXCEEDS gmv in Q1: the
# signature trap of the fixture.
SEASONALITY_SUBSCRIPTION = {1: 0.74, 2: 0.78, 3: 0.90, 4: 0.98, 5: 0.96, 6: 0.92,
                            7: 0.84, 8: 0.88, 9: 1.06, 10: 1.16, 11: 1.34, 12: 1.44}

CONSUMER_CHANNEL_MIX = {"d2c": 0.75, "marketplace": 0.25}

# Share of consumer orders placed by a NEW customer (the rest go to the pool of
# customers active in the trailing year). Ad spend moves the d2c share (see EVENTS).
NEW_CUSTOMER_SHARE = {"d2c": 0.30, "marketplace": 0.36}
REPEAT_WINDOW_DAYS = 365

# ---------------------------------------------------------------------------
# Identity-fragmentation fixture (v3). These values are versioned raw-data semantics.
# ---------------------------------------------------------------------------
IDENTITY_MIGRATION_DATE = "2021-07-01"
IDENTITY_CROSSWALK_DROP_RATE = 0.12
STRIPE_ACCOUNT_RECREATION_RATE = 0.06

# ---------------------------------------------------------------------------
# Data debt (CLAUDE.md catalog). Each is a definitional trap with a documented
# exclusion / coalescing rule in context/.
# ---------------------------------------------------------------------------
# #3 Channel rename 2022: d2c orders before this date carry channel = 'direct'.
CHANNEL_RENAME_DATE = "2022-06-01"
LEGACY_D2C_LABEL = "direct"

# #6 Test accounts + internal orders, unfiltered in raw/staging. fct_revenue and
# generators/measures.py EXCLUDE orders from non-'customer' accounts.
TEST_ACCOUNT_RATE = 0.015          # share of new consumer accounts that are QA/test
INTERNAL_ORDER_RATE = 0.006        # share of consumer orders placed by internal accounts
N_INTERNAL_ACCOUNTS = 5
ACCOUNT_TYPES = ("customer", "test", "internal")

# #4 Subscription restructure: three grandfathered plan generations. Only gen 3
# is "current" in the app, but all three are live subscriptions.
PLAN_GENERATIONS = {
    1: {"launched_at": "2019-01-01", "retired_at": "2021-06-30",
        "plans": {"starter_v1": ("Business Starter", 84.0, "smb"),
                  "pro_v1": ("Business Pro", 156.0, "enterprise")}},
    2: {"launched_at": "2021-07-01", "retired_at": "2023-03-31",
        "plans": {"team_v2": ("Team", 108.0, "smb"),
                  "office_v2": ("Office", 192.0, "smb"),
                  "enterprise_v2": ("Enterprise", 228.0, "enterprise")}},
    3: {"launched_at": "2023-04-01", "retired_at": None,
        "plans": {"essentials": ("Essentials", 120.0, "smb"),
                  "growth": ("Growth", 204.0, "smb"),
                  "enterprise": ("Enterprise", 252.0, "enterprise")}},
}
SUBSCRIPTION_TERM_MONTHS = 12
NET_TERMS_DAYS = 30
BAD_DEBT_RATE = 0.04
ENTERPRISE_SHARE_OF_NEW_SUBSCRIPTIONS = 0.20
SEATS = {"smb": (3, 12, 60), "enterprise": (40, 90, 200)}      # triangular (min, mode, max)
RENEWAL_CHURN_HAZARD = {"smb": 0.20, "enterprise": 0.10}        # per renewal opportunity

# Marketplace: buyer pays full gross; Shorelane keeps only the take.
# GMV counts the full gross; net revenue counts only the take. <-- the wedge.
MARKETPLACE_TAKE_RATE_RANGE = (0.15, 0.25)

# Refunds: a fraction of consumer orders are refunded N days later.
REFUND_RATE = 0.06
REFUND_LAG_DAYS_RANGE = (3, 45)

# ---------------------------------------------------------------------------
# Product catalog (generators/catalog.py). Unit cost is the margin substrate for
# prescriptive questions. Suppliers map one-to-one onto categories.
# ---------------------------------------------------------------------------
CATEGORIES = {
    #  category     weight  qty_max  (unit_cost_lo, hi)  markup_lo, hi   n_skus
    "paper":       (0.26,   10,      (3.0, 28.0),        1.35, 1.75,     24),
    "writing":     (0.20,   8,       (0.8, 14.0),        1.60, 2.40,     30),
    "office_tech": (0.14,   2,       (18.0, 260.0),      1.20, 1.55,     22),
    "furniture":   (0.06,   2,       (60.0, 520.0),      1.30, 1.70,     14),
    "breakroom":   (0.18,   6,       (2.5, 40.0),        1.40, 1.90,     20),
    "storage":     (0.16,   4,       (4.0, 75.0),        1.45, 1.95,     18),
}
SUPPLIERS = {
    "sup_northpaper": ("North Paper Mills", "paper"),
    "sup_inkline": ("Inkline Writing Co.", "writing"),
    "sup_voltdesk": ("VoltDesk Electronics", "office_tech"),
    "sup_harborform": ("Harbor Form Furniture", "furniture"),
    "sup_pantryhub": ("PantryHub Wholesale", "breakroom"),
    "sup_stackright": ("StackRight Storage", "storage"),
}
LINES_PER_ORDER_P = 0.42   # geometric; mean ~2.4 lines
MAX_LINES_PER_ORDER = 6

# Promotions (generators/marketing.py). Only BTB15 carries a volume effect (EVENTS).
PROMOTIONS = [
    {"promo_code": "WELCOME10", "name": "Welcome 10", "start": "2021-03-01", "end": "2021-03-31",
     "discount_pct": 0.10, "channels": ("d2c",), "attach_rate": 0.35},
    {"promo_code": "SPRING5", "name": "Spring Refresh", "start": "2022-04-01", "end": "2022-04-30",
     "discount_pct": 0.05, "channels": ("d2c", "marketplace"), "attach_rate": 0.40},
    {"promo_code": "BTB15", "name": "Back to Business", "start": "2024-09-01", "end": "2024-09-30",
     "discount_pct": 0.15, "channels": ("d2c", "marketplace"), "attach_rate": 0.70},
]

# Paid media (ads__daily_spend). reported_conversions are platform self-reported
# and INFLATED relative to warehouse-attributed new customers (debt item #5).
AD_PLATFORMS = {
    #  platform  start_date     daily_spend  cpc   cvr    self_report_inflation
    "google": ("2019-06-01", 900.0, 1.40, 0.032, 1.30),
    "meta":   ("2019-06-01", 700.0, 0.95, 0.024, 1.55),
    "tiktok": ("2021-01-01", 350.0, 0.60, 0.015, 1.85),
}

# Support (zendesk__tickets)
TICKET_RATE_CONSUMER = 0.06          # tickets per consumer order
TICKETS_PER_SUBSCRIPTION_TERM = 0.6  # Poisson mean per active term

# ---------------------------------------------------------------------------
# SEEDED EVENTS — the causal calendar. Every event has a known cause recorded in
# `cause_table`, so "why did X happen in <window>?" has a derivable answer
# (generators/event_measures.py). All windows are fully elapsed before 2026-07
# so holdout questions stay valid on the live drip-fed warehouse.
# ---------------------------------------------------------------------------
EVENTS = [
    {
        "id": "supplier_outage_2023_03",
        "kind": "stockout",
        "start": "2023-03-06", "end": "2023-04-09",
        "effect": {"volume": {"d2c": 0.85, "marketplace": 0.85},
                   "category_share": {"paper": 0.05}},
        "cause_table": "erp__supplier_shipments",
        "description": "North Paper Mills shipments stop for five weeks; paper lines "
                       "nearly vanish and consumer order volume dips ~15%.",
    },
    {
        "id": "promo_back_to_business_2024_09",
        "kind": "promotion",
        "start": "2024-09-01", "end": "2024-09-30",
        "effect": {"volume": {"d2c": 1.40, "marketplace": 1.40},
                   "promo_code": "BTB15"},
        "cause_table": "app_db__promotions",
        "description": "Back to Business promo: consumer volume +40%, 15% discount on "
                       "70% of orders, so AOV falls while order count spikes.",
    },
    {
        "id": "sub_price_increase_2025_05",
        "kind": "price_change",
        "start": "2025-05-01", "end": "2025-07-31",
        "effect": {"volume": {"business_subscription": 0.80},
                   "price": {"plan_generation": 3, "factor": 1.12,
                             "effective_from": "2025-05-01"}},
        "cause_table": "app_db__plan_prices",
        "description": "Gen-3 plan prices +12% from 2025-05-01; new subscription starts "
                       "dip 20% for three months while ACV per seat rises.",
    },
    {
        "id": "enterprise_churn_2022_q4",
        "kind": "churn",
        "start": "2022-10-01", "end": "2022-12-31",
        "effect": {"renewal_hazard": {"enterprise": 0.65},
                   "tickets": {"segment": "enterprise", "category": "billing",
                               "mean_extra": 2.5, "start": "2022-09-01", "end": "2022-11-30"}},
        "cause_table": "zendesk__tickets",
        "description": "Enterprise renewals due in Q4 2022 churn at 65% (vs 10%) after "
                       "a billing-portal incident that shows up as a spike in "
                       "enterprise billing tickets from September.",
    },
    {
        "id": "ad_spend_cut_2026_02",
        "kind": "marketing",
        "start": "2026-02-01", "end": "2026-04-30",
        "effect": {"volume": {"d2c": 0.85},
                   "new_customer_share": {"d2c": 0.55},
                   "ad_spend": 0.35},
        "cause_table": "ads__daily_spend",
        "description": "Paid media cut to 35% of run-rate for three months; new d2c "
                       "customers fall ~45% and d2c volume ~15%.",
    },
]

# ---------------------------------------------------------------------------
# The question the eval set targets first. Ground truth is derived for this.
# ---------------------------------------------------------------------------
TARGET_PERIOD = {"label": "Q1 2024", "start": "2024-01-01", "end": "2024-03-31"}

# Output
RAW_DIR = "data/raw"
GCS_BUCKET = ""  # set to gs://your-bucket to enable upload in emit.py

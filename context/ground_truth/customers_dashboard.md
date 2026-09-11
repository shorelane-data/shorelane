# Ground truth — Customers Dashboard KPIs

Dataset: **shorelane-v4** (SEED=20190401). These figures are
**derived from the generated data** by `bi/customers_data.py`, not hand-authored.
They are the source-of-truth numbers the customers dashboard
(`bi/plotly/customers_dashboard_static.py`) renders. Reproduce exactly with:

```
python -m bi.customers_data --anchor 2025-12 --output context/ground_truth/customers_dashboard.md
```

All counts are at the **canonical customer grain** (`app_db__orders.customer_id`
== `dim_customers.app_db_customer_id`), never at source-alias grain — counting
per-system customer rows double-counts (see the identity block below and
`context/guides/customer_identity.md`). Definitions live in
`context/metrics/customers.yml`; the trailing "current" window is
12 calendar months, equal to the subscription term, so the
current-subscriber rule (active ratable term) and the trailing-year rule
coincide at month grain. Windows are pinned to fully-elapsed months ending
2025-12, so the figures are valid against both the full
fixture and the live drip-fed warehouse.

## Last 12 Months (2025-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| Current customers (at window end) | 9,184 |
| Current subscribers (at window end) | 3,232 |
| Current d2c customers (at window end) | 6,246 |
| Current marketplace customers (at window end) | 2,653 |
| Active customers (ordered in window) | 9,184 |
| New customers (first order in window) | 4,544 |
| Returning share of actives | 50.52% |
| Multi-channel customers (in window) | 2,681 |

## All Time (2019-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| Current customers (at window end) | 9,184 |
| Current subscribers (at window end) | 3,232 |
| Current d2c customers (at window end) | 6,246 |
| Current marketplace customers (at window end) | 2,653 |
| Active customers (ordered in window) | 22,628 |
| New customers (first order in window) | 22,628 |
| Returning share of actives | 0.00% |
| Multi-channel customers (in window) | 9,529 |

## Identity health (arrival rule applied as of 2025-12-31)

| Measure | Derived value |
|---|---:|
| Source aliases (4 systems, sum of profile rows) | 70,975 |
| Unresolved aliases | 1,180 |
| Resolution null rate | 0.016626 |
| Canonical app profiles | 25,359 |
| Ever-ordered canonical customers | 22,628 |
| Avg source IDs per ordered customer | 2.964 |
| Pre-migration Shopify aliases missing from crosswalk | 533 |
| Pre-migration Salesforce aliases missing from crosswalk | 142 |

Aliases by source system and resolution status:

| Source system | Resolved | 2021 migration gap | Sync lag |
|---|---:|---:|---:|
| app_db | 25,359 | 0 | 0 |
| salesforce | 4,740 | 142 | 80 |
| shopify | 17,963 | 533 | 197 |
| stripe | 21,733 | 0 | 228 |

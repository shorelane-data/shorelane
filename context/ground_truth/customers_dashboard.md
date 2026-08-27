# Ground truth — Customers Dashboard KPIs

Dataset: **shorelane-v3** (SEED=20190401). These figures are
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
| Current customers (at window end) | 1,405 |
| Current subscribers (at window end) | 409 |
| Current d2c customers (at window end) | 812 |
| Current marketplace customers (at window end) | 306 |
| Active customers (ordered in window) | 1,405 |
| New customers (first order in window) | 184 |
| Returning share of actives | 86.90% |
| Multi-channel customers (in window) | 119 |

## All Time (2019-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| Current customers (at window end) | 1,405 |
| Current subscribers (at window end) | 409 |
| Current d2c customers (at window end) | 812 |
| Current marketplace customers (at window end) | 306 |
| Active customers (ordered in window) | 4,516 |
| New customers (first order in window) | 4,516 |
| Returning share of actives | 0.00% |
| Multi-channel customers (in window) | 2,560 |

## Identity health (arrival rule applied as of 2025-12-31)

| Measure | Derived value |
|---|---:|
| Source aliases (4 systems, sum of profile rows) | 14,783 |
| Unresolved aliases | 346 |
| Resolution null rate | 0.023405 |
| Canonical app profiles | 4,711 |
| Ever-ordered canonical customers | 4,516 |
| Avg source IDs per ordered customer | 3.154 |
| Pre-migration Shopify aliases missing from crosswalk | 208 |
| Pre-migration Salesforce aliases missing from crosswalk | 111 |

Aliases by source system and resolution status:

| Source system | Resolved | 2021 migration gap | Sync lag |
|---|---:|---:|---:|
| app_db | 4,711 | 0 | 0 |
| salesforce | 2,067 | 111 | 13 |
| shopify | 3,398 | 208 | 6 |
| stripe | 4,261 | 0 | 8 |

# Ground truth — Executive Dashboard KPIs

Dataset: **shorelane-v4** (SEED=20190401). These figures are **derived from the
generated data** by `bi/dashboard_data.py`, not hand-authored. They are the
source-of-truth numbers the interactive exec dashboard
(`bi/plotly/business_dashboard.py`) renders, and what an agent's answer should be
validated against. Reproduce exactly with:

```
python -m bi.dashboard_data --anchor 2025-12 --output context/ground_truth/business_dashboard.md
```

Headline **Revenue = recognized_revenue (GAAP)** — the canonical default from
`context/metrics/revenue.yml`. The timeline extends to 2027-12 so the live
pipeline can drip-feed data daily; every window below is therefore **pinned with
`--anchor 2025-12` to fully-elapsed calendar months**, making the figures valid
against both the full fixture and the live drip-fed warehouse (query with the
explicit date bounds shown). Orders from non-`customer` accounts
(`app_db__customers.account_type` in `test`, `internal`) are excluded from every
figure (revenue, customers, orders, refunds), matching `fct_revenue` and `fct_orders`; channels are at canonical grain
(`direct` coalesced to `d2c`).

## Last 12 Months (2025-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **Revenue (recognized)** | **$28,306,097.59** |
| GMV | $33,042,600.74 |
| Net revenue | $32,183,536.37 |
| Collected cash | $29,799,429.65 |
| Active customers | 9,107 |
| New customers | 4,496 |
| Orders | 14,583 |
| Avg order value | $2,265.83 |
| Refund rate (of GMV) | 0.51% |

Revenue by channel: Business Subscriptions $25,625,076.64 · Direct-to-Consumer $2,509,432.38 · Marketplace $171,588.57.

## Last 24 Months (2024-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **Revenue (recognized)** | **$50,416,375.91** |
| GMV | $58,746,539.60 |
| Net revenue | $57,147,816.81 |
| Collected cash | $52,910,562.09 |
| Active customers | 12,568 |
| New customers | 8,615 |
| Orders | 27,603 |
| Avg order value | $2,128.27 |
| Refund rate (of GMV) | 0.53% |

## Through 2025 (2019-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **Revenue (recognized)** | **$94,596,736.71** |
| GMV | $113,830,456.22 |
| Net revenue | $109,699,531.15 |
| Collected cash | $101,415,096.43 |
| Total customers | 22,371 |
| Orders | 68,160 |
| Avg order value | $1,670.05 |
| Refund rate (of GMV) | 0.71% |

## Notes for the demo

- The dashboard deliberately commits to ONE revenue (recognized/GAAP) and labels
  it. That is the "human-confirmed source of truth": an agent that answers a
  2025 "what's our revenue" with **$28.31M** matches; one that returns
  GMV ($33.04M) or collected cash ($29.80M) is the silent-SQL failure.
- On the **live warehouse**, an unanchored "last 12 months" resolves relative to
  today and will not match these tables — that is expected. Validation queries
  must use the explicit date bounds above.
- Re-derive after any change to `config.py` or the generators (it's a breaking
  change — bump `DATASET_VERSION` and regenerate this file in the same commit).

# Ground truth — Executive Dashboard KPIs

Dataset: **shorelane-v3** (SEED=20190401). These figures are **derived from the
generated data** by `bi/dashboard_data.py`, not hand-authored. They are the
source-of-truth numbers the interactive exec dashboard
(`bi/plotly/business_dashboard.py`) renders, and what an agent's answer should be
validated against. Reproduce exactly with:

```
python -m bi.dashboard_data --period "Last 12 Months" --anchor 2025-12
```

Headline **Revenue = recognized_revenue (GAAP)** — the canonical default from
`context/metrics/revenue.yml`. The v2 timeline extends to 2027-12 so the live
pipeline can drip-feed data daily; every window below is therefore **pinned with
`--anchor 2025-12` to fully-elapsed calendar months**, making the figures valid
against both the full fixture and the live drip-fed warehouse (query with the
explicit date bounds shown).

## Last 12 Months (2025-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **Revenue (recognized)** | **$6,013,944.57** |
| GMV | $5,943,579.64 |
| Net revenue | $5,843,535.09 |
| Collected cash | $5,806,227.26 |
| Active customers | 1,405 |
| New customers | 184 |
| Orders | 1,637 |
| Avg order value | $3,630.78 |
| Refund rate (of GMV) | 0.25% |

Revenue by channel: Business Subscriptions $5,787,386.63 · Direct-to-Consumer
$205,304.79 · Marketplace $21,253.15.

## Last 24 Months (2024-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **Revenue (recognized)** | **$11,821,002.56** |
| GMV | $11,886,827.55 |
| Net revenue | $11,681,783.04 |
| Collected cash | $11,211,075.13 |
| Active customers | 2,441 |
| New customers | 443 |
| Orders | 3,317 |
| Avg order value | $3,583.61 |
| Refund rate (of GMV) | 0.24% |

## Through 2025 (2019-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **Revenue (recognized)** | **$39,826,130.15** |
| GMV | $42,946,274.02 |
| Net revenue | $42,232,350.14 |
| Collected cash | $39,997,374.51 |
| Total customers | 4,516 |
| Orders | 11,711 |
| Avg order value | $3,667.17 |
| Refund rate (of GMV) | 0.25% |

## Notes for the demo

- The dashboard deliberately commits to ONE revenue (recognized/GAAP) and labels
  it. That is the "human-confirmed source of truth": an agent that answers a
  2025 "what's our revenue" with **$6.01M** matches; one that returns
  GMV ($5.94M) or collected cash ($5.81M) is the silent-SQL failure.
- On the **live warehouse**, an unanchored "last 12 months" resolves relative to
  today and will not match these tables — that is expected. Validation queries
  must use the explicit date bounds above.
- Re-derive after any change to `config.py` or the generators (it's a breaking
  change — bump `DATASET_VERSION` and regenerate this file in the same commit).

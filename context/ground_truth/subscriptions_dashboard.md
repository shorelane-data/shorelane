# Ground truth — Subscriptions Dashboard KPIs

Dataset: **shorelane-v4** (SEED=20190401). These figures are
**derived from the generated data** by `bi/subscriptions_data.py`, not hand-authored.
They are the numbers the FP&A subscriptions page (`bi/plotly/subscriptions_dashboard_static.py`)
renders. Reproduce exactly with:

```
python -m bi.subscriptions_data --anchor 2025-12 --output context/ground_truth/subscriptions_dashboard.md
```

Real customers only. One row per 12-month term; renewals are new terms. "Active
at D" = a term containing D, at customer grain. Renewal rate = renewed ÷ (renewed
+ churned) among terms that ended in the window; terms still running are not
decided and are excluded. Windows are pinned to fully elapsed months ending
2025-12.

## Last 12 Months (2025-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **Active subscribers (at window end)** | **3,232** |
| ACV under contract (at window end) | $29,671,685.76 |
| Grandfathered share (gen 1–2) of active | 34.25% |
| New subscriptions (first terms started) | 966 |
| New ACV | $9,139,592.16 |
| ACV per seat on new subscriptions | $226.08 |
| Renewal rate (terms decided in window) | 82.01% |
| Churned terms | 497 |
| ACV churned | $3,278,784.00 |

## Last 24 Months (2024-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **Active subscribers (at window end)** | **3,232** |
| ACV under contract (at window end) | $29,671,685.76 |
| Grandfathered share (gen 1–2) of active | 34.25% |
| New subscriptions (first terms started) | 1,847 |
| New ACV | $16,810,268.16 |
| ACV per seat on new subscriptions | $218.74 |
| Renewal rate (terms decided in window) | 82.40% |
| Churned terms | 886 |
| ACV churned | $5,536,248.00 |

## Active subscribers by plan as of 2025-12-31

| Generation | Plan | Active subscribers | Seats | ACV |
|---|---|---:|---:|---:|
| 1 | pro_v1 | 128 | 14,213 | $2,217,228.00 |
| 1 | starter_v1 | 328 | 8,076 | $678,384.00 |
| 2 | enterprise_v2 | 150 | 16,252 | $3,705,456.00 |
| 2 | office_v2 | 240 | 6,203 | $1,190,976.00 |
| 2 | team_v2 | 261 | 6,560 | $708,480.00 |
| 3 | enterprise | 457 | 49,703 | $13,720,180.32 |
| 3 | essentials | 826 | 20,723 | $2,717,088.00 |
| 3 | growth | 842 | 21,273 | $4,733,893.44 |

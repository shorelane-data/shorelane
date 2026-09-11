# Ground truth — Marketing Dashboard KPIs

Dataset: **shorelane-v4** (SEED=20190401). These figures are
**derived from the generated data** by `bi/marketing_data.py`, not hand-authored.
They are the numbers the marketing dashboard (`bi/plotly/marketing_dashboard_static.py`)
renders. Reproduce exactly with:

```
python -m bi.marketing_data --anchor 2025-12 --output context/ground_truth/marketing_dashboard.md
```

Marketing's headline is **GMV** (full ticket, all channels, gross of refunds).
Orders from non-`customer` accounts are excluded; channels are canonical
(`direct` coalesced to `d2c`); "consumer" means d2c + marketplace. New customers
are first-ever orders. CAC divides ad spend by new d2c customers attributed in
the warehouse, never by platform-reported conversions. Windows are pinned to
fully elapsed months ending 2025-12.

## Last 12 Months (2025-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **GMV (all channels)** | **$33,042,600.74** |
| Consumer GMV (d2c + marketplace) | $3,370,914.98 |
| Consumer orders | 11,351 |
| Consumer AOV | $296.97 |
| New customers (first order in window) | 4,500 |
| New d2c customers | 2,508 |
| Ad spend | $1,691,226.97 |
| CAC (ad spend ÷ new d2c customers) | $674.33 |
| Orders with a promo code | 0 |
| Discount dollars given | $0.00 |

Category line revenue (consumer orders):

| Category | Line revenue | Margin % |
|---|---:|---:|
| paper | $614,425.42 | 37.10% |
| writing | $231,819.11 | 50.48% |
| office_tech | $840,435.84 | 26.65% |
| furniture | $686,314.74 | 31.60% |
| breakroom | $398,708.33 | 38.37% |
| storage | $599,211.54 | 42.72% |

Promotions in window:

| Code | Window | Discount | Orders | GMV | Discount $ |
|---|---|---:|---:|---:|---:|
| — | no promotions in window | | | | |

## Last 24 Months (2024-01-01 .. 2025-12-31)

| KPI | Value |
|---|---:|
| **GMV (all channels)** | **$58,746,539.60** |
| Consumer GMV (d2c + marketplace) | $6,353,885.84 |
| Consumer orders | 21,609 |
| Consumer AOV | $294.04 |
| New customers (first order in window) | 8,626 |
| New d2c customers | 4,843 |
| Ad spend | $3,175,511.84 |
| CAC (ad spend ÷ new d2c customers) | $655.69 |
| Orders with a promo code | 953 |
| Discount dollars given | $43,520.76 |

Category line revenue (consumer orders):

| Category | Line revenue | Margin % |
|---|---:|---:|
| paper | $1,170,457.98 | 36.63% |
| writing | $450,703.20 | 50.14% |
| office_tech | $1,584,515.00 | 26.30% |
| furniture | $1,305,716.86 | 31.05% |
| breakroom | $729,257.64 | 37.98% |
| storage | $1,113,235.16 | 42.30% |

Promotions in window:

| Code | Window | Discount | Orders | GMV | Discount $ |
|---|---|---:|---:|---:|---:|
| BTB15 | 2024-09-01 .. 2024-09-30 | 15% | 953 | $246,600.08 | $43,520.76 |


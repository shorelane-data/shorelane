# Ground truth — seeded events (diagnostic and prescriptive substrate)

Dataset: **shorelane-v4** (SEED=20190401). These figures are
**derived from the generated data** by `generators/event_measures.py`, not
hand-authored. Every window is a fully elapsed calendar period, so the figures
are valid against both the full fixture and the live drip-fed warehouse.
Reproduce exactly with:

```
python -m generators.event_measures --output context/ground_truth/events.md
```

Orders from non-`customer` accounts (`app_db__customers.account_type` in
`test`, `internal`) are excluded throughout, matching `fct_revenue`. Channels are
at canonical grain (`direct` coalesced to `d2c`).

## 1. Supplier outage — 2023-03-06..2023-04-09 (cause: `erp__supplier_shipments`)

North Paper Mills shipped **0 of
76,781** expected units across
5 scheduled shipments in the window
(`status = 'delayed'`: shp_northpaper_20230306, shp_northpaper_20230313, shp_northpaper_20230320, shp_northpaper_20230327, shp_northpaper_20230403).

| Paper line revenue by month | Value |
|---|---:|
| 2023-01 | $32,069.00 |
| 2023-02 | $29,149.57 |
| 2023-03 | $8,026.35 |
| 2023-04 | $26,626.73 |
| 2023-05 | $35,036.70 |
| 2023-06 | $37,983.64 |

| Paper share of consumer line revenue | Value |
|---|---:|
| 2023-01 | 20.46% |
| 2023-02 | 17.31% |
| 2023-03 | 4.00% |
| 2023-04 | 13.24% |
| 2023-05 | 16.48% |
| 2023-06 | 18.41% |

| Consumer orders by month | Value |
|---|---:|
| 2023-01 | 558 |
| 2023-02 | 564 |
| 2023-03 | 662 |
| 2023-04 | 655 |
| 2023-05 | 665 |
| 2023-06 | 679 |

## 2. Back to Business promo — 2024-09-01..2024-09-30 (cause: `app_db__promotions`, code `BTB15`)

| Consumer orders by month | Value |
|---|---:|
| 2024-07 | 793 |
| 2024-08 | 977 |
| 2024-09 | 1,337 |
| 2024-10 | 924 |
| 2024-11 | 907 |

| Consumer GMV by month | Value |
|---|---:|
| 2024-07 | $234,705.01 |
| 2024-08 | $276,071.93 |
| 2024-09 | $359,035.99 |
| 2024-10 | $274,860.77 |
| 2024-11 | $254,480.97 |

| Consumer AOV by month | Value |
|---|---:|
| 2024-07 | $295.97 |
| 2024-08 | $282.57 |
| 2024-09 | $268.54 |
| 2024-10 | $297.47 |
| 2024-11 | $280.57 |

| Orders carrying BTB15 by month | Value |
|---|---:|
| 2024-07 | 0 |
| 2024-08 | 0 |
| 2024-09 | 953 |
| 2024-10 | 0 |
| 2024-11 | 0 |

| Discount dollars given by month | Value |
|---|---:|
| 2024-07 | $0.00 |
| 2024-08 | $0.00 |
| 2024-09 | $43,520.76 |
| 2024-10 | $0.00 |
| 2024-11 | $0.00 |

## 3. Gen-3 subscription price increase — effective 2025-05-01 (cause: `app_db__plan_prices`)

| Plan | Annual price per seat history |
|---|---|
| essentials | 2023-04-01: $120.00 → 2025-05-01: $134.40 |
| growth | 2023-04-01: $204.00 → 2025-05-01: $228.48 |
| enterprise | 2023-04-01: $252.00 → 2025-05-01: $282.24 |

| New subscription starts by month | Value |
|---|---:|
| 2025-02 | 66 |
| 2025-03 | 73 |
| 2025-04 | 76 |
| 2025-05 | 60 |
| 2025-06 | 61 |
| 2025-07 | 61 |
| 2025-08 | 63 |
| 2025-09 | 84 |

| New-subscription ACV per seat by month | Value |
|---|---:|
| 2025-02 | $211.00 |
| 2025-03 | $211.11 |
| 2025-04 | $211.58 |
| 2025-05 | $239.66 |
| 2025-06 | $221.58 |
| 2025-07 | $221.28 |
| 2025-08 | $228.88 |
| 2025-09 | $233.12 |

## 4. Enterprise churn — 2022-10-01..2022-12-31 (cause: `zendesk__tickets`)

Renewal outcomes for terms ending in each quarter (`status` in `renewed`, `churned`):

| Quarter / segment | Up for renewal | Churned | Churn rate | ACV churned |
|---|---:|---:|---:|---:|
| 2022Q2 smb | 247 | 48 | 19.43% | $104,580.00 |
| 2022Q2 enterprise | 56 | 5 | 8.93% | $82,524.00 |
| 2022Q3 smb | 250 | 47 | 18.80% | $135,324.00 |
| 2022Q3 enterprise | 70 | 10 | 14.29% | $217,548.00 |
| 2022Q4 smb | 358 | 71 | 19.83% | $197,340.00 |
| 2022Q4 enterprise | 106 | 67 | 63.21% | $1,475,292.00 |
| 2023Q1 smb | 268 | 58 | 21.64% | $151,704.00 |
| 2023Q1 enterprise | 87 | 12 | 13.79% | $226,116.00 |
| 2023Q2 smb | 340 | 68 | 20.00% | $194,448.00 |
| 2023Q2 enterprise | 88 | 5 | 5.68% | $105,744.00 |

| Business (Salesforce-requester) billing tickets by month | Value |
|---|---:|
| 2022-07 | 23 |
| 2022-08 | 14 |
| 2022-09 | 388 |
| 2022-10 | 427 |
| 2022-11 | 349 |
| 2022-12 | 28 |
| 2023-01 | 21 |

| of which high/urgent priority | Value |
|---|---:|
| 2022-07 | 2 |
| 2022-08 | 3 |
| 2022-09 | 366 |
| 2022-10 | 402 |
| 2022-11 | 343 |
| 2022-12 | 1 |
| 2023-01 | 5 |

## 5. Paid-media cut — 2026-02-01..2026-04-30 (cause: `ads__daily_spend`)

| Ad spend by month (all platforms) | Value |
|---|---:|
| 2025-11 | $157,017.06 |
| 2025-12 | $181,201.49 |
| 2026-01 | $128,285.02 |
| 2026-02 | $42,578.29 |
| 2026-03 | $54,596.70 |
| 2026-04 | $50,596.57 |
| 2026-05 | $152,076.27 |
| 2026-06 | $142,794.96 |

| d2c orders by month | Value |
|---|---:|
| 2025-11 | 748 |
| 2025-12 | 882 |
| 2026-01 | 619 |
| 2026-02 | 508 |
| 2026-03 | 602 |
| 2026-04 | 647 |
| 2026-05 | 776 |
| 2026-06 | 734 |

| New d2c customers by month (first-ever order) | Value |
|---|---:|
| 2025-11 | 215 |
| 2025-12 | 257 |
| 2026-01 | 190 |
| 2026-02 | 77 |
| 2026-03 | 108 |
| 2026-04 | 100 |
| 2026-05 | 224 |
| 2026-06 | 237 |

| New-customer share of d2c orders | Value |
|---|---:|
| 2025-11 | 28.74% |
| 2025-12 | 29.14% |
| 2026-01 | 30.69% |
| 2026-02 | 15.16% |
| 2026-03 | 17.94% |
| 2026-04 | 15.46% |
| 2026-05 | 28.87% |
| 2026-06 | 32.29% |

## 6. Prescriptive substrate — 2025 gross margin by category (consumer order lines)

| Category | Line revenue | COGS (qty × unit_cost) | Gross margin | Margin % | Units |
|---|---:|---:|---:|---:|---:|
| breakroom | $398,708.33 | $245,737.97 | $152,970.36 | 38.37% | 12,467 |
| furniture | $686,314.74 | $469,470.52 | $216,844.22 | 31.60% | 1,926 |
| office_tech | $840,435.84 | $616,440.50 | $223,995.34 | 26.65% | 4,716 |
| paper | $614,425.42 | $386,503.66 | $227,921.76 | 37.10% | 25,758 |
| storage | $599,211.54 | $343,221.36 | $255,990.18 | 42.72% | 8,246 |
| writing | $231,819.11 | $114,789.62 | $117,029.49 | 50.48% | 15,989 |

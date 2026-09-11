# Sigma workbooks — build guide

Two Sigma workbooks that mirror the public Pages dashboards, built on the public
BigQuery datasets (`nodal-shorelane.shorelane` and `shorelane_raw`). Sigma is a
third *render* of the same figures, never a new source of truth: every custom
SQL file here mirrors a function in `bi/dashboard_data.py` or
`bi/customers_data.py`, and each was checked against those references for
Last 12 Months anchored at 2026-08 before being committed.

| File | Workbook | Feeds | Mirrors |
|---|---|---|---|
| `business_kpis.sql` | Business | 6 KPI tiles (+ prior-window deltas) | `dashboard_data.kpis` |
| `business_monthly.sql` | Business | Revenue by Month, Customer Growth, Orders & AOV, Recognized vs Collected | `dashboard_data.monthly_metrics` |
| `revenue_by_channel.sql` | Business | Revenue by Channel donut | `dashboard_data.revenue_by_channel` |
| `customers_kpis.sql` | Customers | 6 KPI tiles + Current Customer Mix donut | `customers_data.kpis` |
| `customers_monthly.sql` | Customers | Current Customers by Month, Active by Channel, New vs Returning | `customers_data.monthly_customer_metrics` |
| `identity_health.sql` | Customers | 6 identity tiles + Naive vs Canonical bar | `customers_data.identity_quality` |
| `identity_by_system.sql` | Customers | Source Aliases by Resolution Status | `customers_data.identity_quality` |

`_periods.sql` is the shared period spine every period-aware file starts with.

## The period pattern (no SQL parameters needed)

Each period-aware query returns one block of rows per Period label
(`Last 6 Months`, `Last 12 Months`, `Last 24 Months`, `All Time`). A single
segmented control named **Period** targets the `period` column of every data
element on the page, so one click switches all tiles and charts together and
the SQL never has to be parameterised. The window end is always the last
fully-elapsed calendar month (`current_date()` minus one month), which is the
`--anchor` convention the ground truth uses, so the tiles agree with
`context/ground_truth/` on the live drip-fed warehouse.

## Build steps (both workbooks)

Prerequisite: a BigQuery connection in Sigma whose service account has
BigQuery Data Viewer + Job User on `nodal-shorelane`, and an account type with
the *Write SQL* permission (org admin has it).

1. **Create the workbook** — Create new > Workbook. Name it
   `Shorelane — Business` or `Shorelane — Customers`.
2. **Add each data element as custom SQL** — Add element > Data > Table >
   in the *Select source* modal pick **SQL** > choose the BigQuery connection >
   paste the file > Run (⌘+Return). Rename the element to the file's name
   (e.g. `business_kpis`) so the dashboard-verify playbook can find it.
   Collapse or hide these tables once the visuals exist.
3. **Add the Period control** — Add element > Controls > Segmented control.
   Value source: manual list, the four labels above, default `Last 12 Months`.
   On the control's **Targets** tab add every period-aware table and map it to
   its `period` column.
4. **KPI tiles** — Add element > Charts > **KPI**, source = the `*_kpis` table.
   Value = the metric column; Comparison = the matching `*_delta` column
   (column comparison, shown as a percent). Set the number format from the
   Value column's dropdown > Format. Title every tile with the canonical name
   from `context/metrics/` — that name is the point of the demo.
5. **Charts** — Add element > Charts, source = the `*_monthly` table (or the
   channel / identity tables). Bar, line, pie and combo (dual axis) cover
   every figure on the Pages site.
6. **Publish**, then open the published URL in View mode for recordings and
   for the dashboard-verify skill.

## Workbook 1 — Business (mirrors `/business/`)

KPI row from `business_kpis` (title · value · comparison · format):

- Revenue (Recognized · GAAP) · `recognized_revenue` · `recognized_revenue_delta` · currency
- GMV · `gmv` · `gmv_delta` · currency
- Active Customers · `active_customers` · `active_customers_delta` · integer
- New Customers · `new_customers` · `new_customers_delta` · integer
- Avg Order Value · `aov` · `aov_delta` · currency
- Refund Rate · `refund_rate` · `refund_rate_delta` · percent (a rise is bad)

Charts:

- Recognized Revenue by Month — bar, x `month`, y `recognized_revenue` (`business_monthly`)
- Revenue by Channel — donut, category `channel_label`, value `recognized_revenue` (`revenue_by_channel`)
- Customer Growth — combo: bars `new_customers`, line `cumulative_customers` on a secondary axis
- Orders & Average Order Value — combo: bars `orders`, line `aov` on a secondary axis
- Recognized Revenue vs Collected Cash — two lines, `recognized_revenue` and `collected_cash`

## Workbook 2 — Customers (mirrors `/customers/`)

KPI row from `customers_kpis`:

- Current Customers · `current_customers` · integer
- Current Subscribers · `current_subscribers` · integer
- Active Customers · `active_customers` · integer
- New Customers · `new_customers` · integer
- Returning Share · `returning_share` · percent
- Multi-Channel · `multi_channel_customers` · integer

Charts from `customers_monthly`:

- Current Customers by Month — line(s): `current_customers` (and per-channel series)
- Current Customer Mix (at window end) — donut over `current_d2c`,
  `current_subscribers`, `current_marketplace` from `customers_kpis` (slices sum
  past the deduplicated total; that is the documented gotcha, keep it visible)
- Active Customers by Month & Channel — stacked bar of the three `active_*` series
- New vs Returning Customers — stacked bar of `new_customers` and `returning_customers`

Identity health (no Period control; reads the warehouse's current load state):

- Tiles from `identity_health`: Source Aliases, Resolution Null Rate (percent),
  Canonical Profiles, Ever-Ordered Customers, Avg IDs / Customer,
  Pre-2021 Shopify Unlinked
- Source Aliases by Resolution Status — horizontal stacked bar from
  `identity_by_system`: y `source_system`, x `aliases`, color `status_label`
- Customer Count: Naive vs Canonical — bar of `source_aliases`,
  `canonical_profiles`, `ordered_customers` (unpivot the single row in Sigma,
  or three KPI tiles side by side)

## Validate before demoing

```
.venv/bin/python -m bi.dashboard_data --period "Last 12 Months" --anchor 2026-08
.venv/bin/python -m bi.customers_data --anchor 2026-08
```

With the Period control on Last 12 Months every tile must match to the cent
(revenue) or exactly (counts). The identity tiles are the one exception: the
warehouse is loaded as-of today while the reference above is as-of the anchor
month end, so alias counts drift by the handful of profiles that arrived since.
Compare them against a reference run whose anchor matches the load date.

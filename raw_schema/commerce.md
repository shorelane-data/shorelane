# Raw landing schema — commerce (v4)

Fivetran-shaped landing tables emitted by `generators.dataset.generate()` for the
`shorelane-v4` business-dynamics release. Together with `revenue_slice.md` (orders,
invoices, recognition, refunds) and `customer_identity.md` (customers, source-native
identities, crosswalk) this is the complete nineteen-table raw contract.

Types are generated pandas dtypes. Timestamps are business dates at day precision.
Amounts are `float64`; warehouse money handling is a modeling concern (`{{ money() }}`).

**Nothing in the raw layer is filtered.** Test and internal accounts, pre-rename
channel labels, retired plan generations, and delayed shipments all land as-is. The
exclusion and coalescing rules live in `context/` and are applied in the dbt marts.

## `app_db__products`

**Raw grain:** one row per SKU. **Primary key:** `sku`. **Arrival:** `introduced_at`.

| column | type | nullable | meaning |
|---|---|---:|---|
| `sku` | string | no | `sku_<cat>_<nnn>`; FK target for `app_db__order_lines.sku`. |
| `product_name` | string | no | Display name. |
| `category` | string | no | One of `paper`, `writing`, `office_tech`, `furniture`, `breakroom`, `storage`. |
| `supplier_id` | string | no | FK to `erp__suppliers.supplier_id` (one supplier per category). |
| `unit_cost` | float64 | no | Landed cost per unit — the margin substrate. |
| `list_price` | float64 | no | Undiscounted unit price used on order lines. |
| `introduced_at` | timestamp | no | First date the SKU can appear on a line. |

## `app_db__order_lines`

**Raw grain:** one row per line on a **consumer** (d2c / marketplace) order.
**Primary key:** `order_line_id`. **Arrival:** `created_at` (= the order date).

| column | type | nullable | meaning |
|---|---|---:|---|
| `order_line_id` | string | no | |
| `order_id` | string | no | FK to `app_db__orders.order_id`. |
| `sku` | string | no | FK to `app_db__products.sku`. |
| `quantity` | int64 | no | Units. |
| `unit_price` | float64 | no | `list_price` at order time. |
| `discount_pct` | float64 | no | 0 unless the order carries a promo code. |
| `line_amount` | float64 | no | `round(quantity * unit_price * (1 - discount_pct), 2)`; lines sum to the order's `gross_amount`. |
| `created_at` | timestamp | no | Order date. |

**Trap:** subscription orders have **no** order lines — their composition is in
`app_db__subscriptions`. Summing `order_lines.line_amount` yields consumer GMV only.

## `app_db__plans`

**Raw grain:** one row per plan across three grandfathered generations.
**Primary key:** `plan_id`. **Arrival:** `launched_at`.

| column | type | nullable | meaning |
|---|---|---:|---|
| `plan_id` | string | no | e.g. `starter_v1`, `team_v2`, `essentials`. |
| `plan_name` | string | no | |
| `plan_generation` | int64 | no | 1 (2019–2021-06), 2 (2021-07–2023-03), 3 (2023-04→). |
| `tier` | string | no | `smb` or `enterprise`. |
| `launched_at` | timestamp | no | |
| `retired_at` | timestamp | yes | Null for generation 3. As-of loads mask future retirements. |
| `is_current` | bool | no | True only for the generation still sold. **Trap:** filtering on it drops every grandfathered live subscription. |

## `app_db__plan_prices`

**Raw grain:** one row per plan per price change. **Primary key:** (`plan_id`, `effective_from`).
**Arrival:** `effective_from`. The 2025-05-01 rows are the gen-3 +12% increase.

| column | type | nullable | meaning |
|---|---|---:|---|
| `plan_id` | string | no | FK to `app_db__plans`. |
| `effective_from` | timestamp | no | |
| `annual_price_per_seat` | float64 | no | Applies to terms starting on/after `effective_from`. |

## `app_db__subscriptions`

**Raw grain:** one row per 12-month **term**; renewals are new rows chained by
`renewed_from_subscription_id`. **Primary key:** `subscription_id`. `order_id` is unique.
**Arrival:** `term_start`; a term still running at as-of shows `status = 'active'` and
`cancelled_at` null (future churn/renewal is masked).

| column | type | nullable | meaning |
|---|---|---:|---|
| `subscription_id` | string | no | Term id. |
| `customer_id` | string | no | FK to `app_db__customers.app_db_customer_id`. |
| `plan_id` | string | no | FK to `app_db__plans`; unchanged across renewals (grandfathering). |
| `seats` | int64 | no | |
| `term_start` / `term_end` | timestamp | no | Inclusive 12-month term. |
| `price_per_seat` | float64 | no | From `app_db__plan_prices` at `term_start`. |
| `acv` | float64 | no | `seats * price_per_seat`; equals the term's order `gross_amount`. |
| `order_id` | string | no | The `business_subscription` order for this term. |
| `renewed_from_subscription_id` | string | yes | Previous term; null on the first term. |
| `status` | string | no | `renewed` (a later term exists), `active` (running past END_DATE), `churned`. |
| `cancelled_at` | timestamp | yes | `term_end` when churned. |

"Active subscribers at date D" = terms with `term_start <= D <= term_end`, at
customer grain. Counting `status = 'active'` rows or `is_current` plans is the trap.

## `app_db__promotions`

**Raw grain:** one row per promo code. **Primary key:** `promo_code`. **Arrival:** `start_date`.
Columns: `promo_code`, `promo_name`, `start_date`, `end_date`, `discount_pct`,
`eligible_channels` (comma-separated). Orders reference codes via `app_db__orders.promo_code`.

## `erp__suppliers`

One row per supplier: `supplier_id` (PK), `supplier_name`, `category`, `onboarded_at`.

## `erp__supplier_shipments`

**Raw grain:** one row per supplier-week. **Primary key:** `shipment_id`.
**Arrival:** `expected_date`; a shipment received after as-of shows `status = 'in_transit'`
with `received_date` null.

| column | type | nullable | meaning |
|---|---|---:|---|
| `shipment_id` | string | no | |
| `supplier_id` | string | no | FK to `erp__suppliers`. |
| `category` | string | no | Denormalized supplier category. |
| `expected_date` | timestamp | no | Scheduled Monday. |
| `received_date` | timestamp | yes | Null when `delayed` (or masked as-of). |
| `units_expected` / `units_received` | int64 | no | |
| `status` | string | no | `received`, `partial`, `delayed` (`in_transit` in as-of snapshots). |

## `ads__daily_spend`

**Raw grain:** one row per platform-day. **Primary key:** (`spend_date`, `platform`).
**Arrival:** `spend_date`.

| column | type | nullable | meaning |
|---|---|---:|---|
| `spend_date` | timestamp | no | |
| `platform` | string | no | `google`, `meta` (from 2019-06), `tiktok` (from 2021-01). |
| `spend_usd` | float64 | no | |
| `impressions` / `clicks` | int64 | no | |
| `reported_conversions` | int64 | no | **Platform self-reported and inflated**; the warehouse-attributed figure is first-ever d2c orders in `app_db__orders`. |

## `zendesk__tickets`

**Raw grain:** one row per ticket. **Primary key:** `ticket_id`. **Arrival:** `created_at`;
a ticket solved after as-of shows `status = 'open'` with `resolved_at` null.

| column | type | nullable | meaning |
|---|---|---:|---|
| `ticket_id` | string | no | |
| `requester_source_system` | string | no | `salesforce` (business accounts), `stripe` (consumers), or `app_db` when the crosswalk cannot resolve. |
| `requester_source_id` | string | no | The source-native id; resolve via the crosswalk on the qualified key. |
| `created_at` | timestamp | no | |
| `category` | string | no | `shipping`, `product`, `billing`, `account`, `technical`, `onboarding`. |
| `priority` | string | no | `low`, `normal`, `high`, `urgent`. |
| `status` | string | no | `solved` or `open`. |
| `resolved_at` | timestamp | yes | |
| `related_order_id` | string | yes | Consumer-order tickets only. |
| `related_subscription_id` | string | yes | Subscription-term tickets only. |

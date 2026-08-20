# Raw landing schema — revenue slice

Fivetran-shaped landing tables emitted by `generators.dataset.generate()`. This file
documents the exact generated columns after identity enrichment, including the
source-native customer IDs now appended to invoices and refunds. See
`customer_identity.md` for customer tables, crosswalk semantics, and safe identity
resolution.

Types below are the generated pandas DataFrame dtypes. Timestamp values represent
business dates at day precision even though pandas stores some at nanosecond
resolution. Amounts and rates are generated as `float64`; warehouse/dbt money handling
is a separate modeling concern.

## `app_db__orders`

**Raw grain:** one row per order.

**Primary key:** `order_id`.

**Arrival column:** `order_date`; a row is visible when `order_date <= as_of`.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `order_id` | string (`object`) | no | App-native order ID. |
| `customer_id` | string (`object`) | no | FK to `app_db__customers.app_db_customer_id`. |
| `channel` | string (`object`) | no | `d2c`, `business_subscription`, or `marketplace`. |
| `order_date` | timestamp (`datetime64[s]`) | no | Order event date and arrival timestamp. |
| `gross_amount` | `float64` | no | Full ticket value; marketplace is full retail price. |
| `take_rate` | `float64` | yes | Marketplace take rate (0.15–0.25); null for d2c and business subscriptions. |
| `net_amount` | `float64` | no | Amount Shorelane earns; marketplace is `gross_amount * take_rate`. |

## `app_db__invoices`

**Raw grain:** one row per business-subscription order/invoice.

**Primary key:** `invoice_id`. `order_id` is also unique in this table and is an FK to
`app_db__orders.order_id`.

**Arrival column:** `billed_date`; a row is visible when `billed_date <= as_of`.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `invoice_id` | string (`object`) | no | App-native invoice ID. |
| `order_id` | string (`object`) | no | FK to the unique subscription order. This is the safe join back to app order/customer context. |
| `billed_date` | timestamp (`datetime64[s]`) | no | Equal to order date; billed up front. |
| `due_date` | timestamp (`datetime64[s]`) | no | `billed_date + 30 days`. |
| `collected_date` | timestamp (`datetime64[s]`) | yes | Actual collection date. Null means **pending or bad debt**, not bad debt alone; use `is_bad_debt` to distinguish them. |
| `amount` | `float64` | no | Invoice amount, equal to order `net_amount`. |
| `is_bad_debt` | boolean (`bool`) | no | True when the invoice is never collected in the generated fixture. |
| `salesforce_customer_id` | string (`string[python]`) | no in generated data | Source-native FK to `salesforce__customers.salesforce_customer_id`; it is not an app customer ID. |

For as-of loads, an already-billed invoice whose collection is after `as_of` remains
visible but has `collected_date` masked to null. Therefore:

- `collected_date is null and is_bad_debt = false` means pending in that snapshot;
- `collected_date is null and is_bad_debt = true` means bad debt.

## `app_db__revenue_recognition`

**Raw grain:** one row per order and recognition event. Business subscriptions have 12
monthly rows; d2c and marketplace orders have one row at order date.

**Composite primary key / uniqueness:** (`order_id`, `recognition_date`). `order_id`
alone is not unique and is an FK to `app_db__orders.order_id`.

**Arrival column:** `recognition_date`; a row is visible when
`recognition_date <= as_of`.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `order_id` | string (`object`) | no | FK to `app_db__orders.order_id`. |
| `recognition_date` | timestamp (`datetime64[ns]`) | no | Recognition event date; month-stepped for subscriptions. |
| `amount` | `float64` | no | Monthly portion for subscriptions or full order `net_amount` for other channels. |

Joining recognition to orders on `order_id` is safe, but it is one-to-many for
subscriptions. Do not infer order counts after that join without deduplicating orders.

## `stripe__refunds`

**Raw grain:** one row per refund on a d2c or marketplace order, lagged 3–44 days after
the order (the generator's upper bound is exclusive).

**Primary key:** `refund_id`. `order_id` is also unique in this table and is an FK to
`app_db__orders.order_id`.

**Arrival column:** `refund_date`; a row is visible when `refund_date <= as_of`.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `refund_id` | string (`object`) | no | Stripe-side refund event ID. |
| `order_id` | string (`object`) | no | FK to the refunded app order; the safe join to app order/customer context. |
| `refund_date` | timestamp (`datetime64[s]`) | no | Order date plus generated refund lag. |
| `refund_amount` | `float64` | no | Equal to refunded order `net_amount`. |
| `stripe_customer_id` | string (`string[python]`) | no in generated data | Source-native FK to `stripe__customers.stripe_customer_id`, selected according to which Stripe identity existed on the refund date. It is not an app customer ID. |

Use `order_id` to relate refunds to app orders. Use `stripe_customer_id` only for the
source-native Stripe relationship; resolving that ID to a canonical app customer via
the crosswalk requires the qualified key (`source_system = 'stripe'`,
`source_customer_id = stripe_customer_id`).

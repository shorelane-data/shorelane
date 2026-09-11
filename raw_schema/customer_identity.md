# Raw landing schema — customer identity

This document describes the **shorelane-v4** tables emitted by `generators.dataset.generate()`.
The public BigQuery dataset is loaded from this release; the private Redshift warehouse is
not (its migration is deferred).

The fixture deliberately fragments one app customer across source-native identities.
The raw Stripe, Shopify, and Salesforce customer tables intentionally do **not** expose
`app_db_customer_id`; the crosswalk is the only raw bridge to the canonical app ID, and
that bridge is intentionally incomplete.

Types below are the generated pandas DataFrame dtypes. Timestamp values have day-level
business precision even where pandas stores them at nanosecond resolution.

## `app_db__customers`

**Raw grain:** one row per app database customer in the complete operational customer
pool, including customers that never place an order.

**Primary key:** `app_db_customer_id`.

**Arrival column:** `created_at`; a row is visible when `created_at <= as_of`.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `app_db_customer_id` | string (`object`) | no | Canonical app customer ID, assigned chronologically by creation. |
| `created_at` | timestamp | no | Sign-up date: the first order (or first subscription term) for ordering customers; a drawn date for sign-ups that never order. |
| `segment` | string | no | `consumer`, `smb`, or `enterprise`. |
| `account_type` | string | no | `customer`, `test` (QA accounts), or `internal` (Shorelane's own consumption). **Only `customer` rows count toward revenue** — the exclusion is applied in `fct_revenue`, not here. |
| `acquisition_channel` | string | no | Canonical channel of the first order, or `signup` for never-ordered accounts. |

`app_db__orders.customer_id` is a real FK to this table's
`app_db_customer_id`; it is no longer an unresolved customer reference.

## `stripe__customers`

**Raw grain:** one row per Stripe customer account identity, not one row per canonical
customer. A recreated account produces one historical row and one current row for the
same underlying app customer.

**Primary key:** `stripe_customer_id`.

**Arrival column:** `created_at`; a row is visible when `created_at <= as_of`.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `stripe_customer_id` | string (`object`) | no | Opaque Stripe-native customer ID. It does not encode the app ID. |
| `created_at` | timestamp (`datetime64[ns]`) | no | When this Stripe identity was created. Initial identities begin with the customer's first d2c or marketplace order; replacement identities begin at recreation. |
| `is_active` | boolean (`bool`) | no | Whether this Stripe identity is active in the full generated snapshot. |
| `deactivated_at` | timestamp (`datetime64[ns]`) | yes | Recreation time for a historical identity; null for the current or never-recreated identity. |

### Historical as-of masking

The full generated table already contains future deactivations. `visible_tables()` must
not leak that future state: before `deactivated_at`, it masks the timestamp to null and
restores `is_active = true`. At the recreation timestamp, the old identity becomes
inactive and its `deactivated_at` appears while the new identity arrives as active.
Therefore a null `deactivated_at` in an as-of snapshot can mean either “not deactivated”
or “a later deactivation has not arrived yet.”

## `shopify__customers`

**Raw grain:** one row per Shopify-native customer identity for an app customer with a
d2c order.

**Primary key:** `shopify_customer_id`.

**Arrival column:** `created_at`; a row is visible when `created_at <= as_of`.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `shopify_customer_id` | string (`object`) | no | Opaque Shopify-native customer ID; no canonical app ID is present. |
| `created_at` | timestamp (`datetime64[ns]`) | no | Customer's first d2c order time. |
| `is_active` | boolean (`bool`) | no | Source-system active flag; all generated Shopify identities are active in this release candidate. |

## `salesforce__customers`

**Raw grain:** one row per Salesforce-native customer identity for an app customer with
a business-subscription order.

**Primary key:** `salesforce_customer_id`.

**Arrival column:** `created_at`; a row is visible when `created_at <= as_of`.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `salesforce_customer_id` | string (`object`) | no | Opaque Salesforce-native customer ID; no canonical app ID is present. |
| `created_at` | timestamp (`datetime64[ns]`) | no | Customer's first business-subscription order time. |
| `is_active` | boolean (`bool`) | no | Source-system active flag; all generated Salesforce identities are active in this release candidate. |

## `app_db__customer_id_crosswalk`

**Raw grain:** one row per **retained source alias → canonical app customer** mapping.
It includes app self-mappings and retained Stripe, Shopify, and Salesforce mappings.
It is not one row per app customer: one app customer can have 2–4 active source aliases,
and a recreated Stripe account adds a historical alias.

**Composite uniqueness / qualified source key:**
(`source_system`, `source_customer_id`). Always use both columns when joining the
crosswalk; source IDs are scoped to their source system even if the generated prefixes
currently happen not to collide.

**Arrival column:** `linked_at`; a mapping is visible when `linked_at <= as_of`.
`linked_at` is never earlier than either the source customer or app customer creation
time, so a visible crosswalk row never precedes either endpoint.

| column | generated type | nullable | meaning |
|---|---|---:|---|
| `source_system` | string (`object`) | no | `app_db`, `stripe`, `shopify`, or `salesforce`. |
| `source_customer_id` | string (`object`) | no | ID as represented in `source_system`. For `app_db`, this equals `app_db_customer_id`. |
| `app_db_customer_id` | string (`object`) | no | Canonical FK to `app_db__customers.app_db_customer_id`. |
| `linked_at` | timestamp (`datetime64[ns]`) | no | When this bridge record became available. |
| `link_method` | string (`object`) | no | `primary_key` for app self-mappings, `2021_migration` for retained pre-migration Shopify/Salesforce aliases, or `direct_sync` for other external aliases. |

### Intentional 2021 migration loss

The generator first constructs a complete bridge for every observed source identity.
Only after that complete bridge exists does canonical generation delete a deterministic
fraction (`IDENTITY_CROSSWALK_DROP_RATE`, currently 12%) of mappings eligible under
both conditions:

- source is Shopify or Salesforce; and
- source identity was created before `IDENTITY_MIGRATION_DATE` (2021-07-01).

The source customer rows themselves are **not** dropped. Retained eligible mappings
arrive at the migration date with `link_method = '2021_migration'`; dropped mappings
are absent altogether, not represented by a row with a null app ID. Stripe mappings,
app self-mappings, and post-migration Shopify/Salesforce mappings are not eligible for
this planted deletion. `plant_migration_gap=False` is an audit/test seam that returns
the complete pre-deletion bridge; normal `dataset.generate()` uses the incomplete one.

## Safe join rules

- Join `app_db__orders.customer_id = app_db__customers.app_db_customer_id` directly.
- `order_id` is the safe event relationship: invoices, refunds, and recognition rows
  all join to `app_db__orders.order_id`. Invoice and refund `order_id` values are unique
  in their own tables; recognition is unique only by
  (`order_id`, `recognition_date`) and therefore has multiple rows for subscriptions.
- `app_db__invoices.salesforce_customer_id` can join directly to
  `salesforce__customers.salesforce_customer_id`; `stripe__refunds.stripe_customer_id`
  can join directly to `stripe__customers.stripe_customer_id`. These are source-native
  references, not canonical app IDs.
- To resolve any external customer to the app customer, join its native ID to
  `source_customer_id` **and** constrain `source_system`, then use
  `app_db_customer_id`. Prefer a left join and measure unmatched rows: an inner join
  silently drops the planted pre-2021 Shopify/Salesforce gap.
- Never join IDs across external source tables by value, and never assume an external
  customer table has a hidden canonical app ID. Its absence is intentional.

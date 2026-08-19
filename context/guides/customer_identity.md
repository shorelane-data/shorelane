# Customer identity: canonical grain and safe fact joins

Use this guide whenever a question combines app customers with Stripe, Shopify, or
Salesforce identities. The source tables describe aliases; they do not define the
business-customer grain.

## Safe model contract

- `dim_customers` has **one row per canonical app ID** (`app_db_customer_id`). For a
  business customer count, query this dimension and filter `has_order = true`.
  Profiles with no orders are resolvable app profiles, not ordered customers.
- `int_customer_identity` has **one row per source alias**. Its unique,
  source-qualified key is `(source_system, source_customer_id)`. It has a nullable app_db_customer_id;
  raw ID text is not a cross-system key.
- Never inner join away unresolved aliases when measuring identity quality, and
  never guess or manufacture a canonical ID for an unresolved alias. Start from
  observed aliases and left join the crosswalk.
- `fct_identity_resolution_quality` is the safe aggregate for identity-quality
  reporting. Its base grain is one row per `source_system` (optionally source month
  in future versions), based on the warehouse's current as-of load state.
- The overall null rate can include ordinary sync lag at an as-of snapshot. The
  pre-migration Shopify cohort isolates the planted permanent migration gap, so do
  not treat every snapshot null as permanent or every null as temporary.

## Multi-source eligibility

A multi-source customer resolves in at least two distinct resolved source systems
at the pinned snapshot. app_db counts as a source system, alongside Stripe,
Shopify, and Salesforce. Count systems, not aliases.

Historical Stripe aliases are included in identity-quality totals and in the long
bridge. Both active and inactive aliases can resolve to one app customer; joining
that bridge directly to facts can fan out orders and money.

To aggregate facts safely, derive a deduplicated canonical customer set from the
identity bridge, then filter `dim_customers` or order facts by that set. Never sum
an order once per source alias. Use `dim_customers` for customer counts and the
deduplicated canonical customer set for facts.

## Time rules

All identity membership and quality metrics are **as of 2025-12-31**: source rows
must be created by the snapshot and crosswalk links must be available by it.
Questions with a fact window use only fully elapsed periods. For the pinned 2024
GMV question, include order dates from 2024-01-01 through 2024-12-31, inclusive;
the full year is fully elapsed before the identity as-of snapshot. The migration
cohort uses `created_at < 2021-07-01`, not less-than-or-equal.

GMV is gross order amount before refunds. Once eligibility is resolved as of the
pinned snapshot, each eligible order in the fully elapsed fact window contributes
exactly once.

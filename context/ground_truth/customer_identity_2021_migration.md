# Customer identity ground truth: 2021 migration gap

This file is generated, not hand-authored. Reproduce it with:

```bash
python -m generators.identity_measures --output context/ground_truth/customer_identity_2021_migration.md
```

## Pinned scope and grains

- **Dataset:** `shorelane-v4` with seed `20190401`.
- **Identity migration cutoff:** **2021-07-01**.
- **Snapshot:** rows visible as of **2025-12-31**, using `loaders.visibility.visible_tables` over `generators.dataset.generate()`.
- **Observed source ID grain:** one visible source customer row keyed by `(source_system, source_customer_id)` across `app_db`, `stripe`, `shopify`, and `salesforce`.
- **Historical Stripe aliases:** **included**. Both active and inactive visible Stripe customer records enter the observed and resolved alias bridge.
- **Resolution:** left join observed source IDs to the visible crosswalk on `(source_system, source_customer_id)`. The inner-join count is the retained subset; null rate is unresolved / observed. Snapshot-unresolved IDs can be permanently missing 2021 migration mappings or ordinary source rows whose direct-sync crosswalk has a `linked_at` after the snapshot; the pre-migration Shopify section isolates the planted permanent gap.
- **Ordered canonical customers:** distinct `app_db__orders.customer_id` among orders visible at the snapshot (all dates through the snapshot).
- **Pre-migration Shopify:** visible Shopify customers with `created_at < 2021-07-01`; resolved and missing refer to crosswalk presence at the snapshot.
- **GMV window:** inclusive **2024-01-01** through **2024-12-31**. Eligible customers have resolved aliases in at least two distinct source systems at the snapshot; `app_db` counts as a source system alongside `stripe`, `shopify`, and `salesforce`.
- **Correct GMV/order grain:** deduplicate eligible `app_db_customer_id` values, then filter orders; each order contributes once. GMV is gross of refunds.
- **Unsafe fanout grain:** join those same orders to the long resolved alias bridge on app customer ID without deduplicating aliases; each order contributes once per resolved alias, including historical Stripe aliases.

## Identity resolution measures

| Measure | Derived value |
|---|---:|
| Observed source-ID count | 70,975 |
| Naive distinct raw source-ID count (source namespace ignored) | 70,975 |
| Inner-join retained / resolved source-ID count | 69,795 |
| Unresolved source-ID count | 1,180 |
| Resolution null rate | 0.016626 |
| Distinct resolved canonical app IDs | 25,359 |
| Ordered canonical customer count as of snapshot | 22,628 |

## Pre-migration Shopify crosswalk

| Measure | Derived value |
|---|---:|
| Observed pre-migration Shopify IDs | 4,567 |
| Resolved pre-migration Shopify IDs | 4,034 |
| Missing pre-migration Shopify IDs | 533 |

## 2024 multi-source customer GMV: correct vs unsafe

| Path | Canonical customers | Order rows | GMV |
|---|---:|---:|---:|
| Correct (deduplicated canonical customer set) | 22,393 | 13,195 | $25,733,431.14 |
| Unsafe alias-bridge fanout | — | 43,501 | $91,761,496.64 |

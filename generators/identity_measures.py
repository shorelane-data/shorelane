"""Canonical reference measures for customer-identity fragmentation.

The reference starts from ``dataset.generate()`` and applies the same as-of arrival
rules as warehouse loaders. Run the module to print or update committed ground truth:

    python -m generators.identity_measures
    python -m generators.identity_measures --output context/ground_truth/customer_identity_2021_migration.md
"""
from __future__ import annotations

import argparse
import pathlib
from collections.abc import Mapping

import pandas as pd

import config
from generators import dataset
from loaders.visibility import visible_tables

AS_OF = "2025-12-31"
GMV_START = "2024-01-01"
GMV_END = "2024-12-31"

_SOURCE_TABLES = (
    ("app_db", "app_db__customers", "app_db_customer_id"),
    ("stripe", "stripe__customers", "stripe_customer_id"),
    ("shopify", "shopify__customers", "shopify_customer_id"),
    ("salesforce", "salesforce__customers", "salesforce_customer_id"),
)


def _observed_aliases(tables: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Return one row per visible source-native customer record.

    Stripe records include active and inactive (historical) aliases. Source system
    remains part of the identity key even though this fixture's prefixes also make
    the raw ID strings globally distinct.
    """
    frames = []
    for source_system, table_name, id_column in _SOURCE_TABLES:
        source = tables[table_name]
        frames.append(
            pd.DataFrame(
                {
                    "source_system": source_system,
                    "source_customer_id": source[id_column].astype("string"),
                    "source_created_at": source["created_at"],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def derive_identity_measures(
    tables: Mapping[str, pd.DataFrame],
    *,
    as_of: str = AS_OF,
    gmv_start: str = GMV_START,
    gmv_end: str = GMV_END,
) -> dict[str, int | float | str]:
    """Derive identity and join-trap measures at explicitly pinned grains.

    Counts over aliases are at ``(source_system, source_customer_id)`` grain.
    Correct GMV is at order grain after deduplicating eligible canonical customers;
    unsafe GMV intentionally remains at order-by-resolved-alias grain.
    """
    visible = visible_tables(dict(tables), as_of)
    aliases = _observed_aliases(visible)
    crosswalk = visible["app_db__customer_id_crosswalk"]
    resolved = aliases.merge(
        crosswalk[
            ["source_system", "source_customer_id", "app_db_customer_id"]
        ],
        on=["source_system", "source_customer_id"],
        how="left",
        validate="one_to_one",
    )

    observed_count = int(len(resolved))
    if observed_count == 0:
        raise ValueError(
            "cannot calculate identity resolution over zero observed source IDs"
        )
    resolved_mask = resolved["app_db_customer_id"].notna()
    resolved_count = int(resolved_mask.sum())
    unresolved_count = observed_count - resolved_count
    resolved_aliases = resolved.loc[resolved_mask].copy()

    orders = visible["app_db__orders"]
    ordered_canonical_count = int(orders["customer_id"].nunique())

    migration = pd.Timestamp(config.IDENTITY_MIGRATION_DATE)
    pre_shopify = resolved.loc[
        (resolved["source_system"] == "shopify")
        & (resolved["source_created_at"] < migration)
    ]
    pre_shopify_resolved = int(pre_shopify["app_db_customer_id"].notna().sum())
    pre_shopify_observed = int(len(pre_shopify))

    systems_per_customer = resolved_aliases.groupby("app_db_customer_id")[
        "source_system"
    ].nunique()
    eligible_customers = systems_per_customer[systems_per_customer >= 2].index

    in_gmv_window = (orders["order_date"] >= pd.Timestamp(gmv_start)) & (
        orders["order_date"] <= pd.Timestamp(gmv_end)
    )
    eligible_orders = orders.loc[
        in_gmv_window & orders["customer_id"].isin(eligible_customers)
    ]
    correct_order_count = int(len(eligible_orders))
    correct_gmv = round(float(eligible_orders["gross_amount"].sum()), 2)

    # Deliberately unsafe: each order is repeated once per resolved alias belonging
    # to the app customer. Historical Stripe aliases participate in this bridge.
    unsafe = eligible_orders.merge(
        resolved_aliases[["app_db_customer_id", "source_system", "source_customer_id"]],
        left_on="customer_id",
        right_on="app_db_customer_id",
        how="inner",
        validate="many_to_many",
    )

    return {
        "dataset_version": config.DATASET_VERSION,
        "seed": config.SEED,
        "identity_migration_date": config.IDENTITY_MIGRATION_DATE,
        "as_of": str(pd.Timestamp(as_of).date()),
        "gmv_start": str(pd.Timestamp(gmv_start).date()),
        "gmv_end": str(pd.Timestamp(gmv_end).date()),
        "observed_source_id_count": observed_count,
        "naive_distinct_source_id_count": int(aliases["source_customer_id"].nunique()),
        "inner_join_retained_source_id_count": resolved_count,
        "resolved_source_id_count": resolved_count,
        "unresolved_source_id_count": unresolved_count,
        "resolution_null_rate": round(unresolved_count / observed_count, 6),
        "distinct_resolved_canonical_id_count": int(
            resolved_aliases["app_db_customer_id"].nunique()
        ),
        "ordered_canonical_customer_count": ordered_canonical_count,
        "pre_migration_shopify_observed_count": pre_shopify_observed,
        "pre_migration_shopify_resolved_count": pre_shopify_resolved,
        "pre_migration_shopify_missing_count": pre_shopify_observed
        - pre_shopify_resolved,
        "multi_source_canonical_customer_count": int(len(eligible_customers)),
        "correct_multi_source_order_count": correct_order_count,
        "correct_multi_source_gmv": correct_gmv,
        "unsafe_fanout_order_row_count": int(len(unsafe)),
        "unsafe_fanout_gmv": round(float(unsafe["gross_amount"].sum()), 2),
    }


def render_markdown(measures: Mapping[str, int | float | str]) -> str:
    """Render the canonical, reproducible ground-truth document."""
    return f"""# Customer identity ground truth: 2021 migration gap

This file is generated, not hand-authored. Reproduce it with:

```bash
python -m generators.identity_measures --output context/ground_truth/customer_identity_2021_migration.md
```

## Pinned scope and grains

- **Dataset:** `{measures['dataset_version']}` with seed `{measures['seed']}`.
- **Identity migration cutoff:** **{measures['identity_migration_date']}**.
- **Snapshot:** rows visible as of **{measures['as_of']}**, using `loaders.visibility.visible_tables` over `generators.dataset.generate()`.
- **Observed source ID grain:** one visible source customer row keyed by `(source_system, source_customer_id)` across `app_db`, `stripe`, `shopify`, and `salesforce`.
- **Historical Stripe aliases:** **included**. Both active and inactive visible Stripe customer records enter the observed and resolved alias bridge.
- **Resolution:** left join observed source IDs to the visible crosswalk on `(source_system, source_customer_id)`. The inner-join count is the retained subset; null rate is unresolved / observed. Snapshot-unresolved IDs can be permanently missing 2021 migration mappings or ordinary source rows whose direct-sync crosswalk has a `linked_at` after the snapshot; the pre-migration Shopify section isolates the planted permanent gap.
- **Ordered canonical customers:** distinct `app_db__orders.customer_id` among orders visible at the snapshot (all dates through the snapshot).
- **Pre-migration Shopify:** visible Shopify customers with `created_at < {measures['identity_migration_date']}`; resolved and missing refer to crosswalk presence at the snapshot.
- **GMV window:** inclusive **{measures['gmv_start']}** through **{measures['gmv_end']}**. Eligible customers have resolved aliases in at least two distinct source systems at the snapshot; `app_db` counts as a source system alongside `stripe`, `shopify`, and `salesforce`.
- **Correct GMV/order grain:** deduplicate eligible `app_db_customer_id` values, then filter orders; each order contributes once. GMV is gross of refunds.
- **Unsafe fanout grain:** join those same orders to the long resolved alias bridge on app customer ID without deduplicating aliases; each order contributes once per resolved alias, including historical Stripe aliases.

## Identity resolution measures

| Measure | Derived value |
|---|---:|
| Observed source-ID count | {measures['observed_source_id_count']:,} |
| Naive distinct raw source-ID count (source namespace ignored) | {measures['naive_distinct_source_id_count']:,} |
| Inner-join retained / resolved source-ID count | {measures['inner_join_retained_source_id_count']:,} |
| Unresolved source-ID count | {measures['unresolved_source_id_count']:,} |
| Resolution null rate | {measures['resolution_null_rate']:.6f} |
| Distinct resolved canonical app IDs | {measures['distinct_resolved_canonical_id_count']:,} |
| Ordered canonical customer count as of snapshot | {measures['ordered_canonical_customer_count']:,} |

## Pre-migration Shopify crosswalk

| Measure | Derived value |
|---|---:|
| Observed pre-migration Shopify IDs | {measures['pre_migration_shopify_observed_count']:,} |
| Resolved pre-migration Shopify IDs | {measures['pre_migration_shopify_resolved_count']:,} |
| Missing pre-migration Shopify IDs | {measures['pre_migration_shopify_missing_count']:,} |

## 2024 multi-source customer GMV: correct vs unsafe

| Path | Canonical customers | Order rows | GMV |
|---|---:|---:|---:|
| Correct (deduplicated canonical customer set) | {measures['multi_source_canonical_customer_count']:,} | {measures['correct_multi_source_order_count']:,} | ${measures['correct_multi_source_gmv']:,.2f} |
| Unsafe alias-bridge fanout | — | {measures['unsafe_fanout_order_row_count']:,} | ${measures['unsafe_fanout_gmv']:,.2f} |
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="write Markdown to this path instead of stdout",
    )
    args = parser.parse_args(argv)
    markdown = render_markdown(derive_identity_measures(dataset.generate()))
    if args.output is None:
        print(markdown, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown)
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

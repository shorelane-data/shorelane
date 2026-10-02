"""Re-derive and validate the committed customer-identity ground truth.

Run directly (no pytest):

    python tests/check_identity_ground_truth.py
"""
from __future__ import annotations

import pathlib
import sys

import config
from generators import dataset
from generators.identity_measures import (
    AS_OF,
    GMV_END,
    GMV_START,
    derive_identity_measures,
    render_markdown,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
GROUND_TRUTH = REPO / "context" / "ground_truth" / "customer_identity_2021_migration.md"


def main() -> int:
    tables = dataset.generate()
    measures = derive_identity_measures(
        tables, as_of=AS_OF, gmv_start=GMV_START, gmv_end=GMV_END
    )

    assert measures["dataset_version"] == config.DATASET_VERSION
    assert measures["seed"] == config.SEED
    assert measures["identity_migration_date"] == config.IDENTITY_MIGRATION_DATE

    empty_observations = dict(tables)
    for table_name in (
        "app_db__customers",
        "stripe__customers",
        "shopify__customers",
        "salesforce__customers",
    ):
        empty_observations[table_name] = tables[table_name].iloc[0:0].copy()
    try:
        derive_identity_measures(empty_observations)
    except ValueError as exc:
        assert str(exc) == "cannot calculate identity resolution over zero observed source IDs"
    else:
        raise AssertionError("zero observed source IDs must be rejected explicitly")

    # Signature assertions make sure the planted join traps remain meaningful.
    assert measures["unresolved_source_id_count"] > 0
    assert 0 < measures["resolution_null_rate"] < 1
    assert (
        measures["resolved_source_id_count"] + measures["unresolved_source_id_count"]
        == measures["observed_source_id_count"]
    )
    assert (
        measures["inner_join_retained_source_id_count"]
        == measures["resolved_source_id_count"]
    )
    assert measures["naive_distinct_source_id_count"] > measures["ordered_canonical_customer_count"]
    assert measures["unsafe_fanout_gmv"] > measures["correct_multi_source_gmv"]
    assert (
        measures["unsafe_fanout_order_row_count"]
        > measures["correct_multi_source_order_count"]
    )
    assert measures["pre_migration_shopify_resolved_count"] > 0
    assert measures["pre_migration_shopify_missing_count"] > 0
    assert (
        measures["pre_migration_shopify_resolved_count"]
        + measures["pre_migration_shopify_missing_count"]
        == measures["pre_migration_shopify_observed_count"]
    )

    expected = render_markdown(measures)
    committed = GROUND_TRUTH.read_text()
    if committed != expected:
        print(
            f"{GROUND_TRUTH.relative_to(REPO)} does not match canonical re-derivation.\n"
            "Run: python -m generators.identity_measures "
            "--output context/ground_truth/customer_identity_2021_migration.md"
        )
        return 1

    print(
        "identity ground truth holds; unresolved, migration-gap, and fanout "
        "signature traps intact"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

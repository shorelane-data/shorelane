#!/usr/bin/env python3
"""Contract check for the canonical nine-table dataset and arrival rules."""
from __future__ import annotations

import sys

import pandas as pd

from generators import dataset, orders
from loaders.visibility import ARRIVAL_COLUMNS, visible_tables

EXPECTED_RAW_TABLES = (
    "app_db__orders",
    "app_db__invoices",
    "app_db__revenue_recognition",
    "stripe__refunds",
    "app_db__customers",
    "stripe__customers",
    "shopify__customers",
    "salesforce__customers",
    "app_db__customer_id_crosswalk",
)
EXPECTED_ARRIVALS = {
    "app_db__orders": "order_date",
    "app_db__invoices": "billed_date",
    "app_db__revenue_recognition": "recognition_date",
    "stripe__refunds": "refund_date",
    "app_db__customers": "created_at",
    "stripe__customers": "created_at",
    "shopify__customers": "created_at",
    "salesforce__customers": "created_at",
    "app_db__customer_id_crosswalk": "linked_at",
}


def main() -> int:
    failures: list[str] = []
    legacy = orders.generate()
    canonical = dataset.generate()

    if dataset.RAW_TABLES != EXPECTED_RAW_TABLES:
        failures.append(f"registry: expected {EXPECTED_RAW_TABLES!r}, got {dataset.RAW_TABLES!r}")
    if tuple(canonical) != EXPECTED_RAW_TABLES:
        failures.append(f"table order: expected {EXPECTED_RAW_TABLES!r}, got {tuple(canonical)!r}")
    if ARRIVAL_COLUMNS != EXPECTED_ARRIVALS:
        failures.append(f"arrival rules: expected {EXPECTED_ARRIVALS!r}, got {ARRIVAL_COLUMNS!r}")

    for name, frame in legacy.items():
        try:
            pd.testing.assert_frame_equal(canonical[name][list(frame.columns)], frame)
        except AssertionError as exc:
            failures.append(f"{name}: legacy columns/values changed: {exc}")

    original_generate = orders.generate
    calls = 0

    def counted_generate() -> dict[str, pd.DataFrame]:
        nonlocal calls
        calls += 1
        return legacy

    orders.generate = counted_generate
    try:
        dataset.generate()
    finally:
        orders.generate = original_generate
    if calls != 1:
        failures.append(f"orders.generate delegation count: expected 1, got {calls}")

    def incomplete_generate() -> dict[str, pd.DataFrame]:
        return {name: legacy[name] for name in tuple(legacy)[:-1]}

    orders.generate = incomplete_generate
    try:
        try:
            dataset.generate()
        except ValueError:
            pass
        else:
            failures.append("incomplete legacy mapping did not raise ValueError")
    finally:
        orders.generate = original_generate

    for as_of in ("2020-06-30", "2021-07-01", "2025-12-31"):
        visible = visible_tables(canonical, as_of)
        cutoff = pd.Timestamp(as_of)
        for name, frame in visible.items():
            arrival = ARRIVAL_COLUMNS[name]
            if (frame[arrival] > cutoff).any():
                failures.append(f"{name}: row later than {as_of} is visible")
        visible_sources = {
            "app_db": set(visible["app_db__customers"].app_db_customer_id),
            "stripe": set(visible["stripe__customers"].stripe_customer_id),
            "shopify": set(visible["shopify__customers"].shopify_customer_id),
            "salesforce": set(visible["salesforce__customers"].salesforce_customer_id),
        }
        visible_apps = visible_sources["app_db"]
        for row in visible["app_db__customer_id_crosswalk"].itertuples(index=False):
            if row.source_customer_id not in visible_sources[row.source_system]:
                failures.append(f"crosswalk visible before {row.source_system} source at {as_of}")
            if row.app_db_customer_id not in visible_apps:
                failures.append(f"crosswalk visible before app customer at {as_of}")

    if failures:
        print("Dataset orchestration check FAILED:")
        for failure in failures[:30]:
            print(f"  - {failure}")
        return 1

    print("Dataset orchestration check")
    for name in EXPECTED_RAW_TABLES:
        print(f"  {name:<36} rows={len(canonical[name]):>6}  OK")
    print("\nnine-table registry, legacy preservation, single delegation, and as-of visibility hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())

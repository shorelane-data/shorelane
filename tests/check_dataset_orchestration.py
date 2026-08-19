#!/usr/bin/env python3
"""Contract check for the canonical raw-dataset orchestration seam.

    python tests/check_dataset_orchestration.py
"""
from __future__ import annotations

import sys

import pandas as pd

from generators import dataset, orders
from loaders.visibility import ARRIVAL_COLUMNS

EXPECTED_RAW_TABLES = (
    "app_db__orders",
    "app_db__invoices",
    "app_db__revenue_recognition",
    "stripe__refunds",
)


def main() -> int:
    failures: list[str] = []

    if dataset.RAW_TABLES != EXPECTED_RAW_TABLES:
        failures.append(
            f"registry order: expected {EXPECTED_RAW_TABLES!r}, got {dataset.RAW_TABLES!r}"
        )

    legacy = orders.generate()
    canonical = dataset.generate()
    if tuple(canonical) != EXPECTED_RAW_TABLES:
        failures.append(
            f"generated table order: expected {EXPECTED_RAW_TABLES!r}, got {tuple(canonical)!r}"
        )
    for name in EXPECTED_RAW_TABLES:
        try:
            pd.testing.assert_frame_equal(canonical[name], legacy[name])
        except AssertionError as exc:
            failures.append(f"{name}: canonical output differs from legacy: {exc}")

    original_generate = orders.generate
    calls = 0

    def counted_generate() -> dict[str, pd.DataFrame]:
        nonlocal calls
        calls += 1
        return legacy

    orders.generate = counted_generate
    try:
        delegated = dataset.generate()
    finally:
        orders.generate = original_generate
    if calls != 1:
        failures.append(f"delegation count: expected 1, got {calls}")
    if delegated is not legacy:
        failures.append("dataset.generate() did not return the delegated mapping unchanged")

    def incomplete_generate() -> dict[str, pd.DataFrame]:
        return {name: legacy[name] for name in EXPECTED_RAW_TABLES[:-1]}

    orders.generate = incomplete_generate
    try:
        try:
            dataset.generate()
        except ValueError:
            pass
        else:
            failures.append("registry mismatch did not raise ValueError")
    finally:
        orders.generate = original_generate

    if tuple(ARRIVAL_COLUMNS) != EXPECTED_RAW_TABLES:
        failures.append(
            "ARRIVAL_COLUMNS coverage/order: "
            f"expected {EXPECTED_RAW_TABLES!r}, got {tuple(ARRIVAL_COLUMNS)!r}"
        )

    if failures:
        print("Dataset orchestration check FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("Dataset orchestration check")
    for name in EXPECTED_RAW_TABLES:
        print(f"  {name:<36} rows={len(canonical[name]):>6}  OK")
    print("\ncanonical registry, legacy equality, delegation, and arrival coverage hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())

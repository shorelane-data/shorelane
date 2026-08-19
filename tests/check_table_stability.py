#!/usr/bin/env python3
"""Characterization guard for the four legacy revenue tables.

This check deliberately freezes generator output independently of warehouse parity
and committed Markdown ground truth. Canonical scalar encoding avoids pandas CSV
formatting differences for nulls, timestamps, booleans, and IEEE-754 floats.

    python tests/check_table_stability.py
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import struct
import sys
from datetime import date, datetime
from numbers import Integral, Real
from typing import Any

import numpy as np
import pandas as pd

from generators import orders
from generators.measures import five_revenues

MANIFEST = pathlib.Path(__file__).with_name("table_stability_manifest.json")
PERIOD = ("2024-01-01", "2024-03-31")

PRIMARY_KEYS = {
    "app_db__orders": ["order_id"],
    "app_db__invoices": ["invoice_id"],
    "app_db__revenue_recognition": ["order_id", "recognition_date"],
    "stripe__refunds": ["refund_id"],
}
MONEY_COLUMNS = {
    "app_db__orders": ["gross_amount", "take_rate", "net_amount"],
    "app_db__invoices": ["amount"],
    "app_db__revenue_recognition": ["amount"],
    "stripe__refunds": ["refund_amount"],
}
DATE_COLUMNS = {
    "app_db__orders": ["order_date"],
    "app_db__invoices": ["billed_date", "due_date", "collected_date"],
    "app_db__revenue_recognition": ["recognition_date"],
    "stripe__refunds": ["refund_date"],
}
REVENUE_KEYS = [
    "gmv",
    "net_revenue",
    "recognized_revenue",
    "billed_revenue",
    "collected_cash",
]
MANIFEST_TABLE_FIELDS = {
    "columns",
    "row_count",
    "primary_key",
    "primary_key_hash",
    "money_hash",
    "date_hash",
    "content_hash",
}


def _canonical_scalar(value: Any) -> str:
    """Encode supported pandas scalar values without display-format dependence."""
    if value is None or value is pd.NaT:
        return "null"
    if isinstance(value, (pd.Timestamp, datetime, date, np.datetime64)):
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            return "null"
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        iso = (
            timestamp.strftime("%Y-%m-%dT%H:%M:%S")
            + f".{timestamp.microsecond:06d}{timestamp.nanosecond:03d}"
        )
        return "timestamp:" + iso
    if isinstance(value, (bool, np.bool_)):
        return "bool:true" if bool(value) else "bool:false"
    if isinstance(value, Integral):
        return "int:" + str(int(value))
    if isinstance(value, Real):
        number = float(value)
        if math.isnan(number):
            return "null"
        return "float64:" + struct.pack(">d", number).hex()
    if isinstance(value, str):
        return "str:" + value
    raise TypeError(f"unsupported scalar for stability hash: {type(value).__name__}")


def stable_hash(frame: pd.DataFrame, columns: list[str], primary_key: list[str]) -> str:
    """Hash compact canonical JSON of selected columns in primary-key order."""
    ordered = frame.sort_values(primary_key, kind="stable")
    payload = {
        "columns": columns,
        "rows": [
            [_canonical_scalar(value) for value in row]
            for row in ordered.loc[:, columns].itertuples(index=False, name=None)
        ],
    }
    serialized = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def characterize(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    characterized: dict[str, Any] = {}
    for name, frame in tables.items():
        primary_key = PRIMARY_KEYS[name]
        if frame.duplicated(primary_key).any():
            raise AssertionError(f"{name}: primary key is not unique: {primary_key}")
        characterized[name] = {
            "columns": list(frame.columns),
            "row_count": len(frame),
            "primary_key": primary_key,
            "primary_key_hash": stable_hash(frame, primary_key, primary_key),
            "money_hash": stable_hash(frame, MONEY_COLUMNS[name], primary_key),
            "date_hash": stable_hash(frame, DATE_COLUMNS[name], primary_key),
            "content_hash": stable_hash(frame, list(frame.columns), primary_key),
        }
    return characterized


def manifest_errors(expected: dict[str, Any]) -> list[str]:
    """Return structural errors that could otherwise weaken the frozen contract."""
    errors: list[str] = []
    required_top_level = {"tables", "q1_2024_five_revenues"}
    if set(expected) != required_top_level:
        errors.append(
            "top-level fields: "
            f"expected {sorted(required_top_level)!r}, got {sorted(expected)!r}"
        )
        return errors

    if set(expected["tables"]) != set(PRIMARY_KEYS):
        errors.append(
            "manifest tables: "
            f"expected {sorted(PRIMARY_KEYS)!r}, got {sorted(expected['tables'])!r}"
        )
    for name, table in expected["tables"].items():
        if set(table) != MANIFEST_TABLE_FIELDS:
            errors.append(
                f"{name} fields: expected {sorted(MANIFEST_TABLE_FIELDS)!r}, "
                f"got {sorted(table)!r}"
            )

    if set(expected["q1_2024_five_revenues"]) != set(REVENUE_KEYS):
        errors.append(
            "revenue fields: "
            f"expected {sorted(REVENUE_KEYS)!r}, "
            f"got {sorted(expected['q1_2024_five_revenues'])!r}"
        )
    return errors


def main() -> int:
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures = manifest_errors(expected)
    if failures:
        print("Table stability manifest is incomplete or malformed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    tables = orders.generate()
    if set(tables) != set(expected["tables"]):
        print("Legacy table stability check FAILED:")
        print(
            f"  table names: expected {list(expected['tables'])!r}, "
            f"got {list(tables)!r}"
        )
        return 1

    actual_tables = characterize(tables)
    actual_revenues = five_revenues(tables, *PERIOD)

    failures = []

    print("Legacy table stability check")
    for name, wanted in expected["tables"].items():
        got = actual_tables.get(name)
        if got is None:
            print(f"  {name:<36} MISSING")
            continue
        mismatches = [key for key, value in wanted.items() if got.get(key) != value]
        status = "OK" if not mismatches else f"MISMATCH ({', '.join(mismatches)})"
        print(f"  {name:<36} rows={got['row_count']:>6}  {status}")
        for key in mismatches:
            failures.append(f"{name}.{key}: expected {wanted[key]!r}, got {got.get(key)!r}")

    print(f"\nQ1 2024 five revenues ({PERIOD[0]} .. {PERIOD[1]})")
    for key in REVENUE_KEYS:
        wanted = expected["q1_2024_five_revenues"][key]
        got = actual_revenues[key]
        ok = got == wanted
        print(f"  {key:<20} expected={wanted:>15,.2f}  actual={got:>15,.2f}  {'OK' if ok else 'MISMATCH'}")
        if not ok:
            failures.append(f"q1_2024_five_revenues.{key}: expected {wanted!r}, got {got!r}")

    if failures:
        print("\nTable stability check FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nall legacy table schemas, rows, hashes, and revenues are stable")
    return 0


if __name__ == "__main__":
    sys.exit(main())

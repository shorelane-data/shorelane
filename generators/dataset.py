"""Canonical orchestration for the raw Shorelane dataset.

The registry is the ordered contract shared by generators, loaders, and arrival
filtering. The legacy orders generator remains the only implementation until new
tables are added in later tasks.
"""
from __future__ import annotations

import pandas as pd

from generators import orders

RAW_TABLES = (
    "app_db__orders",
    "app_db__invoices",
    "app_db__revenue_recognition",
    "stripe__refunds",
)


def generate() -> dict[str, pd.DataFrame]:
    """Generate every registered raw table through the legacy generator once."""
    tables = orders.generate()
    generated = tuple(tables)
    if generated != RAW_TABLES:
        raise ValueError(
            "raw table registry does not match generated tables: "
            f"expected {RAW_TABLES!r}, got {generated!r}"
        )
    return tables

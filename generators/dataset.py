"""Canonical orchestration for the raw Shorelane dataset.

The registry is the ordered contract shared by generators, loaders, and arrival
filtering. ``orders.generate`` supplies the byte-stable revenue base once, then
``identity.generate`` copies/enriches it and adds source-native customer tables.
"""
from __future__ import annotations

import pandas as pd

from generators import identity, orders

RAW_TABLES = (
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


def generate() -> dict[str, pd.DataFrame]:
    """Generate every registered raw table through the legacy generator once."""
    tables = identity.generate(orders.generate())
    generated = tuple(tables)
    if generated != RAW_TABLES:
        raise ValueError(
            "raw table registry does not match generated tables: "
            f"expected {RAW_TABLES!r}, got {generated!r}"
        )
    return tables

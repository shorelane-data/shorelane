"""Canonical orchestration for the raw Shorelane dataset.

The registry is the ordered contract shared by generators, loaders, and arrival
filtering. ``orders.generate`` supplies the commerce tables once, ``identity.generate``
copies/enriches them and adds source-native customer tables, and ``support.generate``
adds Zendesk tickets keyed to those source-native identities.
"""
from __future__ import annotations

import pandas as pd

from generators import identity, orders, support

RAW_TABLES = (
    "app_db__customers",
    "app_db__products",
    "app_db__orders",
    "app_db__order_lines",
    "app_db__plans",
    "app_db__plan_prices",
    "app_db__subscriptions",
    "app_db__invoices",
    "app_db__revenue_recognition",
    "app_db__promotions",
    "stripe__refunds",
    "erp__suppliers",
    "erp__supplier_shipments",
    "ads__daily_spend",
    "stripe__customers",
    "shopify__customers",
    "salesforce__customers",
    "app_db__customer_id_crosswalk",
    "zendesk__tickets",
)


def generate() -> dict[str, pd.DataFrame]:
    """Generate every registered raw table through the commerce generator once."""
    tables = support.generate(identity.generate(orders.generate()))
    generated = tuple(tables)
    if generated != RAW_TABLES:
        raise ValueError(
            "raw table registry does not match generated tables: "
            f"expected {RAW_TABLES!r}, got {generated!r}"
        )
    return tables

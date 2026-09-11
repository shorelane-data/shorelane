"""Deterministic source-native customer identity fragmentation.

Identity randomness is isolated from the commerce streams:
  stream 10: (retired in v4 — sign-up dates now come from generators/customers.py)
  stream 11: opaque Stripe ID assignment
  stream 12: opaque Shopify ID assignment
  stream 13: opaque Salesforce ID assignment
  stream 14: Stripe account recreation cohort and dates
  stream 15: opaque recreated Stripe ID assignment
  stream 16: ordinary crosswalk-link arrival lags
  stream 17: planted pre-migration Shopify/Salesforce crosswalk deletion

External IDs are stable sequential values assigned through seeded permutations; they
never encode or expose the canonical app customer ID.
"""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

import config
from generators.common import canonical_channel, make_rng


def _assign_ids(
    customer_ids: Iterable[str], prefix: str, rng: np.random.Generator
) -> dict[str, str]:
    """Assign opaque sequential source IDs without embedding canonical IDs."""
    customers = sorted(customer_ids)
    sequence = np.arange(1, len(customers) + 1)
    rng.shuffle(sequence)
    return {
        customer_id: f"{prefix}_{number:08d}"
        for customer_id, number in zip(customers, sequence, strict=True)
    }


def _first_channel_date(orders: pd.DataFrame, channels: set[str]) -> pd.Series:
    canonical = canonical_channel(orders.channel)
    return (
        orders.loc[canonical.isin(channels)]
        .groupby("customer_id", sort=True)["order_date"]
        .min()
    )


def _source_frame(
    id_column: str, identity_map: dict[str, str], created: pd.Series
) -> pd.DataFrame:
    rows = [
        (source_id, pd.Timestamp(created.loc[customer_id]), True)
        for customer_id, source_id in identity_map.items()
    ]
    return pd.DataFrame(rows, columns=[id_column, "created_at", "is_active"]).sort_values(
        id_column, kind="stable", ignore_index=True
    )


REQUIRED_COMMERCE_TABLES = (
    "app_db__customers",
    "app_db__orders",
    "app_db__invoices",
    "stripe__refunds",
)


def generate(
    commerce_tables: dict[str, pd.DataFrame], *, plant_migration_gap: bool = True
) -> dict[str, pd.DataFrame]:
    """Copy/enrich commerce frames and append the identity raw tables.

    ``plant_migration_gap=False`` is the auditable test seam for inspecting the
    complete pre-deletion bridge. Canonical dataset generation always uses the
    default and therefore exposes only the intentionally incomplete crosswalk.
    """
    missing = [name for name in REQUIRED_COMMERCE_TABLES if name not in commerce_tables]
    if missing:
        raise ValueError(f"identity generator missing commerce tables {missing!r}")

    tables = {name: frame.copy(deep=True) for name, frame in commerce_tables.items()}
    orders = tables["app_db__orders"]
    app_customers = tables["app_db__customers"]
    customer_pool = sorted(app_customers.app_db_customer_id)

    # Ordered app customers exist no later than their first order (the commerce
    # generator sets created_at from the first order / sign-up date).
    pool_dates = pd.Series(
        pd.to_datetime(app_customers.created_at.values), index=app_customers.app_db_customer_id.values
    )

    stripe_created = _first_channel_date(orders, {"d2c", "marketplace"})
    shopify_created = _first_channel_date(orders, {"d2c"})
    salesforce_created = _first_channel_date(orders, {"business_subscription"})

    stripe_initial = _assign_ids(stripe_created.index, "cus", make_rng(stream=11))
    shopify_ids = _assign_ids(shopify_created.index, "shp", make_rng(stream=12))
    salesforce_ids = _assign_ids(
        salesforce_created.index, "sfc", make_rng(stream=13)
    )

    recreation_rng = make_rng(stream=14)
    stripe_customers_sorted = sorted(stripe_initial)
    recreate_mask = recreation_rng.random(len(stripe_customers_sorted)) < config.STRIPE_ACCOUNT_RECREATION_RATE
    recreate_mask &= np.array(
        [pd.Timestamp(stripe_created.loc[customer]) < pd.Timestamp(config.END_DATE) for customer in stripe_customers_sorted]
    )
    recreated = [customer for customer, selected in zip(stripe_customers_sorted, recreate_mask, strict=True) if selected]
    recreated_ids = _assign_ids(recreated, "cus_r", make_rng(stream=15))
    end = pd.Timestamp(config.END_DATE)
    recreation_dates: dict[str, pd.Timestamp] = {}
    for customer_id in recreated:
        start = pd.Timestamp(stripe_created.loc[customer_id])
        available_days = max((end - start).days, 0)
        offset = int(recreation_rng.integers(1, available_days + 1)) if available_days else 0
        recreation_dates[customer_id] = start + pd.Timedelta(days=offset)

    stripe_rows: list[tuple[str, pd.Timestamp, bool, pd.Timestamp | None]] = []
    stripe_active: dict[str, str] = {}
    for customer_id, initial_id in stripe_initial.items():
        initial_created_at = stripe_created.loc[customer_id]
        if customer_id in recreated_ids:
            stripe_rows.append(
                (
                    initial_id,
                    initial_created_at,
                    False,
                    recreation_dates[customer_id],
                )
            )
            current_id = recreated_ids[customer_id]
            stripe_rows.append((current_id, recreation_dates[customer_id], True, None))
            stripe_active[customer_id] = current_id
        else:
            stripe_rows.append((initial_id, initial_created_at, True, None))
            stripe_active[customer_id] = initial_id
    stripe_customers = pd.DataFrame.from_records(
        stripe_rows,
        columns=["stripe_customer_id", "created_at", "is_active", "deactivated_at"],
    ).sort_values("stripe_customer_id", kind="stable", ignore_index=True)
    shopify_customers = _source_frame("shopify_customer_id", shopify_ids, shopify_created)
    salesforce_customers = _source_frame(
        "salesforce_customer_id", salesforce_ids, salesforce_created
    )

    # Build the complete mapping first. Only after all observations exist do we
    # plant the migration loss in a copy of the bridge.
    aliases: list[tuple[str, str, str, pd.Timestamp]] = []
    aliases.extend(("app_db", customer, customer, pd.Timestamp(pool_dates.loc[customer])) for customer in customer_pool)
    for customer_id, source_id in stripe_initial.items():
        aliases.append(("stripe", source_id, customer_id, pd.Timestamp(stripe_created.loc[customer_id])))
    for customer_id, source_id in recreated_ids.items():
        aliases.append(("stripe", source_id, customer_id, recreation_dates[customer_id]))
    aliases.extend(("shopify", source_id, customer, pd.Timestamp(shopify_created.loc[customer])) for customer, source_id in shopify_ids.items())
    aliases.extend(("salesforce", source_id, customer, pd.Timestamp(salesforce_created.loc[customer])) for customer, source_id in salesforce_ids.items())

    link_rng = make_rng(stream=16)
    migration_date = pd.Timestamp(config.IDENTITY_MIGRATION_DATE)
    crosswalk_rows = []
    for source_system, source_id, app_id, source_date in aliases:
        earliest = max(source_date, pd.Timestamp(pool_dates.loc[app_id]))
        migration_alias = source_system in {"shopify", "salesforce"} and source_date < migration_date
        if source_system == "app_db":
            linked_at = earliest
            method = "primary_key"
        elif migration_alias:
            linked_at = max(earliest, migration_date)
            method = "2021_migration"
        else:
            linked_at = min(earliest + pd.Timedelta(days=int(link_rng.integers(0, 31))), end)
            method = "direct_sync"
        crosswalk_rows.append((source_system, source_id, app_id, linked_at, method, source_date))
    complete = pd.DataFrame(
        crosswalk_rows,
        columns=["source_system", "source_customer_id", "app_db_customer_id", "linked_at", "link_method", "source_created_at"],
    )
    complete = complete.sort_values(
        ["source_system", "source_customer_id"], kind="stable", ignore_index=True
    )
    if plant_migration_gap:
        eligible = complete.source_system.isin(["shopify", "salesforce"]) & (
            complete.source_created_at < migration_date
        )
        drop_draw = make_rng(stream=17).random(len(complete))
        complete = complete.loc[
            ~(eligible & (drop_draw < config.IDENTITY_CROSSWALK_DROP_RATE))
        ].reset_index(drop=True)
    crosswalk = complete.drop(columns="source_created_at")

    customer_by_order = orders.set_index("order_id").customer_id
    invoices = tables["app_db__invoices"]
    invoices["salesforce_customer_id"] = pd.Series(
        invoices.order_id.map(customer_by_order).map(salesforce_ids), dtype="string"
    )
    refunds = tables["stripe__refunds"]
    refund_customers = refunds.order_id.map(customer_by_order)
    refund_ids = []
    for customer_id, refund_date in zip(refund_customers, refunds.refund_date, strict=True):
        if customer_id in recreation_dates and pd.Timestamp(refund_date) < recreation_dates[customer_id]:
            refund_ids.append(stripe_initial[customer_id])
        else:
            refund_ids.append(stripe_active[customer_id])
    refunds["stripe_customer_id"] = pd.Series(refund_ids, dtype="string")

    return {
        **tables,
        "stripe__customers": stripe_customers,
        "shopify__customers": shopify_customers,
        "salesforce__customers": salesforce_customers,
        "app_db__customer_id_crosswalk": crosswalk,
    }

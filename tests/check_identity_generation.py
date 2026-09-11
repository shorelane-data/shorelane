#!/usr/bin/env python3
"""Executable contract check for deterministic identity fragmentation."""
from __future__ import annotations

import sys

import pandas as pd

import config
from generators import dataset, identity, orders
from generators.common import canonical_channel
from loaders.visibility import visible_tables

EXTERNAL_TABLES = {
    "stripe": ("stripe__customers", "stripe_customer_id"),
    "shopify": ("shopify__customers", "shopify_customer_id"),
    "salesforce": ("salesforce__customers", "salesforce_customer_id"),
}


def check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []
    legacy = orders.generate()
    first = dataset.generate()
    second = dataset.generate()
    # "legacy" here means the commerce tables identity enriches; v4 appends only to invoices/refunds.

    for name in first:
        try:
            pd.testing.assert_frame_equal(first[name], second[name])
        except AssertionError as exc:
            failures.append(f"repeated generation differs for {name}: {exc}")

    for name, frame in legacy.items():
        legacy_columns = list(frame.columns)
        check(
            list(first[name].columns[: len(legacy_columns)]) == legacy_columns,
            f"{name}: legacy columns were not preserved in order",
            failures,
        )
        try:
            pd.testing.assert_frame_equal(first[name][legacy_columns], frame)
        except AssertionError as exc:
            failures.append(f"{name}: legacy values changed: {exc}")

    check(
        list(first["app_db__invoices"].columns)[-1:] == ["salesforce_customer_id"],
        "invoices: nullable salesforce_customer_id was not appended",
        failures,
    )
    check(
        list(first["stripe__refunds"].columns)[-1:] == ["stripe_customer_id"],
        "refunds: nullable stripe_customer_id was not appended",
        failures,
    )

    observations = [
        first["app_db__customers"][["app_db_customer_id", "created_at"]]
        .rename(columns={"app_db_customer_id": "source_customer_id"})
        .assign(source_system="app_db", is_active=True)
    ]
    for system, (table, id_column) in EXTERNAL_TABLES.items():
        frame = first[table]
        check(
            "app_db_customer_id" not in frame.columns,
            f"{table}: external table exposes canonical app ID",
            failures,
        )
        observations.append(
            frame[[id_column, "created_at", "is_active"]]
            .rename(columns={id_column: "source_customer_id"})
            .assign(source_system=system)
        )
    observed = pd.concat(observations, ignore_index=True)
    check(
        not observed.duplicated(["source_system", "source_customer_id"]).any(),
        "source observations are not globally unique by qualified source key",
        failures,
    )

    orders_frame = first["app_db__orders"]
    ordered = canonical_channel(orders_frame["channel"]).groupby(orders_frame["customer_id"]).agg(set)
    active = observed[observed["is_active"]]
    complete = identity.generate(legacy, plant_migration_gap=False)
    complete_crosswalk = complete["app_db__customer_id_crosswalk"]
    active_bridge = complete_crosswalk.merge(active[qualified := ["source_system", "source_customer_id"]], on=qualified)
    active_systems = active_bridge.groupby("app_db_customer_id")["source_system"].agg(set)
    active_row_counts = active_bridge.groupby("app_db_customer_id").size()
    for customer_id, channels in ordered.items():
        required = {"app_db", "stripe"} if channels & {"d2c", "marketplace"} else {"app_db"}
        if "d2c" in channels:
            required.add("shopify")
        if "business_subscription" in channels:
            required.add("salesforce")
        actual = active_systems.loc[customer_id]
        check(actual == required, f"{customer_id}: active aliases {actual} != {required}", failures)
        active_row_count = int(active_row_counts.loc[customer_id])
        check(
            active_row_count == len(required) and 2 <= active_row_count <= 4,
            f"{customer_id}: active alias row count {active_row_count} does not match {len(required)} required sources",
            failures,
        )

    stripe = first["stripe__customers"]
    check((~stripe.is_active).any(), "Stripe recreation produced no historical inactive IDs", failures)
    stripe_bridge = complete_crosswalk.loc[
        complete_crosswalk.source_system.eq("stripe"),
        ["source_customer_id", "app_db_customer_id"],
    ]
    stripe_with_customer = stripe.merge(
        stripe_bridge, left_on="stripe_customer_id", right_on="source_customer_id"
    )
    check(
        stripe_with_customer.groupby("app_db_customer_id").size().le(2).all(),
        "a customer has more than one historical plus one active Stripe ID",
        failures,
    )
    for customer_id, group in stripe_with_customer.groupby("app_db_customer_id"):
        if len(group) != 2:
            continue
        historical = group.loc[~group.is_active, "created_at"]
        current = group.loc[group.is_active, "created_at"]
        check(
            len(historical) == 1
            and len(current) == 1
            and current.iloc[0] > historical.iloc[0],
            f"{customer_id}: recreated Stripe ID is not strictly later than one historical ID",
            failures,
        )

    recreated_group = next(
        group for _, group in stripe_with_customer.groupby("app_db_customer_id") if len(group) == 2
    )
    historical_row = recreated_group.loc[~recreated_group.is_active].iloc[0]
    current_row = recreated_group.loc[recreated_group.is_active].iloc[0]
    recreation_at = current_row.created_at
    before_recreation = visible_tables(first, recreation_at - pd.DateOffset(days=1))[
        "stripe__customers"
    ]
    before_pair = before_recreation.loc[
        before_recreation.stripe_customer_id.isin(
            [historical_row.stripe_customer_id, current_row.stripe_customer_id]
        )
    ]
    check(
        len(before_pair) == 1
        and before_pair.stripe_customer_id.eq(historical_row.stripe_customer_id).all()
        and before_pair.is_active.eq(True).all(),
        "Stripe snapshot before recreation does not expose exactly the old ID as active",
        failures,
    )
    check(
        "deactivated_at" in before_pair.columns
        and before_pair["deactivated_at"].isna().all(),
        "Stripe snapshot before recreation leaks the future deactivation timestamp",
        failures,
    )

    at_recreation = visible_tables(first, recreation_at)["stripe__customers"]
    at_pair = at_recreation.loc[
        at_recreation.stripe_customer_id.isin(
            [historical_row.stripe_customer_id, current_row.stripe_customer_id]
        )
    ]
    check(
        len(at_pair) == 2
        and at_pair.loc[
            at_pair.stripe_customer_id.eq(historical_row.stripe_customer_id), "is_active"
        ].eq(False).all()
        and at_pair.loc[
            at_pair.stripe_customer_id.eq(current_row.stripe_customer_id), "is_active"
        ].eq(True).all(),
        "Stripe snapshot at recreation does not expose the old ID inactive and new ID active",
        failures,
    )
    check(
        "deactivated_at" in at_pair.columns
        and at_pair.loc[
            at_pair.stripe_customer_id.eq(historical_row.stripe_customer_id),
            "deactivated_at",
        ].eq(recreation_at).all()
        and at_pair.loc[
            at_pair.stripe_customer_id.eq(current_row.stripe_customer_id),
            "deactivated_at",
        ].isna().all(),
        "Stripe deactivation timestamp is not applied exactly at recreation",
        failures,
    )

    final_crosswalk = first["app_db__customer_id_crosswalk"]
    qualified = ["source_system", "source_customer_id"]
    check(not complete_crosswalk.duplicated(qualified).any(), "complete mappings are not unique", failures)
    check(len(complete_crosswalk) == len(observed), "complete crosswalk does not map every source observation", failures)

    missing = observed.merge(final_crosswalk[qualified], on=qualified, how="left", indicator=True)
    missing = missing[missing._merge.eq("left_only")]
    cutoff = pd.Timestamp(config.IDENTITY_MIGRATION_DATE)
    check(len(missing) > 0, "planted migration gap has no missing mappings", failures)
    check(
        missing.source_system.isin(["shopify", "salesforce"]).all()
        and (missing.created_at < cutoff).all(),
        "missing mappings include ineligible source records",
        failures,
    )
    eligible = observed[
        observed.source_system.isin(["shopify", "salesforce"]) & (observed.created_at < cutoff)
    ]
    retained_eligible = eligible.merge(final_crosswalk[qualified], on=qualified, how="inner")
    check(len(retained_eligible) > 0, "all eligible mappings were dropped; none retained", failures)
    retained_migration_links = retained_eligible.merge(
        final_crosswalk[qualified + ["linked_at", "link_method"]], on=qualified
    )
    check(
        (retained_migration_links.linked_at == cutoff).all(),
        "retained pre-cutoff Shopify/Salesforce mappings do not arrive at migration cutoff",
        failures,
    )
    check(
        retained_migration_links.link_method.eq("2021_migration").all(),
        "retained migration mappings lack the 2021_migration link method",
        failures,
    )
    audited_links = final_crosswalk.merge(
        observed[qualified + ["created_at"]], on=qualified, how="left"
    )
    expected_method = pd.Series("direct_sync", index=audited_links.index)
    expected_method.loc[audited_links.source_system.eq("app_db")] = "primary_key"
    expected_method.loc[
        audited_links.source_system.isin(["shopify", "salesforce"])
        & (audited_links.created_at < cutoff)
    ] = "2021_migration"
    check(
        audited_links.link_method.equals(expected_method),
        "crosswalk link_method does not match primary-key/migration/direct-sync semantics",
        failures,
    )

    customer_keys = set(first["app_db__customers"].app_db_customer_id)
    check(set(orders_frame.customer_id) <= customer_keys, "order customer missing from app customers", failures)
    order_keys = set(orders_frame.order_id)
    for table in ("app_db__invoices", "app_db__revenue_recognition", "stripe__refunds"):
        check(set(first[table].order_id) <= order_keys, f"{table}: broken order_id relationship", failures)
    check(
        first["app_db__invoices"].salesforce_customer_id.notna().all()
        and set(first["app_db__invoices"].salesforce_customer_id) <= set(first["salesforce__customers"].salesforce_customer_id),
        "invoice native Salesforce IDs are incomplete or unobserved",
        failures,
    )
    salesforce_created_by_id = first["salesforce__customers"].set_index(
        "salesforce_customer_id"
    ).created_at
    check(
        (
            first["app_db__invoices"].salesforce_customer_id.map(salesforce_created_by_id)
            <= first["app_db__invoices"].billed_date
        ).all(),
        "invoice is visible before its native Salesforce customer",
        failures,
    )
    check(
        first["stripe__refunds"].stripe_customer_id.notna().all()
        and set(first["stripe__refunds"].stripe_customer_id) <= set(stripe.stripe_customer_id),
        "refund native Stripe IDs are incomplete or unobserved",
        failures,
    )
    stripe_created_by_id = stripe.set_index("stripe_customer_id").created_at
    check(
        (
            first["stripe__refunds"].stripe_customer_id.map(stripe_created_by_id)
            <= first["stripe__refunds"].refund_date
        ).all(),
        "refund is visible before its native Stripe customer",
        failures,
    )

    source_created = observed.set_index(qualified).created_at
    app_created = first["app_db__customers"].set_index("app_db_customer_id").created_at
    for row in final_crosswalk.itertuples(index=False):
        linked_at = pd.Timestamp(row.linked_at)
        check(linked_at >= source_created.loc[(row.source_system, row.source_customer_id)], "crosswalk arrives before source", failures)
        check(linked_at >= app_created.loc[row.app_db_customer_id], "crosswalk arrives before app customer", failures)
        if row.source_system == "app_db":
            check(
                linked_at == app_created.loc[row.app_db_customer_id],
                "app self-mapping does not arrive exactly with app customer",
                failures,
            )

    if failures:
        print("Identity generation check FAILED:")
        for failure in failures[:30]:
            print(f"  - {failure}")
        if len(failures) > 30:
            print(f"  ... {len(failures) - 30} more")
        return 1
    print("Identity generation check: deterministic aliases, migration gap, native IDs, and relationships hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())

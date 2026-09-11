"""
As-of visibility filter for the drip-feed pipeline.

The Parquet in data/raw is canonical and spans the full timeline (START_DATE..
END_DATE, which extends past "today"). A live warehouse must only see rows that
have "arrived" by a given as-of date. This module is the single definition of
that arrival rule, shared by every warehouse loader (BigQuery today, Redshift
later) so the drip stays warehouse-neutral.

Arrival rule: a row is visible when its own event date <= as_of. Future updates
on an otherwise-visible row are masked (the Fivetran-style late update):
  - an invoice's future collected_date is NULL;
  - a Stripe customer's future deactivated_at is NULL with is_active restored;
  - a subscription term still running at as_of is 'active' with no cancelled_at;
  - a plan retired after as_of is still current;
  - a shipment received after as_of is 'in_transit' with no received_date;
  - a ticket solved after as_of is 'open' with no resolved_at.
At the update timestamp, the final values become visible.

Parity property: for any period that lies fully <= as_of, the filtered tables
produce the same five revenues as generators/measures.py on the full Parquet.
"""
from __future__ import annotations

import pandas as pd

# Which column governs arrival for each raw table.
ARRIVAL_COLUMNS = {
    "app_db__customers": "created_at",
    "app_db__products": "introduced_at",
    "app_db__orders": "order_date",
    "app_db__order_lines": "created_at",
    "app_db__plans": "launched_at",
    "app_db__plan_prices": "effective_from",
    "app_db__subscriptions": "term_start",
    "app_db__invoices": "billed_date",
    "app_db__revenue_recognition": "recognition_date",
    "app_db__promotions": "start_date",
    "stripe__refunds": "refund_date",
    "erp__suppliers": "onboarded_at",
    "erp__supplier_shipments": "expected_date",
    "ads__daily_spend": "spend_date",
    "stripe__customers": "created_at",
    "shopify__customers": "created_at",
    "salesforce__customers": "created_at",
    "app_db__customer_id_crosswalk": "linked_at",
    "zendesk__tickets": "created_at",
}


def visible_tables(tables: dict[str, pd.DataFrame], as_of) -> dict[str, pd.DataFrame]:
    """Return copies of the raw tables containing only rows visible at as_of."""
    cutoff = pd.Timestamp(as_of)
    out: dict[str, pd.DataFrame] = {}
    for name, df in tables.items():
        col = ARRIVAL_COLUMNS[name]
        vis = df[df[col] <= cutoff].copy()
        if name == "app_db__invoices":
            vis.loc[vis["collected_date"] > cutoff, "collected_date"] = pd.NaT
        elif name == "stripe__customers":
            future_deactivation = vis["deactivated_at"] > cutoff
            vis.loc[future_deactivation, "deactivated_at"] = pd.NaT
            vis.loc[future_deactivation, "is_active"] = True
        elif name == "app_db__subscriptions":
            running = vis["term_end"] >= cutoff
            vis.loc[running, "status"] = "active"
            vis.loc[running, "cancelled_at"] = pd.NaT
        elif name == "app_db__plans":
            future_retirement = vis["retired_at"] > cutoff
            vis.loc[future_retirement, "retired_at"] = pd.NaT
            vis.loc[future_retirement, "is_current"] = True
        elif name == "erp__supplier_shipments":
            pending = vis["received_date"] > cutoff
            vis.loc[pending, "received_date"] = pd.NaT
            vis.loc[pending, "status"] = "in_transit"
        elif name == "zendesk__tickets":
            unresolved = vis["resolved_at"] > cutoff
            vis.loc[unresolved, "resolved_at"] = pd.NaT
            vis.loc[unresolved, "status"] = "open"
        out[name] = vis.reset_index(drop=True)
    return out

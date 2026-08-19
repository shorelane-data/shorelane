"""
Snowflake mirror (marts only; outside the canonical raw-table registry).

Snowflake is your product's home turf and the second warehouse for the
cross-tool / format-agnostic demo. You do NOT need the full stack here — mirror
only the final marts so Nodal can show consistent context + eval behavior across
two warehouses.

Two options:
  1. Run dbt with target=snowflake against the raw tables (also loaded here), OR
  2. Load the BigQuery-built fct_revenue straight across (simplest for a demo).

This stub uses option 2: read marts from local Parquet (export them from BQ first,
or materialize fct_revenue locally) and COPY into Snowflake.

    python -m loaders.snowflake_load --account ... --database SHORELANE

Requires: pip install snowflake-connector-python[pandas]
"""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--database", default="SHORELANE")
    ap.add_argument("--schema", default="MARTS")
    ap.add_argument("--marts-parquet", default="data/marts/fct_revenue.parquet")
    args = ap.parse_args()

    # Intentionally a stub: wire up snowflake.connector + write_pandas here once
    # you've exported fct_revenue. Kept minimal so Claude Code fills it in against
    # your actual Snowflake account/role (per your Nodal MCP setup).
    print(
        "Snowflake marts mirror not yet wired.\n"
        f"  target: {args.account}/{args.database}.{args.schema}\n"
        f"  source: {args.marts_parquet}\n"
        "TODO: snowflake.connector.connect(...) + write_pandas(fct_revenue, 'FCT_REVENUE')."
    )


if __name__ == "__main__":
    main()

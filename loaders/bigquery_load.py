"""
Load raw Parquet into BigQuery (primary warehouse).

Generate once (generators/emit.py), load many. This reads the same Parquet the
Snowflake loader reads, so the two warehouses stay byte-identical at the raw layer.

    python -m loaders.bigquery_load --project YOUR_GCP_PROJECT --dataset shorelane_raw

Requires: pip install google-cloud-bigquery; auth via `gcloud auth application-default login`.
Loads from local data/raw by default, or from GCS if config.GCS_BUCKET is set.

Drip-feed mode (the live pipeline): pass --as-of YYYY-MM-DD (or "today") to load
only rows visible at that date per loaders/visibility.py, replacing each table
with WRITE_TRUNCATE. Idempotent; backfill is just a normal run. Omit --as-of for
the full-fixture load.
"""
from __future__ import annotations

import argparse
import glob
import os
from datetime import date, datetime

import config
from generators.dataset import RAW_TABLES
from loaders.visibility import visible_tables


def _parse_as_of(value: str) -> date:
    if value == "today":
        return datetime.utcnow().date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="shorelane_raw")
    ap.add_argument("--location", default="US")
    ap.add_argument(
        "--as-of",
        default=None,
        help='Drip-feed cutoff: YYYY-MM-DD or "today". Omit for the full-fixture load.',
    )
    args = ap.parse_args()

    if not glob.glob(os.path.join(config.RAW_DIR, "*.parquet")):
        if args.as_of or not config.GCS_BUCKET:
            raise SystemExit("No Parquet found. Run: python -m generators.emit")

    from google.cloud import bigquery

    client = bigquery.Client(project=args.project, location=args.location)
    ds_ref = bigquery.Dataset(f"{args.project}.{args.dataset}")
    ds_ref.location = args.location
    client.create_dataset(ds_ref, exists_ok=True)

    if args.as_of:
        import pandas as pd

        as_of = _parse_as_of(args.as_of)
        tables = {
            t: pd.read_parquet(os.path.join(config.RAW_DIR, f"{t}.parquet"))
            for t in RAW_TABLES
        }
        for table, df in visible_tables(tables, as_of).items():
            job = client.load_table_from_dataframe(
                df,
                f"{args.project}.{args.dataset}.{table}",
                job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
            )
            job.result()
            print(f"loaded {len(df)} rows (as of {as_of}) -> {args.dataset}.{table}")
        return

    for table in RAW_TABLES:
        if config.GCS_BUCKET:
            uri = f"{config.GCS_BUCKET}/{config.DATASET_VERSION}/{table}.parquet"
            job = client.load_table_from_uri(
                uri,
                f"{args.project}.{args.dataset}.{table}",
                job_config=bigquery.LoadJobConfig(
                    source_format=bigquery.SourceFormat.PARQUET,
                    write_disposition="WRITE_TRUNCATE",
                ),
            )
            job.result()
            print(f"loaded {uri} -> {args.dataset}.{table}")
        else:
            path = os.path.join(config.RAW_DIR, f"{table}.parquet")
            with open(path, "rb") as f:
                job = client.load_table_from_file(
                    f,
                    f"{args.project}.{args.dataset}.{table}",
                    job_config=bigquery.LoadJobConfig(
                        source_format=bigquery.SourceFormat.PARQUET,
                        write_disposition="WRITE_TRUNCATE",
                    ),
                )
                job.result()
            print(f"loaded {path} -> {args.dataset}.{table}")


if __name__ == "__main__":
    main()

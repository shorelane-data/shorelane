"""
Load raw Parquet into Redshift Serverless (the AWS-side warehouse).

Generate once (generators/emit.py), load many -- the same Parquet BigQuery reads,
so the two warehouses stay byte-identical at the raw layer.

    python -m loaders.redshift_load --workgroup shorelane --bucket my-bucket
    python -m loaders.redshift_load --generate --as-of today   # no data/raw needed

Requires: pip install "shorelane[redshift]"; auth via the usual AWS chain
(AWS_PROFILE, instance role, or Lambda execution role).

Drip-feed mode (the live pipeline): pass --as-of YYYY-MM-DD (or "today") to load
only rows visible at that date per loaders/visibility.py. Idempotent; backfill is
just a normal run. Omit --as-of for the full-fixture load.

Two things differ from the BigQuery loader, both forced by Redshift:

  * BigQuery infers a schema from the Parquet footer and auto-creates the table.
    Redshift COPY requires the table to exist already, so the schema is an
    explicit artifact: shorelane-pipeline/sql/ddl_raw.sql.

  * There is no load_table_from_dataframe equivalent. Every path goes
    DataFrame -> Parquet on S3 -> COPY. S3 is therefore mandatory here, unlike
    GCS on the BigQuery side (config.GCS_BUCKET defaults to "" and is optional).

Everything runs through the Redshift Data API rather than a TCP connection: the
workgroup is private, so there is no endpoint to dial from outside the VPC. The
Data API reaches it service-side over HTTPS.
"""
from __future__ import annotations

import argparse
import io
import os
import time
from datetime import date, datetime, timezone

import config
from generators.dataset import RAW_TABLES
from loaders.visibility import visible_tables

RAW_SCHEMA = "shorelane_raw"

# Secret holding the fivetran_loader credentials. Loading as that user rather
# than as admin is the whole point: it is what makes this traffic identifiable
# as the loader in query history, mirroring sa-fivetran on GCP.
LOADER_SECRET = "shorelane/redshift/fivetran_loader"


def _parse_as_of(value: str) -> date:
    if value == "today":
        return datetime.now(timezone.utc).date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _s3_key(table: str) -> str:
    """Object layout mirrors the GCS convention: version-namespaced per table."""
    return f"{config.DATASET_VERSION}/{table}.parquet"


def _run_sql(data_api, *, workgroup: str, database: str, secret_arn: str, sql: str) -> None:
    """Execute one statement and block until it finishes.

    The Data API is asynchronous -- execute_statement returns an id immediately
    and the work happens server-side -- so every call needs this poll loop.
    """
    statement_id = data_api.execute_statement(
        WorkgroupName=workgroup,
        Database=database,
        SecretArn=secret_arn,
        Sql=sql,
    )["Id"]

    while True:
        desc = data_api.describe_statement(Id=statement_id)
        if desc["Status"] in ("FINISHED", "FAILED", "ABORTED"):
            break
        time.sleep(0.4)

    if desc["Status"] != "FINISHED":
        raise RuntimeError(f"{desc['Status']}: {desc.get('Error', 'no detail')}\nSQL: {sql[:200]}")


def _secret_arn(session, name: str) -> str:
    sm = session.client("secretsmanager")
    try:
        return sm.describe_secret(SecretId=name)["ARN"]
    except sm.exceptions.ResourceNotFoundException:
        raise SystemExit(
            f"Secret {name!r} not found. Run terraform apply, then "
            "infra/bootstrap_redshift.py in shorelane-pipeline."
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workgroup", default="shorelane")
    ap.add_argument("--database", default="shorelane")
    ap.add_argument("--schema", default=RAW_SCHEMA)
    ap.add_argument(
        "--bucket",
        default=os.environ.get("SHORELANE_S3_BUCKET"),
        help="S3 bucket for Parquet staging. Defaults to $SHORELANE_S3_BUCKET.",
    )
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument(
        "--copy-role-arn",
        default=os.environ.get("SHORELANE_COPY_ROLE_ARN"),
        help="IAM role Redshift assumes to read S3. Defaults to $SHORELANE_COPY_ROLE_ARN.",
    )
    ap.add_argument(
        "--as-of",
        default=None,
        help='Drip-feed cutoff: YYYY-MM-DD or "today". Omit for the full-fixture load.',
    )
    ap.add_argument(
        "--generate",
        action="store_true",
        help="Build the dataset in memory instead of reading data/raw. Required "
             "in Lambda, which has no data directory.",
    )
    args = ap.parse_args()

    if not args.bucket:
        raise SystemExit("--bucket is required (or set SHORELANE_S3_BUCKET)")
    if not args.copy_role_arn:
        raise SystemExit("--copy-role-arn is required (or set SHORELANE_COPY_ROLE_ARN)")

    import boto3
    import pandas as pd

    session = boto3.Session(region_name=args.region)
    s3 = session.client("s3")
    data_api = session.client("redshift-data")
    secret_arn = _secret_arn(session, LOADER_SECRET)

    as_of = _parse_as_of(args.as_of) if args.as_of else None

    if args.generate:
        # No filesystem to read from -- regenerate instead. This is what the
        # daily Lambda does, and it is exactly what the BigQuery pipeline's
        # load_daily.py does too. Safe because generation is deterministic:
        # config.SEED pins it, so the in-memory frames are byte-identical to
        # data/raw for the same DATASET_VERSION.
        from generators import dataset

        tables = dataset.generate()
    else:
        missing = [
            t for t in RAW_TABLES
            if not os.path.exists(os.path.join(config.RAW_DIR, f"{t}.parquet"))
        ]
        if missing:
            raise SystemExit(
                f"No Parquet for {missing}. Run `python -m generators.emit`, "
                "or pass --generate to build the dataset in memory."
            )

        tables = {
            t: pd.read_parquet(os.path.join(config.RAW_DIR, f"{t}.parquet"))
            for t in RAW_TABLES
        }

    if as_of:
        tables = visible_tables(tables, as_of)

    for table, df in tables.items():
        key = _s3_key(table)

        # Re-serialise rather than uploading data/raw/*.parquet verbatim. In
        # drip mode the frame has been filtered so the file on disk is wrong
        # anyway, and going through pyarrow lets us pin the string type below.
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow")
        buf.seek(0)
        s3.put_object(Bucket=args.bucket, Key=key, Body=buf.getvalue())

        qualified = f"{args.schema}.{table}"

        # TRUNCATE + COPY is the WRITE_TRUNCATE equivalent, and it is what makes
        # re-running safe -- the first run IS the backfill.
        #
        # Redshift commits TRUNCATE implicitly, so this is NOT atomic: between
        # the two statements the table is empty. That is acceptable here because
        # the only reader is a daily dbt build that runs an hour later, never
        # concurrently. If a reader ever shares this window, switch to COPY into
        # a staging table followed by ALTER TABLE ... RENAME.
        _run_sql(
            data_api,
            workgroup=args.workgroup,
            database=args.database,
            secret_arn=secret_arn,
            sql=f"TRUNCATE TABLE {qualified}",
        )
        _run_sql(
            data_api,
            workgroup=args.workgroup,
            database=args.database,
            secret_arn=secret_arn,
            sql=(
                f"COPY {qualified} FROM 's3://{args.bucket}/{key}' "
                f"IAM_ROLE '{args.copy_role_arn}' FORMAT AS PARQUET"
            ),
        )

        suffix = f" (as of {as_of})" if as_of else ""
        print(f"loaded {len(df):>7,} rows{suffix} -> {qualified}")


if __name__ == "__main__":
    main()

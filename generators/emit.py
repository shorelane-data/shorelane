"""
Generate -> write Parquet to data/raw -> (optional) upload to GCS.

GCS is the canonical artifact store ("generate once, load many"): the BigQuery and
Snowflake loaders read these Parquet files, so a second warehouse is nearly free.

Usage:
    python -m generators.emit
    python -m generators.emit --period   # also print the five revenues for TARGET_PERIOD
"""
from __future__ import annotations

import argparse
import os

import config
from generators import dataset
from generators.measures import five_revenues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", action="store_true", help="print five-revenues for TARGET_PERIOD")
    args = ap.parse_args()

    os.makedirs(config.RAW_DIR, exist_ok=True)
    tables = dataset.generate()

    for name, df in tables.items():
        path = os.path.join(config.RAW_DIR, f"{name}.parquet")
        df.to_parquet(path, index=False)
        print(f"wrote {path:<48} rows={len(df):>8,}")

    if config.GCS_BUCKET:
        try:
            import gcsfs  # noqa

            for name, df in tables.items():
                uri = f"{config.GCS_BUCKET}/{config.DATASET_VERSION}/{name}.parquet"
                df.to_parquet(uri, index=False)
                print(f"uploaded {uri}")
        except ImportError:
            print("gcsfs not installed; skipping GCS upload (pip install gcsfs)")

    if args.period:
        p = config.TARGET_PERIOD
        rev = five_revenues(tables, p["start"], p["end"])
        print(f"\nFive revenues for {p['label']} ({config.DATASET_VERSION}):")
        for k, v in rev.items():
            print(f"  {k:<20} ${v:>16,.2f}")


if __name__ == "__main__":
    main()

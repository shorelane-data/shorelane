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
    ap.add_argument("--ground-truth", default=None, metavar="PATH",
                    help="also render the derived revenue ground-truth doc for TARGET_PERIOD to PATH")
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

    if args.ground_truth:
        p = config.TARGET_PERIOD
        rev = five_revenues(tables, p["start"], p["end"])
        with open(args.ground_truth, "w") as fh:
            fh.write(render_revenue_ground_truth(rev, p))
        print(f"wrote {args.ground_truth}")


def render_revenue_ground_truth(rev: dict[str, float], period: dict[str, str]) -> str:
    """The derived ground-truth doc for the unqualified-revenue eval (never hand-edit)."""
    spread = max(rev.values()) - min(rev.values())
    gap = rev["recognized_revenue"] - rev["gmv"]
    return f"""# Ground truth — "What was our revenue in {period['label']}?"

Dataset: **{config.DATASET_VERSION}** (SEED={config.SEED}). These figures are **derived from the
generated data**, not hand-authored. Regenerate with the pinned seed and they
reproduce exactly. If they don't, something perturbed the RNG — treat it as a
breaking change and re-derive
(`python -m generators.emit --period --ground-truth context/ground_truth/revenue_q1_2024.md`).
Orders from non-`customer` accounts (`app_db__customers.account_type` in `test`,
`internal`) are excluded, matching `fct_revenue`.

## The five revenues, {period['label']} ({period['start']} .. {period['end']})

| Measure | Amount (USD) | Who uses it |
|---|---:|---|
| GMV | {rev['gmv']:,.2f} | Marketing / Exec |
| Net revenue | {rev['net_revenue']:,.2f} | Ops |
| **Recognized revenue** | **{rev['recognized_revenue']:,.2f}** | **Finance (canonical)** |
| Billed revenue | {rev['billed_revenue']:,.2f} | FP&A |
| Collected cash | {rev['collected_cash']:,.2f} | Treasury |

## Canonical answer

Unqualified "revenue" resolves to **recognized_revenue = ${rev['recognized_revenue']:,.2f}** (the
CFO's GAAP number), per `context/metrics/revenue.yml` and the personas guide.
A correct response states that assumption explicitly and ideally surfaces the
other four for comparison.

## Why this is a trap

- **Recognized > GMV.** Counterintuitive but correct: {period['label']} recognized revenue
  includes ratable recognition from subscriptions booked across the prior four
  quarters (Q4 is the B2B budget-flush season), while GMV only counts orders
  *placed* in {period['label']}. A naive agent that equates "revenue" with in-period
  sales will under-report by ~${gap / 1e3:,.0f}k and never notice.
- **Five plausible answers within ~${spread / 1e3:,.0f}k of each other.** Every one looks
  reasonable in isolation. Picking any without disambiguating is silent SQL.

## Acceptable vs failing responses

- **PASS** — returns recognized_revenue, names the assumption, ideally lists the
  other four. Or: asks which measure before answering.
- **SILENT FAIL (the target failure mode)** — returns exactly one of GMV /
  net_revenue / billed_revenue / collected_cash with confidence and no caveat.
- **HARD FAIL** — invents a sixth number, or sums measure rows across measure_name
  (double counting) to produce a meaningless total, or forgets the account-type
  exclusion and reports the unfiltered staging total.
"""


if __name__ == "__main__":
    main()

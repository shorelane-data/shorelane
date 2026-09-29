#!/usr/bin/env python3
"""Guard the benchmark question bank (evals/bank/).

Every gold in the bank has two independent derivations:

1. **Generators.** ``evals/build_bank.py`` derives it from the generated tables
   as the bench warehouse sees them. This check (the CI default) rebuilds the bank
   and fails if the committed ``dev.yaml`` differs, if any spec breaks a rule
   (window after the bench as_of, a trap whose wrong path equals the gold, an
   answer that changes when later rows arrive, ...), or if a holdout question
   slipped into this public repo.

2. **Gold SQL.** ``--sql`` runs each question's ``gold_sql`` against a warehouse
   and compares the result to the generator-derived gold:

       python tests/check_bench_golds.py --sql local --dbt ../shorelane-dbt
           # DuckDB replica of the pinned dbt build (no credentials)
       python tests/check_bench_golds.py --sql bigquery
           # the real nodal-shorelane.shorelane_bench_<v> (needs read access)

   The local run needs ``pip install -r evals/bank/requirements-sql.txt``; the BigQuery run needs
   ``google-cloud-bigquery`` and credentials (sa-bench-agent or any account the
   dataset is shared with).

Pass ``--bank`` to check another bank file (the private holdout) with ``--sql``.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import sys
import tempfile
from decimal import Decimal
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from evals import build_bank  # noqa: E402

TOLERANCE = build_bank.TOLERANCE


def _num(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "item"):
        return v.item()
    return v


def _decimals(v: Any) -> int:
    return len(repr(float(_num(v))).split(".")[1].rstrip("0"))


def _component_tol(gold_value: Any, sql_value: Any) -> float:
    """Components carry no unit, so precision sets the tolerance: integers are
    exact, cents allow half a cent, and finer ratios allow one unit in the last
    decimal place of the more precise side (half-up SQL vs half-even pandas)."""
    if isinstance(gold_value, int):
        return 0
    decimals = max(_decimals(gold_value), _decimals(sql_value))
    return TOLERANCE["usd"] if decimals <= 2 else 10.0 ** -decimals


def _close(a: Any, b: Any, tol: float) -> bool:
    a, b = _num(a), _num(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.fabs(a - b) <= tol + 1e-9
    return str(a) == str(b)


def compare(q: dict, columns: list[str], rows: list[tuple]) -> list[str]:
    """Differences between a gold_sql result and the derived gold ([] = agree)."""
    gold = q["gold"]
    cols = [c.lower() for c in columns]
    errs = []
    if gold["kind"] == "value":
        if len(rows) != 1 or "value" not in cols:
            return [f"expected one row with a `value` column, got {len(rows)} rows, columns {columns}"]
        row = dict(zip(cols, rows[0]))
        if not _close(row["value"], gold["value"], gold["tolerance"]):
            errs.append(f"value: sql {_num(row['value'])!r} != gold {gold['value']!r}")
        for name, want in (gold.get("components") or {}).items():
            if name.lower() not in row:
                errs.append(f"component {name} missing from gold_sql columns")
            elif not _close(row[name.lower()], want, _component_tol(want, row[name.lower()])):
                errs.append(f"{name}: sql {_num(row[name.lower()])!r} != gold {want!r}")
    elif gold["kind"] == "result_set":
        want_cols = [c.lower() for c in gold["columns"]]
        missing = [c for c in want_cols if c not in cols]
        if missing:
            return [f"result columns {columns} lack {missing}"]
        idx = [cols.index(c) for c in want_cols]
        got = sorted((tuple(_num(r[i]) for i in idx) for r in rows), key=lambda r: tuple(map(str, r)))
        want = sorted((tuple(r) for r in gold["rows"]), key=lambda r: tuple(map(str, r)))
        if len(got) != len(want):
            return [f"row count: sql {len(got)} != gold {len(want)}"]
        units = {c.lower(): u for c, u in gold["units"].items()}
        for g, w in zip(got, want):
            for col, a, b in zip(want_cols, g, w):
                tol = TOLERANCE[units[col]] if col in units else 0
                if not _close(a, b, tol):
                    errs.append(f"row {w}: {col} sql {a!r} != gold {b!r}")
    return errs


def check_sql(bank: dict, runner) -> int:
    failures = 0
    checked = 0
    for q in bank["questions"]:
        if not q.get("gold_sql"):
            continue
        checked += 1
        try:
            columns, rows = runner(q)
        except Exception as exc:  # report every failing question, not just the first
            print(f"FAIL {q['id']}: query error: {exc}")
            failures += 1
            continue
        errs = compare(q, columns, rows)
        if errs:
            failures += 1
            print(f"FAIL {q['id']}:", *errs, sep="\n    ")
    print(f"{checked - failures}/{checked} gold_sql results agree with the generator-derived golds")
    return 1 if failures else 0


def local_runner(bank: dict, dbt_repo: pathlib.Path, work: pathlib.Path | None):
    from evals.bank import local_warehouse

    work = work or pathlib.Path(tempfile.mkdtemp(prefix="shorelane-bench-local-"))
    print(f"building the local replica of {bank['warehouse']} in {work} ...")
    wh = local_warehouse.build(work, dbt_repo)
    return lambda q: wh.query(q["gold_sql"], bank["warehouse"])


def bigquery_runner(bank: dict, max_bytes: int):
    from google.cloud import bigquery

    project = bank["warehouse"].split(".")[0]
    client = bigquery.Client(project=project)

    def run(q: dict):
        cfg = bigquery.QueryJobConfig(
            maximum_bytes_billed=max_bytes,
            labels={"purpose": "bench_gold_check", "question_id": q["id"][:63]},
        )
        result = client.query(q["gold_sql"], job_config=cfg).result(timeout=120)
        return [f.name for f in result.schema], [tuple(r.values()) for r in result]

    return run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sql", choices=("local", "bigquery"), help="also run every gold_sql and compare")
    ap.add_argument("--bank", type=pathlib.Path, default=REPO_ROOT / "evals" / "bank" / "dev.yaml")
    ap.add_argument("--dbt", type=pathlib.Path, default=REPO_ROOT.parent / "shorelane-dbt",
                    help="local clone of shorelane-dbt holding the pinned commit (--sql local)")
    ap.add_argument("--work", type=pathlib.Path, help="directory for the local replica (default: a temp dir)")
    ap.add_argument("--max-bytes", type=int, default=2 * 1024**3, help="per-query cap for --sql bigquery")
    args = ap.parse_args(argv)

    if args.sql is None:
        # Public bank only: rebuild from the specs and require an exact match.
        return build_bank.main(["--check"])

    bank = yaml.safe_load(args.bank.read_text())
    runner = (local_runner(bank, args.dbt, args.work) if args.sql == "local"
              else bigquery_runner(bank, args.max_bytes))
    return check_sql(bank, runner)


if __name__ == "__main__":
    sys.exit(main())

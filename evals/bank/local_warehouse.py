"""A local DuckDB replica of the benchmark warehouse, for checking gold SQL offline.

The bench dataset (``shorelane_bench_<v>``) is the pinned shorelane-dbt commit
built over the raw snapshot at the bench ``as_of``. This module rebuilds the same
thing on a laptop, with no cloud credentials:

1. generate the raw tables and apply the arrival rule at the bench ``as_of``
   (exactly what the frozen ``bench-load`` wrote to BigQuery);
2. export the dbt project at the commit pinned in ``bench/modes.yaml``
   (``git archive``, so local edits in the dbt clone cannot leak in);
3. ``dbt build`` it with the DuckDB adapter (models, seeds and data tests);
4. run BigQuery SQL against it through sqlglot's BigQuery-to-DuckDB transpiler.

The dbt models are ANSI SQL plus the ``money()`` macro, whose non-BigQuery branch
is ``decimal(38,9)`` (exactly BigQuery's NUMERIC), so the replica agrees with the
warehouse to the cent. It is a stand-in for the live check, not a replacement:
``tests/check_bench_golds.py --sql bigquery`` runs the same SQL against the real
dataset.

Needs ``pip install -r evals/bank/requirements-sql.txt``.
"""
from __future__ import annotations

import io
import pathlib
import subprocess
import tarfile
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW_SCHEMA = "shorelane_raw"


def _pinned(modes_path: pathlib.Path) -> tuple[str, str, str]:
    modes = yaml.safe_load(modes_path.read_text())
    wh = modes["warehouse"]
    return modes["sources"]["dbt"]["commit"], str(wh["as_of"]), wh["dataset"]


def export_dbt(dbt_repo: pathlib.Path, commit: str, dest: pathlib.Path) -> None:
    archive = subprocess.run(["git", "-C", str(dbt_repo), "archive", "--format=tar", commit],
                             check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:  # Python without extraction filters; our own pinned archive
            tar.extractall(dest)


def load_raw(db_path: pathlib.Path, as_of: str) -> None:
    import duckdb

    from generators import dataset
    from loaders.visibility import visible_tables

    tables = visible_tables(dataset.generate(), as_of)
    con = duckdb.connect(str(db_path))
    con.execute(f"create schema if not exists {RAW_SCHEMA}")
    for name, df in tables.items():
        con.register("df", df)
        con.execute(f"create or replace table {RAW_SCHEMA}.{name} as select * from df")
        con.unregister("df")
    con.close()


def build(work: pathlib.Path, dbt_repo: pathlib.Path, modes_path: pathlib.Path | None = None) -> "LocalWarehouse":
    """Build the replica under `work` and return a handle to query it."""
    commit, as_of, dataset_name = _pinned(modes_path or REPO_ROOT / "bench" / "modes.yaml")
    work = work.resolve()  # dbt runs from inside the exported project
    work.mkdir(parents=True, exist_ok=True)
    project = work / "dbt"
    db = work / "bench.duckdb"
    if db.exists():
        db.unlink()
    export_dbt(dbt_repo, commit, project)
    load_raw(db, as_of)
    (work / "profiles.yml").write_text(yaml.safe_dump({
        "shorelane": {"target": "local", "outputs": {"local": {
            "type": "duckdb", "path": str(db), "schema": dataset_name, "threads": 4}}}
    }))
    # A target other than `bench` reading a raw schema not named like a bench
    # snapshot satisfies assert_raw_dataset_matches_target.
    subprocess.run(
        ["dbt", "build", "--profiles-dir", str(work), "--target-path", str(work / "target"),
         "--log-path", str(work / "logs"), "--vars", yaml.safe_dump({"raw_dataset": RAW_SCHEMA})],
        cwd=project, check=True, stdout=subprocess.DEVNULL,
    )
    return LocalWarehouse(db, dataset_name, commit)


class LocalWarehouse:
    def __init__(self, db: pathlib.Path, dataset_name: str, dbt_commit: str):
        import duckdb

        self.con = duckdb.connect(str(db), read_only=True)
        self.dataset = dataset_name
        self.dbt_commit = dbt_commit

    def query(self, sql: str, project_dataset: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        """Run BigQuery SQL that addresses `project.dataset.table`."""
        import sqlglot

        sql = sql.replace(f"`{project_dataset}.", f"`{self.dataset}.")
        duck = sqlglot.transpile(sql, read="bigquery", write="duckdb")[0]
        cur = self.con.execute(duck)
        return [d[0] for d in cur.description], cur.fetchall()

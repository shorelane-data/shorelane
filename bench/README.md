# bench/ — the analytics-agent benchmark's context modes

The benchmark measures what context adds to an analytics agent. Every run
queries the **same frozen BigQuery dataset** (`nodal-shorelane.shorelane_bench_<v>`)
with the same prompt and the same SQL tool. Only the agent's working directory
changes between modes:

| Mode | Working directory | Measures |
|---|---|---|
| `none` | empty | the bare agent on tables and column names |
| `dbt` | `dbt/`: the dbt project (models, YAML docs, macros, seeds, data tests) | `dbt − none`: the lift from the modeled, documented project |
| `dbt_context` | `dbt/` + `context/`: the analytics-context layer (ACF) | `dbt_context − dbt`: the lift from the context layer |

dbt owns its documentation: whatever the dbt YAML says counts as part of the `dbt`
mode. The warehouse carries no descriptions of its own (shorelane-dbt never
enables `persist_docs`), so `none` really is schema only.

## What guarantees the modes are honest

- **Pinned sources.** `modes.yaml` pins shorelane-dbt and
  shorelane-analytics-context to commits, and files are read from the git object
  store at those commits. The dbt pin must equal
  `shorelane_bench_<v>._bench_build.dbt_commit`: the project the agent reads is the
  one that built the tables it queries.
- **Nesting.** `check` builds all three modes and fails unless `dbt` contains
  `none` unchanged plus only `dbt/`, and `dbt_context` contains `dbt` unchanged
  plus only `context/`.
- **Leakage scan** (`leakage.py`): every build fails if a workspace contains
  - a file an agent loads on its own (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`,
    `.cursorrules`, `.claude/`, and so on). Context must be *read*, the same way by
    every entry, not injected into some of them. The ACF answering procedure ships
    as `AGENTS.md` and is mounted as `context/README.md` for that reason;
  - evaluation material by path: ground truth, eval banks and seeds, benchmark
    runs, the parity checks, `measures.py`;
  - any graded number: currency to the cent and counts of 1,000 or more, collected
    from `evals/` and `context/ground_truth/`.
- **Manifest.** Each build writes a manifest *outside* the workspace, holding
  source commits, per-file hashes and one workspace hash. A result is only
  reported next to the manifest it ran with.

## Commands

```bash
# all three modes: build, scan, nesting check (dev: unpinned sources allowed)
make bench-check DBT=../shorelane-dbt CONTEXT=../shorelane-analytics-context

# one workspace for a run
python -m bench.workspace build --mode dbt_context --out /tmp/ws \
    --dbt ../shorelane-dbt --context ../shorelane-analytics-context \
    --manifest /tmp/ws.manifest.json

python tests/check_bench_modes.py   # credential-free unit checks (CI)
```

## Standing up a bench version

1. `BENCH_VERSION=v1 infra/setup_bench.sh` in shorelane-pipeline creates the
   datasets, `sa-bench-agent`, and the grants.
2. Dispatch shorelane-pipeline `bench-load` with `bench_version=v1` and a fixed
   past `as_of`. This loads the frozen raw snapshot.
3. Dispatch shorelane-dbt `bench-build` with `bench_version=v1`. This builds and
   tests the dataset, runs parity, and stamps `_bench_build`.
4. Copy `_bench_build.dbt_commit` into `sources.dbt.commit` and `raw_as_of` into
   `warehouse.as_of` here, then run `make bench-check` without
   `--allow-unpinned`.

## Not solved here

Any Google identity can read the live `shorelane` dataset, because it is public.
IAM alone therefore cannot stop an agent from querying the moving warehouse
instead of the frozen one. The runner's SQL tool must allow only
`shorelane_bench_<v>`.

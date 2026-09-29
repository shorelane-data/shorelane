# evals/bank/ — the benchmark question bank

The canonical question bank of the Shorelane analytics-agent benchmark (see
`bench/README.md`). One format for every question, whatever it came from, with
every graded number derived from the generators.

| File | What it is | Written by |
|---|---|---|
| `specs/*.yaml` | the authored questions, one file per domain, **no numbers** | people |
| `derive.py` | the gold derivations the specs name (generic, parameterized) | people |
| `dev.yaml` | the dev split with golds, silent-fail values and evidence filled in | `evals/build_bank.py` |
| `local_warehouse.py` | DuckDB replica of the bench warehouse for checking `gold_sql` offline | people |

```
python evals/build_bank.py                                  # re-derive dev.yaml
python tests/check_bench_golds.py                           # CI: dev.yaml current and valid
python tests/check_bench_golds.py --sql local --dbt ../shorelane-dbt   # gold_sql on a local replica
python tests/check_bench_golds.py --sql bigquery            # gold_sql on shorelane_bench_<v>
```

## Two derivations of every gold

1. **Generators** (`build_bank.py`). The spec names a function in `derive.py`; it
   runs over the generated tables *as the bench warehouse sees them*: the arrival
   rule (`loaders/visibility.py`) applied at the bench `as_of` from
   `bench/modes.yaml`. The same gold is also derived from the full tables, and
   a question whose answer changes when later rows arrive is rejected: it would
   be reading the future.
2. **Gold SQL** (`check_bench_golds.py --sql`). Each value or result-set question
   carries the BigQuery SQL an analyst would write against the dbt marts. It runs
   against either a DuckDB replica (the pinned shorelane-dbt commit, `dbt build`
   over the same as-of snapshot, SQL transpiled by sqlglot) or the real
   `nodal-shorelane.shorelane_bench_<v>`, and must agree with (1) to the cent.

Disagreement between the two means one of them encodes the wrong rule. That is
the point of having both.

## Fields

Authored in a spec (the domain comes from the spec file):

| Field | Meaning |
|---|---|
| `id` | snake_case, unique across splits, stable forever (results are keyed on it) |
| `tier` | `descriptive` (a number or table), `diagnostic` (why did X move), `unanswerable` |
| `trap_tag` | the one silent-SQL failure the question is built around (below) |
| `prompt` | exactly what the agent receives, after the mode-independent preamble |
| `persona` | who is asking (metadata only; anything the agent needs is in `prompt`) |
| `pinned_scope` | `window: {start, end}` or `at: <date>`, inclusive, both on or before the bench `as_of`; `question_as_of` when the prompt names its own as-of |
| `gold.kind` | `value`, `result_set`, `criteria` (diagnostic, judged) or `refusal` |
| `gold.derive` | `{fn: <derive.py function>, params: {...}}`; the window and `at` are passed in automatically |
| `gold.unit` / `gold.units` | `usd`, `count` or `ratio`, for a value or each result-set measure column |
| `gold.must` / `must_not` | the judge's criteria (diagnostics) |
| `gold.reason` / `absent_terms` | why the question is unanswerable; terms that must not appear in any raw column or table name |
| `gold_sql` | BigQuery SQL against the marts, tables written as `` `{bench}.<table>` ``; a value query returns a `value` column plus one column per component |
| `trap` | the plausible-wrong path, in words (required unless `trap_tag: none`) |
| `context_required` | the human-confirmed artifacts that resolve the trap: `shorelane:` (this repo's `context/`), `acf:` (shorelane-analytics-context), `dbt:` (the dbt project) |
| `split` | `dev` here; `holdout` only in shorelane-bench |
| `provenance.source` | where the question came from; `context_seed` names the analytics-context seed it overlaps, if any |

Added by the build: `pinned_scope.as_of` (the snapshot), the gold's numbers and
`tolerance`, `silent_fail_values` (what each wrong path returns on the bench
warehouse), and `evidence` for diagnostics.

### Trap tags

| Tag | The failure | Example |
|---|---|---|
| `none` | control: a careful reading of the schema is enough | "What was GMV for full-year 2025?" |
| `ambiguous_definition` | several columns fit the words; context picks one | "revenue" across five measures |
| `definition_outside_schema` | the rule is a business decision nothing in the schema encodes | active subscriber, renewal rate, test accounts |
| `as_of_temporal` | "last quarter", "this year", status as of a past date | `status = 'open'` answers "now", not June 30 |
| `fanout_cardinality` | a join multiplies rows, or a count lands at the wrong grain | identity aliases, per-platform day totals |
| `unanswerable` | the data cannot answer; the right response says so | NPS, gift cards, after the as_of |

A trapped question must derive at least one silent-fail value, and the build
fails if any wrong path returns the gold: a trap that does not bite is noise.

## Splits and the holdout

This repo is public, so everything in it is **dev**: the migrated questions were
already public, and ground truth here is web-discoverable. The **holdout** (60%
of the published bank) lives in the private `shorelane-bench` repo until
publication, as specs in the same format, reusing `derive.py` (so the derivation
logic stays public and single-sourced while the questions stay private):

```
python evals/build_bank.py --specs ../shorelane-bench/bank/specs --split holdout \
    --out ../shorelane-bench/bank/holdout.yaml
```

The builder refuses to write a holdout bank inside this repo, and every spec here
must say `split: dev`. Context authors work from dev only: nobody editing
shorelane-analytics-context reads the holdout.

## Where the first 44 came from

| Source | Questions |
|---|---|
| `evals/questions.yaml` | all 6 (revenue personas, identity) |
| `evals/demo/cases.yaml` | 3 representatives (the 92 are one template over months; the rest stay a drift-demo corpus) |
| `bi/ad-hoc/*.sql` | 01, 02, 03, 05, 06, 07, 09 (04, 10, 11, 12 overlap questions already here) |
| `context/ground_truth/*_dashboard.md`, `events.md` | subscriptions, customers, marketing KPIs; all 5 seeded events as diagnostics |
| analytics-context seeds | 22 questions overlap 19 of the 23 seeds (recorded as `context_seed`) |
| authored | operations as-of questions, the unanswerables, the paper-order fanout |

Questions that overlap an analytics-context seed are the ones the context was
written against. Report lift on them separately from the rest.

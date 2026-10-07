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
| `qa_record.py` | the record format and its verifier: standalone, copy it into other repos | people |
| `seed_overlap.py` | checks `provenance.context_seeds` against the analytics-context seeds | people |
| `export_seeds.py` | one-way export of the bank as ACF eval seeds | people |

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
| `intent` | what the asker means, in words: the definition the gold measures. Metadata for reviewers, the judge and the seed export; never shown to the agent |
| `status` | `confirmed` once a person has checked the intent and gold against the business definition; `draft` until then |
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
| `provenance.source` | where the question came from |
| `provenance.context_seeds` | the analytics-context eval seeds the question overlaps (below); `[]` once checked and none applies. Required |

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

Split policy v2 (`independent-authoring-v2`) follows development exposure, not
an ID hash. Questions developed alongside context, published, or used to tune
context are dev. Independently authored questions and golds reserved from context
development are holdout. IDs stay unchanged when correcting historical labels.

Each bank has a versioned `splits.yaml` beside `specs/`, containing an explicit
assignment and reason for every question. The builder requires it and rejects
missing IDs or disagreement. Private holdout IDs stay in the private manifest.
Unknown IDs require an explicit assignment; there is no automatic fallback.

```
python evals/build_bank.py --which-split rev_q3_2025_gmv
```

Earlier banks used a hash partition. Preserve historical runs and their bank
snapshots; bank version 2 records this new policy, so their scores are not silently
reinterpreted. A holdout exposed to context development must be retired from the
untouched evaluation collection.

This repo is public, so it holds **dev** only. The **holdout** lives in the private
`shorelane-bench` repo until publication, as specs in the same format, reusing
`derive.py` (so the derivation logic stays public and single-sourced while the
questions stay private):

```
python evals/build_bank.py --specs ../shorelane-bench/bank/specs --split holdout \
    --out ../shorelane-bench/bank/holdout.yaml
```

The builder refuses to write a holdout bank inside this repo. Context authors work
from dev only: nobody editing shorelane-analytics-context reads the holdout.

## Where the first 44 came from

| Source | Questions |
|---|---|
| `evals/questions.yaml` | all 6 (revenue personas, identity) |
| `evals/demo/cases.yaml` | 3 representatives (the 92 are one template over months; the rest stay a drift-demo corpus) |
| `bi/ad-hoc/*.sql` | 01, 02, 03, 05, 06, 07, 09 (04, 10, 11, 12 overlap questions already here) |
| `context/ground_truth/*_dashboard.md`, `events.md` | subscriptions, customers, marketing KPIs; all 5 seeded events as diagnostics |
| analytics-context seeds | many questions share a definition with a seed: see the overlap section below |
| authored | operations as-of questions, the unanswerables, the paper-order fanout |

## Overlap with the analytics-context seeds

The analytics-context interview emits eval seeds (`evals/seeds/*.seed.yaml`), one
per confirmed disambiguation. A question **overlaps** a seed when the seed's intent
(or `must_include`) settles the definition the question's gold rests on: the context
author had that exact decision in front of them. Lift on overlapping questions is not
independent of how the context was written, so report it separately from the rest.

Overlaps are judged by hand and recorded in `provenance.context_seeds`, most direct
first. `evals/bank/seed_overlap.py` keeps the record honest against the pinned context
(`bench/modes.yaml` → `sources.context.commit`): it fails on a seed name the context
does not have or a question with no record, reports coverage, and with `--suggest`
shortlists similar seeds per question for the reviewer (a shortlist, never a verdict).

```
make bank-seeds CONTEXT=../shorelane-analytics-context        # this repo's dev bank
python evals/bank/seed_overlap.py --context ../shorelane-analytics-context \
    --specs ../shorelane-bench/bank/specs --suggest            # holdout specs
```

Re-check whenever the context pin moves: a new interview adds seeds. At context
6298880 (63 seeds), 36 of the 44 dev questions overlap at least one seed and 53 seeds
are named. The 8 independent dev questions are the March 2023 consumer-orders
diagnostic, 2025 ad spend by platform, 2025 GMV of paper orders, the three operations
as-of questions, revenue for September 2026 (after the as_of) and the BTB15 email
open rate. Holdout questions are checked the same way before they count as independent.

## Exporting as ACF eval seeds

The bank and the analytics-context seeds are separate formats with separate jobs: a
seed records what one interview confirmed, while a bank question carries a derived gold,
a second derivation (`gold_sql`) and a trap. `evals/bank/export_seeds.py` converts
the bank into seeds, one way only, so nodal-context's `eval_harness` can grade a
bank question the way it grades a context's own seeds. The harness has a model write
SQL for the question and an LLM judge it against `expected`:

```
make bank-export OUT=/tmp/bank-seeds                          # descriptive questions, as sql_shape
python evals/bank/export_seeds.py --out /tmp/bank-seeds \
    --tiers descriptive,diagnostic,unanswerable --values \
    --schema ../nodal-context/schemas/evalseed.schema.json    # every tier, value golds as values
cd ../nodal-context && python -m eval_harness.run --adapter acf \
    --root ../shorelane-analytics-context --seeds /tmp/bank-seeds
```

The harness grades `confirmed` seeds by default. At the pinned context every one of
its own seeds is still `draft`, so a run like this grades the bank's seeds only.

| bank | seed |
|---|---|
| `prompt` / `intent` / `status` | `question` / `intent` / `status` |
| `domain` | the context domain: revenue → `executive-revenue`; customers, marketing, subscriptions unchanged; diagnostics and unanswerable mapped per question by topic; operations has no context domain and is skipped |
| `provenance.source` | `dashboard` for a dashboard source, else `generated` |
| value / result_set gold | `sql_shape`: `must_include` the intent, `must_exclude` the trap's wrong paths. With `--values`, a value gold becomes `value_at_snapshot` (`value`, `as_of` = the bench as_of), which the harness skips without a warehouse |
| criteria gold (diagnostic) | `sql_shape`: `must_include` = `must`, `must_exclude` = `must_not` |
| refusal gold | `sql_shape`: `must_include` "says the data cannot answer", `must_exclude` the trap |

What the harness grades is narrower than what the bench grades. It judges the shape
of one SQL query, without running it, so a seed passes on the right definition even
when the number would be wrong, and diagnostic criteria or refusals fit a SQL query
only loosely. That is why only descriptive questions are exported by default. Use the
harness to compare contexts on definitions; the bench, which runs agents against the
warehouse and scores their numbers, stays the measure of correctness.

The export carries graded answers, and with `--values` the graded numbers too. It
refuses to write under any directory holding a `context.config.yaml`, because seeds
committed to the analytics-context repo would leak into the benchmark workspaces.
Never export the holdout bank anywhere public.

## Authoring questions in another repo

`evals/bank/qa_record.py` is the single definition of a bank record (one spec):
every field, the allowed values, the tier/trap/gold rules and the hash split rule.
`build_bank.py` validates every spec through it, so a record that passes
`qa_record.py` passes the bank's format rules here. It needs only Python 3.10+ and
PyYAML, so it can be copied as is into a repo where questions are drafted:

```
python qa_record.py check records/                            # verify record files
python qa_record.py check records/ --derive-fns ../shorelane/evals/bank/derive.py
python qa_record.py which-split <id> --split-manifest splits.yaml   # dev or holdout, from the manifest
python qa_record.py export records/ --out ../shorelane/evals/bank/specs --split dev
python qa_record.py export records/ --out ../shorelane-bench/bank/specs --split holdout
```

A record file holds one record, a list, or a spec file. A record outside a spec file
names its own `domain`. `export` appends records to `<domain>.yaml` in the target
specs directory, leaving existing records and comments untouched. It refuses an id
that is already there, and it validates the new records together with the ones in
place. A copy is current when its `RECORD_FORMAT` matches this one, which changes
whenever a rule does.

The format is not the whole check. After a record lands, `make bank` runs its
derivation (an unknown `derive.fn` needs a new function in `derive.py` first),
rejects a gold that reads past the as_of or a trap whose silent-fail value equals
the gold, and `tests/check_bench_golds.py --sql` reproduces the gold with `gold_sql`.
Export dev records only to this repo, and holdout records only to shorelane-bench:
the explicit split manifest decides which split a record belongs to.


# CLAUDE.md — Shorelane Commerce

> Read this first. It is the design contract for this repo. Follow it when extending
> the project; the guardrails exist to keep the dataset trustworthy as an eval fixture.

## What this is

**Shorelane Commerce** is a synthetic B2B2C office-supplies business, built as an
**evaluation fixture for analytics agents**. It is not a fake-data toy. It is a
controlled environment for measuring **silent SQL** — confidently wrong,
plausible-looking answers from AI-generated queries.

Inspired by Hex's "Shorelane Commerce" eval lab, but built for a different purpose:
here the point is to demonstrate that **human-confirmed context defuses traps that
auto-generated context and raw model capability do not.** The data is a means; the
context layer and the eval traps are the product.

Profile: B2B2C office supplies, founded 2019, three revenue streams (direct-to-
consumer, net-30 business subscriptions, and a 15–25%-take marketplace), with six
years of accumulated data debt.

## The one idea that governs everything: the eval triple

Every piece of intentional mess in this repo ships as a **triple**. If you add mess
without all three legs, you are adding noise, not an eval. Do not do that.

1. **Ground truth** — the correct answer, *derived from the generated data* (never
   hand-waved), living in `context/ground_truth/`.
2. **The plausible-wrong path** — the specific silent-SQL failure the mess invites,
   documented in the eval's `trap:` field. There must be a believable wrong answer.
3. **The context artifact** — the human-confirmed metric def / semantic model /
   guide in `context/` that resolves the ambiguity. This is the Nodal surface.

The currently-built slice (the **five revenues**) is the worked example of the
triple. Copy its shape when you add the next piece of debt.

## Non-negotiable invariants

- **Determinism.** All randomness derives from `config.SEED` via
  `generators/common.make_rng(stream=N)` (registry in that module's docstring).
  **Every new generator must use a NEW `stream` int** so it cannot perturb existing output. If output for an existing
  table changes, you have silently invalidated ground truth.
- **Ground truth is derived, not authored.** Numbers in `context/ground_truth/`
  come from running the generators + `generators/measures.py`. Never type a figure
  by hand. Re-derive after any change and update the file in the same commit.
- **Breaking changes bump the version.** Changing `SEED`, any economic constant in
  `config.py`, or a measure definition changes the planted trap. Bump
  `DATASET_VERSION` and re-derive all ground truth.
- **dbt must match the reference.** `dbt/models/marts/fct_revenue.sql` must agree
  with `generators/measures.py` for any period. That parity is the contract between
  the warehouse and the eval. If you change one, change the other and confirm.
- **Generate once, load many.** Generators write Parquet to `data/raw` (and
  optionally GCS). Loaders read that Parquet. Never let a loader or warehouse
  become a second source of generation logic.

## Architecture / data flow

```
generators/ (seeded Python)
      │  emit Parquet — or regenerate in memory (--generate), which is
      │  equivalent because config.SEED pins it
      ▼
  data/raw/*.parquet ──►  GCS (optional)        S3 (REQUIRED for Redshift)
      │                    │                      │
      │ loaders/           │ loaders/             │ COPY ... FORMAT AS PARQUET
      │ bigquery_load.py   │ bigquery_load.py     ▼
      ▼                    ▼                   Redshift Serverless (SECOND)
  BigQuery (PRIMARY) ◄─────┘                      │
      │                                           │
      │        dbt: staging → marts (ONE model set, both targets)
      ▼                                           ▼
  fct_revenue  ◄── must match generators/measures.py ──►  fct_revenue
      │                                           │
      │   parity/check_parity.py          parity/check_parity_redshift.py
      │
      ├── context/  (metrics, LookML, guides, ground_truth)  ← the Nodal layer
      ├── evals/    (questions + rubrics)
      └── bi/       (Looker Studio = free/BQ-native; Plotly = fully free)
```

### Warehouse policy
- **BigQuery is primary** (cheap on GCS credits; free tier covers this scale).
- **Redshift Serverless is a full second warehouse**, not a mirror. It runs the
  same generators, the same dbt models and the same parity contract, so the
  fixture is demonstrably not BigQuery-shaped — and so an AWS-native prospect
  sees it on the warehouse they actually run. See `shorelane-pipeline/terraform/`.
- **Snowflake remains a stub.** Redshift now carries the cross-tool claim.
- Keep generation warehouse-neutral (Parquet, or in-memory via `--generate`).
- **dbt is dual-warehouse via one model set.** The models are plain ANSI SQL; the
  only dialect difference is the `money()` macro. There is no portable spelling
  for a fixed-precision decimal cast, and the two failure modes are opposites:

  | | bare `numeric` | `decimal(38,9)` |
  |---|---|---|
  | BigQuery | ✅ *is* decimal(38,9) | ❌ hard error — parameterized types are not allowed in CAST |
  | Redshift | ⚠️ decimal(18,0) — **silently truncates every cent** | ✅ correct |

  Always use `{{ money('col') }}`. Never write a bare `cast(... as numeric)`.

### Parity is per-warehouse
`parity/check_parity.py` and `parity/check_parity_redshift.py` both compare
`fct_revenue` against `measures.py`, and both run weekly. They are separate
because the warehouses can drift **independently** — the decimal trap above
would break Redshift while BigQuery stayed green. A pass on one says nothing
about the other.

`shorelane/tests/check_ground_truth.py` covers the gap neither parity job can:
both compare the warehouse to `measures.py`, so a change that perturbs the RNG
moves them together and parity still passes while every committed figure
silently goes wrong.

### BI policy — read this to avoid a $60k mistake
- **Looker (core)** is a $60k+/yr enterprise platform. We do **not** run an instance.
- We author **LookML as a context artifact** (`context/semantic/*.lkml`) — it's a
  semantic layer, exactly what Nodal reads/evaluates — without paying for Looker.
- Render dashboards with **Looker Studio** (free, BigQuery-native) or **Plotly**
  (fully free). Never assume GCP credits make Looker-core free; they don't.

## Current state (built)

**shorelane-v4** (2026-09) — the business-dynamics release. Nineteen raw tables,
all seeded, all documented in `raw_schema/`:

- **Five revenues** (the signature trap): orders/invoices/recognition/refunds
  with the planted divergence; `generators/measures.py` is the reference,
  `fct_revenue` the warehouse expression. `make verify` prints Q1 2024 and
  `recognized_revenue > gmv` holds there because Q4 is the B2B booking season.
- **Business dynamics** (`generators/timeline.py`): 14% compounding growth, monthly
  seasonality per channel, and `config.EVENTS` — five seeded events, each with a
  known cause in a named table, so diagnostic questions have derivable answers:
  a paper-supplier outage (2023-03), a Back-to-Business promo (2024-09), a gen-3
  price increase (2025-05), an enterprise churn wave after a billing incident
  (2022-Q4), and a paid-media cut (2026-02). Ground truth:
  `context/ground_truth/events.md` via `generators/event_measures.py`.
- **Customer lifecycle** (`generators/customers.py`): order-first assignment with a
  recency pool, so cohorts, retention, and new-vs-returning are real series.
- **Product catalog + supply** (`generators/catalog.py`): 128 SKUs in six categories
  with `unit_cost` (the margin substrate for prescriptive questions), one supplier
  per category, weekly shipments.
- **Subscriptions** (`generators/subscriptions.py`): per-term rows, renewals with a
  churn hazard, three grandfathered plan generations with price history.
- **Marketing** (`generators/marketing.py`): promotions and daily ad spend with
  inflated self-reported conversions. **Support** (`generators/support.py`):
  Zendesk tickets keyed by source-native ids.
- **Identity fragmentation** (`generators/identity.py`): unchanged from v3 —
  2–4 aliases per customer, the 2021 crosswalk gap, Stripe account recreation.
- Debt items built as definitional traps: **channel rename** (`direct` before
  2022-06-01), **test/internal accounts** (excluded by `fct_revenue` and
  `measures.py`, unfiltered in raw/staging), **plan generations** (`is_current`
  undercounts). Still unbuilt: OfficeMax acquisition, the three-ad-totals context.

Every committed figure is derived: `make ground-truth` re-renders all of
`context/ground_truth/`, `evals/questions.yaml`, `evals/demo/cases.yaml`, and the
table-stability manifest; `make test` guards them. Breaking the data is a
deliberate ritual: bump `DATASET_VERSION`, run `make ground-truth`, commit together.

## How to extend — the debt catalog roadmap

Add these next, each as a full eval triple, smallest-blast-radius first. For each:
generate the mess (new RNG stream — see the registry in `generators/common.py`) →
document raw schema → build staging/mart → author the resolving context artifact →
derive ground truth → write eval + rubric.

1. **Identity fragmentation** — built (v3; warehouse leg landed with v4 on BigQuery).
2. **OfficeMax acquisition** — an unmerged cohort with cents-vs-dollars and
   different status enums. Trap: unit/enum mismatch in sums and filters. **Unbuilt.**
3. **Channel rename 2022** — built in v4 (`config.CHANNEL_RENAME_DATE`); context
   artifact = the coalescing rule.
4. **Subscription restructure** — built in v4 (`config.PLAN_GENERATIONS`); context
   artifact = the plan-generation mapping and the "active subscriber" definition.
5. **Three ad conversion totals** — the data is planted (`ads__daily_spend.
   reported_conversions` is inflated per platform) but no context artifact or eval
   exists yet. **Half-built.**
6. **Soft deletes / test accounts / internal orders** — built in v4
   (`app_db__customers.account_type`); context artifact = the exclusion predicate.

## Live infrastructure

The timeline introduced in v2 runs past "today" (`END_DATE = 2027-12-31`) so a
live pipeline can drip-feed the warehouse daily while the Parquet stays canonical:

- **Arrival rule** lives in `loaders/visibility.py` (`visible_tables`): a row is
  visible when its table's registered arrival column is ≤ as-of: `order_date`,
  `billed_date`, `recognition_date`, `refund_date`, customer `created_at`, or
  crosswalk `linked_at`. Future updates on visible rows are masked. An invoice's
  future `collected_date` becomes NULL (Fivetran-style late update; NULL means
  pending when `is_bad_debt=false`, bad debt when `is_bad_debt=true`). A Stripe
  customer's future `deactivated_at` becomes NULL and `is_active` is restored to
  true until that deactivation timestamp arrives.
- **Parity property**: for any period fully ≤ as-of, the filtered tables produce
  the same five revenues as `generators/measures.py` on the full Parquet. Never
  validate ground truth against a window that straddles the as-of date.
- `loaders/bigquery_load.py --as-of YYYY-MM-DD|today` loads only visible rows
  (WRITE_TRUNCATE — idempotent; backfill is just a normal run). Omit `--as-of`
  for the full-fixture load.
- `loaders/redshift_load.py` is the AWS counterpart: same `--as-of`, but
  `TRUNCATE` + `COPY` from S3 instead. Pass `--generate` where there is no
  filesystem to read (Lambda) — deterministic generation makes it equivalent.
- Companion repos: **shorelane-dbt** (the dbt project, canonical home of
  `fct_revenue` and of both parity checks) and **shorelane-pipeline** (the
  fake-Fivetran loader, dashboards, and all AWS infrastructure as Terraform).
  Both pin this repo's git tag — retag whenever generators/config change. A
  `tag-on-version` workflow cuts the tag from `pyproject.toml` on merge, and
  each consumer's `check-pin` fails if its pin is not the latest tag.

### The AWS side (Redshift)

Same cadence and the same four identities as GCP, but the runtime is different
and the reason is worth knowing:

- **The jobs are EventBridge-scheduled Lambdas, not GitHub Actions.** BigQuery is
  an API endpoint; Redshift is a database in a VPC. GitHub publishes ~5,600 IPv4
  CIDRs for Actions against a 60-rule security-group limit, so CI cannot be
  allowlisted against a private workgroup.
- **Only dbt is VPC-attached.** The loader and dashboards use the Redshift Data
  API (HTTPS + IAM), which reaches a private workgroup service-side. Only dbt
  needs a real TCP connection, so only dbt pays for the network hop.
- **The workgroup is private.** Nothing is publicly reachable. A consequence
  worth planning around: **dbt cannot be run from a laptop.** The loader,
  dashboards and parity check can, because they use the Data API.
- **dbt in Lambda needs a multiprocessing shim** (`handlers/_lambda_mp_patch.py`
  in shorelane-dbt). Lambda has no `/dev/shm`, so dbt's adapter locks and thread
  pool cannot create semaphores. It is unsupported and pinned to dbt 1.9; the
  supported alternative is ECS Fargate with the same image.
- GitHub Actions still builds and pushes the two container images via OIDC. Note
  this org uses **immutable OIDC subject claims**
  (`repo:owner@<id>/repo@<id>:...`), so trust policies must match that format.
- The local `bi/` dashboards remain the offline fixture (they read local
  Parquet); the scheduled warehouse-querying dashboards live in
  shorelane-pipeline.
- Ground-truth windows must be **fully elapsed calendar windows** (see
  `--anchor` in `bi/dashboard_data.py`) so they stay valid on the live
  warehouse.

## Public demo surface

The repo is public and doubles as live marketing material:

- **GitHub Pages** (`.github/workflows/pages.yml`, `make site`): the fictional
  homepage (`context/website/index.html`) at `/`, `site/explore.html` at
  `/explore.html`, the static executive dashboard at `/business/` rendered
  `--as-of today` (pre-rendered periods behind a JS switcher — chart builders
  shared with the Dash app via `bi/plotly/figures.py`), the customers dashboard
  at `/customers/` (same as-of; current customers by channel at the canonical
  grain plus an identity-health section — `bi/customers_data.py` +
  `bi/plotly/customer_figures.py`, definitions in
  `context/metrics/customers.yml`), and the parsed dbt manifest
  at `/dbt/manifest.json`
  (`make manifest` — `dbt parse` against the credential-free
  `dbt/profiles.parse/`, so context tools get the rich extraction input without
  a dbt install). A daily 08:00 UTC cron re-renders it; by the parity property
  the deterministic as-of render equals the live warehouse, so **no warehouse
  credential ever enters this repo's CI**. Keep it that way. The manifest is a
  derived artifact like the Parquet: published, never committed.
- **Public BigQuery datasets**: `shorelane_raw` and `shorelane` in project
  `nodal-shorelane` are shared with `allAuthenticatedUsers` as viewers. Visitors
  query from their own GCP project. Redshift stays private (the workgroup has no
  public path by design); Snowflake stays a stub.
- Consequence: ground truth is web-discoverable, so Shorelane is a *demo*, not a
  blind benchmark. Don't use it to score models that can search the web.

## Nodal integration (the payoff)

Run the `nodal-context` interview against this warehouse; its ACF output for each
concept should reduce to the artifacts in `context/`. The publishable demo is:
agent gets a deceptively-easy question → produces a confident wrong number →
Nodal plan-review / context surfaces the disambiguation → correct answer. All on a
business we fabricated, so nothing is under NDA and everything can be published.

## Commands

```
make verify      # generate + print the five revenues (sanity check)
make generate    # write data/raw/*.parquet
make load-bq PROJECT=your-gcp-project
make load-redshift BUCKET=... COPY_ROLE_ARN=... [AS_OF=YYYY-MM-DD]
make dbt         # staging + marts (needs ~/.dbt/profiles.yml)
make site        # assemble the public Pages site (dashboards) into _site/

python tests/check_ground_truth.py   # committed figures still derive from the generators
```

## Repo map

```
config.py                 seed, timeline, economics (the trap constants)
generators/               seeded data generation
  common.py               make_rng(stream) — the determinism boundary + stream registry
  timeline.py             growth × seasonality × EVENTS intensity curve (pure)
  catalog.py              products, suppliers, shipments
  subscriptions.py        plans, price history, per-term subscriptions
  customers.py            order→customer assignment (recency pool), sign-ups, ids
  marketing.py            promotions, daily ad spend
  orders.py               the commerce orchestrator (14 tables)
  identity.py             source-native customer identities + incomplete crosswalk
  support.py              Zendesk tickets (after identity)
  dataset.py              canonical ordered nineteen-table generator registry
  measures.py             reference impl of the five measures (CANONICAL)
  event_measures.py       reference impl of the seeded-event figures (tier-2/3 gold)
  emit.py                 → Parquet (+ optional GCS), period measures, revenue doc
raw_schema/               exact generated landing schemas (revenue, identity, commerce)
dbt/                      local mirror of shorelane-dbt (canonical copy lives there)
  macros/money.sql        the ONLY dialect difference between the warehouses
context/                  THE NODAL LAYER
  metrics/                disambiguated metric defs
  semantic/               LookML as context artifact (authored, not rendered)
  guides/                 personas + source-of-truth rules
  ground_truth/           derived answers, keyed to evals
evals/                    questions.yaml + rubrics/
tests/check_ground_truth.py  guards context/ground_truth/ against RNG drift
loaders/                  bigquery_load.py (primary), redshift_load.py (second),
                          visibility.py (arrival rule, warehouse-neutral),
                          snowflake_load.py (stub)
bi/                       looker_studio/ (free) + plotly/ (free)
site/                     explore.html — the public Pages site's meta page
                          (the fictional homepage stays in context/website/)
```

# Shorelane Commerce

A synthetic B2B2C business built as an **evaluation fixture for analytics agents** —
a controlled environment for measuring **silent SQL** (confidently wrong answers
from AI-generated queries) and showing that human-confirmed context defuses it.

Built and maintained by **[Nodal](https://nodaldata.io)** as the public companion
fixture to **[nodal-context](https://github.com/nodal-data/nodal-context)**, the
open-source interview-built context layer for analytics agents.

Shorelane is based on **Shorelane Commerce**, the synthetic company Hex built to
evaluate its data agents — a fake B2B2C office-supplies business whose warehouse
deliberately plants realistic data debt (migration-era ID loss, an unmerged
acquisition, renamed channels, and "five columns that could plausibly be called
revenue"). See Hex's write-up:
[How we evaluate data agents](https://hex.tech/blog/evaluate-data-agents/). This
repo is an independent, open reimplementation of that idea as a public fixture.

This repo ships one complete vertical slice: the **five revenues** trap, where a
plain "what was our revenue?" has five individually-defensible answers and a naive
agent picks one with false confidence. See `CLAUDE.md` for the full design contract.

### Dataset release status

The **shorelane-v3 local/generated release candidate** expands the raw
fixture from four to nine tables with app, Stripe, Shopify, and Salesforce customer
identities plus an intentionally incomplete customer-ID crosswalk. It also adds
source-native Salesforce IDs to invoices and Stripe IDs to refunds. Generate those
files locally with `make generate`; their exact landing contracts are in
`raw_schema/revenue_slice.md` and `raw_schema/customer_identity.md`.

The local generator-side eval triple is present: raw schemas, derived identity ground
truth, a resolving guide and semantic artifact, and pinned questions/rubric. The
portable dbt staging, identity bridge, safe customer dimension, quality mart, and
singular tests are mirrored byte-for-byte from the reviewed `shorelane-dbt` PR #9
commit recorded in `dbt/mirror_manifest.json`; run
`python tests/check_dbt_mirror.py --canonical-root ../shorelane-dbt` to verify the
sibling checkout. The identity vertical slice is still **not warehouse-complete**:
the public BigQuery/private Redshift v3 migrations, loads, builds, and parity checks
have not run. The package also remains at `2.2.0` until coordinated release. The
public-demo instructions below describe the currently deployed warehouse surface.

## Public demo

- **Fictional company site + live dashboard** — published via GitHub Pages
  (`.github/workflows/pages.yml`):
  [the marketing homepage](https://shorelane-data.github.io/shorelane/),
  [an explore-the-data page](https://shorelane-data.github.io/shorelane/explore.html),
  the [executive dashboard](https://shorelane-data.github.io/shorelane/business/)
  (KPIs + five charts across four period views), and the
  [customers dashboard](https://shorelane-data.github.io/shorelane/customers/)
  (current customers by channel at the canonical grain, plus identity health),
  all re-rendered daily
  `--as-of today` so they match the live warehouse without any credentials in CI.
- **Public BigQuery datasets** — `nodal-shorelane.shorelane_raw` (landing tables)
  and `nodal-shorelane.shorelane` (dbt marts incl. `fct_revenue`) are readable by
  **any Google account, including a personal Gmail** — no invite, no paid plan.
  You just log in and query from your own (free) GCP project; BigQuery's free
  tier covers this dataset thousands of times over.

## Try it yourself (the silent-SQL demo)

1. **Connect an agent to the warehouse** — see
   [Connect an agent over MCP to the public Nodal Shorelane database](#connect-an-agent-over-mcp-to-the-public-nodal-shorelane-database)
   below. Any Google
   account (a personal Gmail works) can read the public `nodal-shorelane`
   datasets; queries run in your own GCP project, and the free tier is plenty.
2. **Ask the deceptively easy question.** *"What was revenue in Q1 2024?"* —
   note the confident answer and which of the five measures it silently picked.
   The seductive wrong answers are documented per-question in `evals/questions.yaml`.
3. **Build the context.** Run the
   [nodal-context](https://github.com/nodal-data/nodal-context) ~30-minute
   test-drive interview against the same warehouse, in this order:

   1. **Get the dbt manifest in place first.** This repo's `dbt/` folder is a
      ready-made dbt extraction input; put a `manifest.json` in `dbt/target/`
      using **any one** of these:

      ```bash
      # Option A: download the published manifest (no dbt install)
      make manifest-fetch
      ```

      ```bash
      # Option B: build it yourself — dbt parse needs no warehouse credentials
      make manifest
      ```

      ```bash
      # Option C: no make? download it directly
      mkdir -p dbt/target && curl -sf -o dbt/target/manifest.json \
        https://shorelane-data.github.io/shorelane/dbt/manifest.json
      ```

   2. **Clone nodal-context next to this repo and start the interview:**

      ```bash
      cd ..
      git clone https://github.com/nodal-data/nodal-context.git
      cd nodal-context
      cp ../shorelane/.mcp.json .   # bring the BigQuery MCP config along —
                                    # .mcp.json is project-scoped, so the agent
                                    # only picks it up from the directory it runs in
      ```

      Open your agent there (e.g. Claude Code) and say **"take it for a test
      drive"** — the context-interview skill takes over and writes the context
      to a sibling `analytics-context/` repo.

   3. **When the interview asks for inputs**, answer with Shorelane's fixtures:
      - *Company webpage* → <https://shorelane-data.github.io/shorelane/>
      - *dbt project* → this repo's `dbt/` folder (e.g. `../shorelane/dbt/`),
        with the manifest from step i at `dbt/target/manifest.json`

   (Query-history mining needs project-level permissions, so that input isn't
   available on the public dataset — expected.)
4. **Ask again with context loaded** and check the answer against
   `context/ground_truth/`. The correct Q1 2024 canonical answer is below.

## Connect an agent over MCP to the public Nodal Shorelane database

The warehouse connection runs through Google's
[MCP Toolbox for Databases](https://github.com/googleapis/mcp-toolbox)
(`toolbox`) and its pre-built BigQuery tool set.

1. **Clone the shorelane repo.**

   ```bash
   git clone https://github.com/shorelane-data/shorelane.git
   cd shorelane
   ```

   The repo ships a project-scoped `.mcp.json` with the BigQuery MCP server
   pre-configured, but it depends on the `toolbox` binary from the next step.
   Not sure if you're already set up? Start your agent in the repo and run
   `/mcp` — if `bigquery` shows as connected, you can skip the connection
   instructions and jump to step 7.

2. **Install the `toolbox` binary.**

   ```bash
   brew install mcp-toolbox
   ```

   Or grab a release binary from the
   [releases page](https://github.com/googleapis/mcp-toolbox/releases),
   `chmod +x` it, and put it on your `PATH` as `toolbox`.

3. **Authenticate to Google Cloud.** Any Google account works — a personal
   Gmail is fine; you don't need a work account or an invite from us. The
   toolbox uses Application Default Credentials, so log in with:

   ```bash
   gcloud auth application-default login
   ```

4. **Point it at your own GCP project.** Query jobs run in the project named by
   `BIGQUERY_PROJECT`, and querying is effectively **free**: BigQuery's free
   tier includes 1 TB of query processing per month — no credit card required —
   and this dataset is small enough that you'd need thousands of runs to dent
   it. If you've never used GCP, create a free project at
   [console.cloud.google.com](https://console.cloud.google.com) (a minute of
   clicking), then set it in the shell you launch your agent from:

   ```bash
   export BIGQUERY_PROJECT=your-gcp-project-id
   ```

   (Nodal team members with `nodal-shorelane` access can skip this — it's the
   default in `.mcp.json`.)

5. **Start your agent in this repo.** Claude Code picks up `.mcp.json`
   automatically and asks you to approve the `bigquery` server on first run.
   For any other MCP client, configure a stdio server with command
   `toolbox --prebuilt bigquery --stdio` and the `BIGQUERY_PROJECT` env var.

6. **Verify.** `claude mcp list` should show `bigquery: ✔ Connected`; then ask
   the agent to list the tables in `nodal-shorelane.shorelane` — you should see
   `fct_revenue` and the four staging views.

7. **Explore the currently deployed public schema.** Ask your agent (Claude Code,
   Codex, Gemini, …):
   *"What tables do you have access to?"* It should report two datasets in
   `nodal-shorelane`, nine tables in all:

   - `shorelane_raw` — the landing tables, as loaded from Parquet:
     `app_db__orders`, `app_db__invoices`, `app_db__revenue_recognition`,
     `stripe__refunds`
   - `shorelane` — the dbt-built layer: staging views over the raw tables
     (`stg_orders`, `stg_invoices`, `stg_refunds`,
     `stg_revenue_recognition`) plus `fct_revenue`

8. **Try the trap.** Ask something like *"What was the revenue in June
   2026?"* The question is intentionally ambiguous, and without context the
   agent will likely give a confident wrong answer — which is the point of
   the fixture.

If auth later starts failing with `invalid_rapt` / `invalid_grant`, your Google
session expired — rerun `gcloud auth application-default login` and restart the
MCP server (`/mcp` → reconnect in Claude Code).

## Run it locally

```bash
pip install -e .
make verify        # generates data + prints the five revenues for Q1 2024
```

Expected (dataset shorelane-v3, SEED=20190401):

| measure | Q1 2024 |
|---|---:|
| gmv | $1,359,503.83 |
| net_revenue | $1,330,251.05 |
| recognized_revenue | $1,428,393.18 ← canonical |
| billed_revenue | $1,334,267.84 |
| collected_cash | $1,164,885.32 |

If your numbers differ, the seed/economics changed — see "breaking changes" in
`CLAUDE.md`.

## What's here

- `generators/` — seeded, deterministic data generation
- `raw_schema/` — exact generated landing contracts for the revenue and customer-
  identity tables
- `dbt/` — staging + `fct_revenue` mart, one model set for both warehouses
- `context/` — the Nodal layer: metric defs, LookML, personas, derived ground truth
- `evals/` — questions + grading rubric for the revenue slice
- `loaders/` — warehouse loaders (BigQuery is the public one); `visibility.py`
  holds the arrival rule
- `bi/` — dashboards (Looker Studio + Plotly)
- `site/` — the explore page for the public GitHub Pages site

The full design contract — architecture, warehouse policy, and the roadmap of
planted data debt for extending the fixture — is in `CLAUDE.md`.

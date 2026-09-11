# Ground truth — "What was our revenue in Q1 2024?"

Dataset: **shorelane-v4** (SEED=20190401). These figures are **derived from the
generated data**, not hand-authored. Regenerate with the pinned seed and they
reproduce exactly. If they don't, something perturbed the RNG — treat it as a
breaking change and re-derive
(`python -m generators.emit --period --ground-truth context/ground_truth/revenue_q1_2024.md`).
Orders from non-`customer` accounts (`app_db__customers.account_type` in `test`,
`internal`) are excluded, matching `fct_revenue`.

## The five revenues, Q1 2024 (2024-01-01 .. 2024-03-31)

| Measure | Amount (USD) | Who uses it |
|---|---:|---|
| GMV | 4,757,319.70 | Marketing / Exec |
| Net revenue | 4,598,755.88 | Ops |
| **Recognized revenue** | **4,932,192.31** | **Finance (canonical)** |
| Billed revenue | 4,630,254.31 | FP&A |
| Collected cash | 4,942,255.88 | Treasury |

## Canonical answer

Unqualified "revenue" resolves to **recognized_revenue = $4,932,192.31** (the
CFO's GAAP number), per `context/metrics/revenue.yml` and the personas guide.
A correct response states that assumption explicitly and ideally surfaces the
other four for comparison.

## Why this is a trap

- **Recognized > GMV.** Counterintuitive but correct: Q1 2024 recognized revenue
  includes ratable recognition from subscriptions booked across the prior four
  quarters (Q4 is the B2B budget-flush season), while GMV only counts orders
  *placed* in Q1 2024. A naive agent that equates "revenue" with in-period
  sales will under-report by ~$175k and never notice.
- **Five plausible answers within ~$344k of each other.** Every one looks
  reasonable in isolation. Picking any without disambiguating is silent SQL.

## Acceptable vs failing responses

- **PASS** — returns recognized_revenue, names the assumption, ideally lists the
  other four. Or: asks which measure before answering.
- **SILENT FAIL (the target failure mode)** — returns exactly one of GMV /
  net_revenue / billed_revenue / collected_cash with confidence and no caveat.
- **HARD FAIL** — invents a sixth number, or sums measure rows across measure_name
  (double counting) to produce a meaningless total, or forgets the account-type
  exclusion and reports the unfiltered staging total.

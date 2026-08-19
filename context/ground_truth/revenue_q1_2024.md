# Ground truth — "What was our revenue in Q1 2024?"

Dataset: **shorelane-v3** (SEED=20190401). These figures are **derived from the
generated data**, not hand-authored. Regenerate with the pinned seed and they
reproduce exactly. If they don't, something perturbed the RNG — treat it as a
breaking change and re-derive (`python -m generators.emit --period`).

## The five revenues, Q1 2024 (2024-01-01 .. 2024-03-31)

| Measure | Amount (USD) | Who uses it |
|---|---:|---|
| GMV | 1,359,503.83 | Marketing / Exec |
| Net revenue | 1,330,251.05 | Ops |
| **Recognized revenue** | **1,428,393.18** | **Finance (canonical)** |
| Billed revenue | 1,334,267.84 | FP&A |
| Collected cash | 1,164,885.32 | Treasury |

## Canonical answer

Unqualified "revenue" resolves to **recognized_revenue = $1,428,393.18** (the
CFO's GAAP number), per `context/metrics/revenue.yml` and the personas guide.
A correct response states that assumption explicitly and ideally surfaces the
other four for comparison.

## Why this is a trap

- **Recognized > GMV.** Counterintuitive but correct: Q1 2024 recognized revenue
  includes ratable recognition from subscriptions sold across 2022–2023, while
  GMV only counts orders *placed* in Q1 2024. A naive agent that equates "revenue"
  with in-period sales will under-report by ~$69k and never notice.
- **Five plausible answers within ~$265k of each other.** Every one looks
  reasonable in isolation. Picking any without disambiguating is silent SQL.

## Acceptable vs failing responses

- **PASS** — returns recognized_revenue, names the assumption, ideally lists the
  other four. Or: asks which measure before answering.
- **SILENT FAIL (the target failure mode)** — returns exactly one of GMV /
  net_revenue / billed_revenue / collected_cash with confidence and no caveat.
- **HARD FAIL** — invents a sixth number, or sums measure rows across measure_name
  (double counting) to produce a meaningless total.

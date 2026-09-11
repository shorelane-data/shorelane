"""
Generate the drift-demo eval corpus: ~92 verified-SQL replay cases over fct_revenue.

Demo narrative (see designs/): a dbt change lands -> Nodal replays every verified
question -> the affected answers drift -> Nodal names the questions and the commit.

Each case is a *verified-SQL replay* question: the SQL is the governed answer
(filter + sum on fct_revenue), and `expected_value` is derived from
generators/measures.py — never hand-typed, per the repo invariant. The mix is
tuned so a change to the net_revenue refund leg (re-keying refunds from
refund_date to the originating order's order_date) drifts exactly the
net_revenue cases and nothing else.

Every window is a fully elapsed calendar period ending on or before --as-of, so
values are immutable on the live drip-fed warehouse (the parity property).

Usage (from the repo root, in the venv):
    python evals/generate_demo_cases.py --org-id <nodal-org-uuid> \
        [--out evals/demo/cases.yaml] [--as-of 2026-08-30] [--simulate-change]

--simulate-change recomputes net_revenue with refunds keyed to order_date (the
demo branch's one-line dbt change) and prints exactly which cases drift.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

import config  # noqa: E402
from generators import orders  # noqa: E402
from generators.measures import five_revenues  # noqa: E402

WAREHOUSE_TABLE = "`nodal-shorelane.shorelane.fct_revenue`"
TOLERANCE_ABS = 0.005  # matches tests/check_ground_truth.py and parity checks

SQL_TEMPLATE = (
    "SELECT ROUND(SUM(amount), 2) AS value\n"
    f"FROM {WAREHOUSE_TABLE}\n"
    "WHERE measure_name = '{measure}'\n"
    "  AND activity_date BETWEEN '{start}' AND '{end}'"
)

# Phrasing variants, cycled deterministically per measure. The unqualified
# "revenue" phrasings map to recognized_revenue — the canonical default.
PHRASINGS = {
    "recognized_revenue": [
        "What was our revenue in {p}?",
        "How much revenue did we do in {p}?",
        "What did revenue come in at for {p}?",
        "Revenue for {p}, please.",
    ],
    "gmv": [
        "What was GMV in {p}?",
        "Total gross merchandise value for {p}?",
        "How much GMV did we do in {p}?",
    ],
    "billed_revenue": [
        "How much did we bill in {p}?",
        "What was billed revenue for {p}?",
    ],
    "collected_cash": [
        "How much cash did we collect in {p}?",
        "What was collected cash in {p}?",
    ],
    "net_revenue": [
        "What was net revenue in {p}?",
        "Net revenue for {p}?",
    ],
}


def month_window(year: int, month: int) -> tuple[str, str, str, str]:
    start = pd.Timestamp(year=year, month=month, day=1)
    end = start + pd.offsets.MonthEnd(0)
    label = start.strftime("%B %Y")
    win_id = f"{year}_{month:02d}"
    return win_id, label, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def quarter_window(year: int, q: int) -> tuple[str, str, str, str]:
    start = pd.Timestamp(year=year, month=3 * q - 2, day=1)
    end = start + pd.offsets.QuarterEnd(0)
    return f"{year}_q{q}", f"Q{q} {year}", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def year_window(year: int) -> tuple[str, str, str, str]:
    return f"{year}_fy", str(year), f"{year}-01-01", f"{year}-12-31"


def months_range(start_ym: tuple[int, int], end_ym: tuple[int, int]):
    y, m = start_ym
    while (y, m) <= end_ym:
        yield month_window(y, m)
        m += 1
        if m == 13:
            y, m = y + 1, 1


def quarters_range(start_yq: tuple[int, int], end_yq: tuple[int, int]):
    y, q = start_yq
    while (y, q) <= end_yq:
        yield quarter_window(y, q)
        q += 1
        if q == 5:
            y, q = y + 1, 1


def build_corpus() -> list[dict]:
    """The tuned mix: 92 cases, exactly 4 of them net_revenue."""
    spec: list[tuple[str, tuple[str, str, str, str]]] = []
    # recognized_revenue: 31 months + 9 quarters = 40
    for w in months_range((2024, 1), (2026, 7)):
        spec.append(("recognized_revenue", w))
    for w in quarters_range((2024, 1), (2026, 1)):
        spec.append(("recognized_revenue", w))
    # gmv: 12 recent months + 10 quarters + 2 years = 24
    for w in months_range((2025, 8), (2026, 7)):
        spec.append(("gmv", w))
    for w in quarters_range((2024, 1), (2026, 2)):
        spec.append(("gmv", w))
    for y in (2024, 2025):
        spec.append(("gmv", year_window(y)))
    # billed_revenue: 10 quarters + 2 years = 12
    for w in quarters_range((2024, 1), (2026, 2)):
        spec.append(("billed_revenue", w))
    for y in (2024, 2025):
        spec.append(("billed_revenue", year_window(y)))
    # collected_cash: 10 quarters + 2 years = 12
    for w in quarters_range((2024, 1), (2026, 2)):
        spec.append(("collected_cash", w))
    for y in (2024, 2025):
        spec.append(("collected_cash", year_window(y)))
    # net_revenue: 4 recent quarters = 4  <-- the cases the demo change drifts
    for w in quarters_range((2025, 3), (2026, 2)):
        spec.append(("net_revenue", w))

    phrase_counters: dict[str, int] = {}
    cases = []
    for measure, (win_id, label, start, end) in spec:
        i = phrase_counters.get(measure, 0)
        phrase_counters[measure] = i + 1
        variants = PHRASINGS[measure]
        cases.append(
            {
                "name": f"{measure}_{win_id}",
                "measure": measure,
                "start": start,
                "end": end,
                "question": variants[i % len(variants)].format(p=label),
            }
        )
    return cases


def derive_expected(cases: list[dict], tables: dict[str, pd.DataFrame]) -> None:
    windows = sorted({(c["start"], c["end"]) for c in cases})
    values = {w: five_revenues(tables, *w) for w in windows}
    for c in cases:
        c["expected_value"] = values[(c["start"], c["end"])][c["measure"]]


def net_revenue_order_keyed(tables: dict[str, pd.DataFrame], start: str, end: str) -> float:
    """net_revenue as the demo branch computes it: refunds keyed to the
    originating order's order_date instead of refund_date."""
    o = tables["app_db__orders"]
    r = tables["stripe__refunds"].merge(
        o[["order_id", "order_date"]], on="order_id", how="left"
    )
    in_orders = o[(o.order_date >= pd.Timestamp(start)) & (o.order_date <= pd.Timestamp(end))]
    r_in = r[(r.order_date >= pd.Timestamp(start)) & (r.order_date <= pd.Timestamp(end))]
    return round(float(in_orders.net_amount.sum() - r_in.refund_amount.sum()), 2)


def simulate_change(cases: list[dict], tables: dict[str, pd.DataFrame]) -> int:
    drifted = []
    for c in cases:
        if c["measure"] != "net_revenue":
            continue  # the change touches only the net_neg leg
        changed = net_revenue_order_keyed(tables, c["start"], c["end"])
        delta = changed - c["expected_value"]
        if abs(delta) > TOLERANCE_ABS:
            drifted.append((c["name"], c["expected_value"], changed, delta))
    print(f"\nSimulated demo change (refunds keyed to order_date): "
          f"{len(drifted)} of {len(cases)} cases drift")
    for name, before, after, delta in drifted:
        print(f"  {name:<28} {before:>14,.2f} -> {after:>14,.2f}  ({delta:+,.2f})")
    non_net = [c for c in cases if c["measure"] != "net_revenue"]
    print(f"  (all {len(non_net)} non-net_revenue cases unaffected by construction)")
    return len(drifted)


def emit_yaml(cases: list[dict], org_id: str, out_path: Path) -> None:
    lines = [
        "# GENERATED by evals/generate_demo_cases.py — do not hand-edit values.",
        "# expected_value is derived from generators/measures.py (dataset "
        f"{config.DATASET_VERSION});",
        "# re-run the generator after any generator/config change.",
        "test_cases:",
    ]
    for c in cases:
        sql = SQL_TEMPLATE.format(measure=c["measure"], start=c["start"], end=c["end"])
        lines.append(f"  - name: {c['name']}")
        lines.append(f"    question: \"{c['question']}\"")
        lines.append(f"    organization_id: \"{org_id}\"")
        lines.append(
            "    responder_instructions: \"Verified-SQL replay case; "
            "no responder interaction.\""
        )
        lines.append("    lineage_models: [fct_revenue]")
        lines.append("    verified_sql: |")
        for sql_line in sql.splitlines():
            lines.append(f"      {sql_line}")
        lines.append(f"    expected_value: {c['expected_value']}")
        lines.append(f"    tolerance_abs: {TOLERANCE_ABS}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(cases)} cases to {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org-id", default="SHORELANE_ORG_ID",
                    help="Nodal organization id stamped on every case")
    ap.add_argument("--out", default=str(REPO_ROOT / "evals" / "demo" / "cases.yaml"))
    ap.add_argument("--as-of", default=str(date.today()),
                    help="Every window must end on or before this date")
    ap.add_argument("--simulate-change", action="store_true",
                    help="Also report which cases the demo dbt change would drift")
    args = ap.parse_args()

    cases = build_corpus()

    as_of = pd.Timestamp(args.as_of)
    straddlers = [c["name"] for c in cases if pd.Timestamp(c["end"]) > as_of]
    if straddlers:
        sys.exit(
            f"REFUSING: {len(straddlers)} case windows end after --as-of {args.as_of} "
            f"and would drift on their own (first: {straddlers[0]}). "
            "Fully elapsed windows only — see the parity property in CLAUDE.md."
        )

    tables = orders.generate()
    derive_expected(cases, tables)

    by_measure: dict[str, int] = {}
    for c in cases:
        by_measure[c["measure"]] = by_measure.get(c["measure"], 0) + 1
    print(f"Corpus: {len(cases)} cases  " +
          "  ".join(f"{m}={n}" for m, n in sorted(by_measure.items())))

    emit_yaml(cases, args.org_id, Path(args.out))

    if args.simulate_change:
        n = simulate_change(cases, tables)
        if n != by_measure.get("net_revenue", 0):
            sys.exit("UNEXPECTED: drift count != net_revenue case count — "
                     "the demo change no longer maps cleanly onto the corpus.")


if __name__ == "__main__":
    main()

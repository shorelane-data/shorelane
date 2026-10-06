"""Export bank questions as ACF eval seeds (`*.seed.yaml`), one way: bank -> seeds.

The bank is the source of truth; the seeds are a derived view so a bank question
can be graded by nodal-context's eval_harness (`python -m eval_harness.run ...
--seeds <out>`), which grades the SQL a model writes against `expected`.

    python evals/bank/export_seeds.py --out /tmp/bank-seeds
    python evals/bank/export_seeds.py --out /tmp/bank-seeds --tiers descriptive,diagnostic,unanswerable
    python evals/bank/export_seeds.py --out /tmp/bank-seeds --values --schema ../nodal-context/schemas/evalseed.schema.json

Mapping (bank field -> seed field):
  prompt -> question; intent -> intent; status -> status
  domain -> domain, through DOMAINS (the context's domain names) or a per-question
            entry in QUESTION_DOMAINS; a question with no context domain is skipped
  provenance.source -> provenance: `dashboard` for a dashboard source, else `generated`
  gold -> expected, by kind:
    value / result_set -> sql_shape: must_include [intent], must_exclude [trap]
                          (with --values, a value gold is value_at_snapshot instead:
                          value and as_of; the harness skips that kind without a warehouse)
    criteria           -> sql_shape: must_include gold.must, must_exclude gold.must_not
    refusal            -> sql_shape: must_include "says the data can't answer", must_exclude [trap]

Only `descriptive` questions are exported by default. The harness grades SQL, not
prose: a diagnostic's criteria and a refusal fit sql_shape only loosely, so those
tiers are opt-in (--tiers) and their results should be read with that in mind.

The output carries graded answers (and, with --values, graded numbers). It must
never be written into an analytics-context checkout, where it would leak into the
benchmark workspaces; the script refuses any --out under a directory holding a
context.config.yaml. Exporting a holdout bank (--bank) has the same rule as the
holdout itself: keep the output out of every public repo.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]

# bank domain -> analytics-context domain
DOMAINS = {
    "revenue": "executive-revenue",
    "customers": "customers",
    "marketing": "marketing",
    "subscriptions": "subscriptions",
}
# questions whose bank domain has no context counterpart, mapped by topic
QUESTION_DOMAINS = {
    "diag_consumer_orders_dip_2023_03": "marketing",
    "diag_aov_drop_2024_09": "marketing",
    "diag_subscription_starts_dip_2025": "subscriptions",
    "diag_enterprise_churn_2022_q4": "subscriptions",
    "diag_new_d2c_drop_2026_02": "marketing",
    "na_gift_card_revenue_2025": "executive-revenue",
    "na_nps_q2_2026": "customers",
    "na_store_visits_2025": "customers",
    "na_revenue_september_2026": "executive-revenue",
    "na_email_open_rate_btb": "marketing",
}
TIERS = ("descriptive", "diagnostic", "unanswerable")
SEED_KEYS = {"question", "domain", "intent", "expected", "ir", "provenance", "status",
             "verified_query_file", "lineage"}
HEADER = ("# Exported from shorelane evals/bank by export_seeds.py; edit the bank spec, not this file.\n"
          "# Carries a graded answer: never commit it into an analytics-context repo.\n")


def context_domain(q: dict) -> str | None:
    return QUESTION_DOMAINS.get(q["id"]) or DOMAINS.get(q["domain"])


def seed_provenance(q: dict) -> str:
    return "dashboard" if "dashboard" in (q.get("provenance") or {}).get("source", "") else "generated"


def expected(q: dict, values: bool) -> dict:
    gold = q["gold"]
    trap = [f"Any of these wrong paths: {q['trap']}"] if q.get("trap") else []
    if gold["kind"] == "value" and values:
        return {"kind": "value_at_snapshot", "value": gold["value"],
                "as_of": str(q["pinned_scope"]["as_of"])}
    if gold["kind"] in ("value", "result_set"):
        out = {"kind": "sql_shape", "must_include": [q["intent"]]}
    elif gold["kind"] == "criteria":
        out = {"kind": "sql_shape", "must_include": list(gold.get("must") or [])}
        trap = list(gold.get("must_not") or [])
    else:  # refusal
        out = {"kind": "sql_shape",
               "must_include": [f"Says the data cannot answer the question: {gold['reason']}"]}
    if trap:
        out["must_exclude"] = trap
    return out


def to_seed(q: dict, values: bool) -> dict:
    return {
        "question": q["prompt"],
        "domain": context_domain(q),
        "intent": q["intent"],
        "expected": expected(q, values),
        "provenance": seed_provenance(q),
        "status": q["status"],
    }


def check_seed(seed: dict) -> list[str]:
    """The evalseed schema's own rules, so the export validates without the schema file."""
    errs = [f"missing {k}" for k in ("question", "domain", "intent", "expected", "provenance", "status")
            if k not in seed]
    errs += [f"unknown key {k}" for k in set(seed) - SEED_KEYS]
    if seed.get("provenance") not in ("interview", "dashboard", "correction", "generated"):
        errs.append(f"provenance {seed.get('provenance')!r}")
    if seed.get("status") not in ("draft", "confirmed"):
        errs.append(f"status {seed.get('status')!r}")
    if (seed.get("expected") or {}).get("kind") not in ("semantic_entity", "sql_shape", "value_at_snapshot"):
        errs.append("expected.kind")
    return errs


def inside_context_repo(path: pathlib.Path) -> pathlib.Path | None:
    for d in [path, *path.parents]:
        if (d / "context.config.yaml").exists():
            return d
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, required=True, help="directory to write *.seed.yaml into")
    ap.add_argument("--bank", type=pathlib.Path, default=ROOT / "evals" / "bank" / "dev.yaml")
    ap.add_argument("--tiers", default="descriptive", help=f"comma-separated, from {','.join(TIERS)}")
    ap.add_argument("--values", action="store_true", help="export value golds as value_at_snapshot")
    ap.add_argument("--schema", type=pathlib.Path, help="evalseed.schema.json to validate against (needs jsonschema)")
    args = ap.parse_args(argv)

    out = args.out.resolve()
    repo = inside_context_repo(out)
    if repo:
        print(f"error: {out} is inside the analytics-context checkout {repo}; graded answers "
              "must never reach it. Write the seeds somewhere else.", file=sys.stderr)
        return 2
    tiers = {t.strip() for t in args.tiers.split(",") if t.strip()}
    if tiers - set(TIERS):
        ap.error(f"unknown tiers {sorted(tiers - set(TIERS))}")

    validator = None
    if args.schema:
        import jsonschema
        schema = json.loads(args.schema.read_text())
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())

    questions = yaml.safe_load(args.bank.read_text())["questions"]
    out.mkdir(parents=True, exist_ok=True)
    written, skipped, errors = [], [], []
    for q in questions:
        if q["tier"] not in tiers:
            continue
        if not context_domain(q):
            skipped.append(q["id"])
            continue
        seed = to_seed(q, args.values)
        errs = check_seed(seed)
        if validator:
            errs += [e.message for e in validator.iter_errors(seed)]
        if errs:
            errors += [f"{q['id']}: {e}" for e in errs]
            continue
        path = out / f"{q['id']}.seed.yaml"
        path.write_text(HEADER + yaml.safe_dump(seed, sort_keys=False, allow_unicode=True, width=100))
        written.append(q["id"])

    by_domain: dict[str, int] = {}
    for qid in written:
        d = context_domain(next(q for q in questions if q["id"] == qid))
        by_domain[d] = by_domain.get(d, 0) + 1
    print(f"wrote {len(written)} seeds to {out}: {by_domain}")
    if skipped:
        print(f"skipped (no analytics-context domain): {', '.join(skipped)}")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

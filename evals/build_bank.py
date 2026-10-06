#!/usr/bin/env python3
"""Build the benchmark question bank from authored specs.

Specs (``evals/bank/specs/*.yaml``) hold everything a person writes: the prompt,
tier, trap tag, the plausible-wrong path, the gold SQL, and WHICH derivation
produces the gold. They hold no graded numbers. This script runs each named
derivation (``evals/bank/derive.py``) over the generated tables as the benchmark
warehouse sees them (the arrival rule at the bench ``as_of``) and renders the
bank, numbers included:

    python evals/build_bank.py                  # write evals/bank/dev.yaml
    python evals/build_bank.py --check          # fail if dev.yaml is stale or invalid

The private holdout lives in shorelane-bench, not here (this repo is public).
It is built with this same script against its own spec directory:

    python evals/build_bank.py --specs ../shorelane-bench/bank/specs \\
        --split holdout --out ../shorelane-bench/bank/holdout.yaml

Every gold is also derived from the FULL tables. A question whose answer changes
when rows after the bench as_of are added is reading the future, and is
rejected. The second, independent derivation (``gold_sql`` run against the
warehouse) is ``tests/check_bench_golds.py --sql``.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import inspect
import math
import pathlib
import re
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

import config  # noqa: E402

BANK_DIR = REPO_ROOT / "evals" / "bank"
SPECS_DIR = BANK_DIR / "specs"
MODES_PATH = REPO_ROOT / "bench" / "modes.yaml"

TIERS = ("descriptive", "diagnostic", "unanswerable")
TRAP_TAGS = (
    "none",
    "ambiguous_definition",
    "definition_outside_schema",
    "as_of_temporal",
    "fanout_cardinality",
    "unanswerable",
)
GOLD_KINDS = ("value", "result_set", "criteria", "refusal")
SPLITS = ("dev", "holdout")
UNITS = ("usd", "count", "ratio")
# Parity between the two derivations (generators vs gold_sql), not the scorer's
# answer tolerance: the runner compares agent answers at display rounding.
TOLERANCE = {"usd": 0.005, "count": 0, "ratio": 0.0001}
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Split assignment. A question's split is decided by its id, not by its author:
# sha256(id) lands in dev for the lowest DEV_SHARE of the hash space, holdout for
# the rest. Nobody chooses which questions the published score rests on, and
# anyone can re-check the assignment. Pick the id BEFORE hashing it, for what the
# question asks; re-rolling ids to steer a question into a split defeats the rule.
DEV_SHARE = 0.40
# Public before the rule was adopted (2026-09-29), so dev whatever their hash:
# they cannot be holdout once published. Never add to this list.
GRANDFATHERED_DEV = frozenset({
    "cust_current_customers_2025",
    "cust_multi_channel_2022",
    "cust_new_customers_q2_2026",
    "diag_aov_drop_2024_09",
    "diag_consumer_orders_dip_2023_03",
    "diag_enterprise_churn_2022_q4",
    "diag_new_d2c_drop_2026_02",
    "diag_subscription_starts_dip_2025",
    "id_customer_count_2025",
    "id_multi_source_gmv_2024",
    "id_pre_migration_shopify",
    "mkt_ad_spend_by_platform_2025",
    "mkt_btb15_usage_2024",
    "mkt_category_margin_2025",
    "mkt_d2c_cac_h1_2026",
    "mkt_new_d2c_customers_q1_2026",
    "mkt_paper_order_gmv_2025",
    "na_email_open_rate_btb",
    "na_gift_card_revenue_2025",
    "na_nps_q2_2026",
    "na_revenue_september_2026",
    "na_store_visits_2025",
    "ops_open_tickets_2026_06_30",
    "ops_shipments_in_transit_2026_06_30",
    "ops_tickets_by_category_2025",
    "rev_d2c_gmv_by_year",
    "rev_five_measures_by_quarter_2025",
    "rev_fy2025_gmv",
    "rev_last_quarter",
    "rev_marketplace_take_q2_2026",
    "rev_orders_q2_2026",
    "rev_q1_2024_collected",
    "rev_q1_2024_marketing_persona",
    "rev_q1_2024_unqualified",
    "rev_q2_2026_net",
    "rev_q4_2025_billed",
    "rev_recognized_by_channel_2025",
    "rev_ytd_growth_2026",
    "sub_active_2025_12_31",
    "sub_active_by_generation_2025_12_31",
    "sub_churn_by_segment_2022",
    "sub_growth_price_paid_2025",
    "sub_new_subscriptions_2025",
    "sub_renewal_rate_2025",
})


def assigned_split(qid: str) -> str:
    """The split the hash rule assigns to a question id."""
    if qid in GRANDFATHERED_DEV:
        return "dev"
    bucket = int(hashlib.sha256(qid.encode()).hexdigest(), 16) / 16 ** 64
    return "dev" if bucket < DEV_SHARE else "holdout"
SPEC_KEYS = {
    "id", "tier", "trap_tag", "prompt", "persona", "pinned_scope", "gold", "gold_sql",
    "trap", "context_required", "split", "provenance", "intent", "status",
}
STATUSES = ("draft", "confirmed")


class SpecError(Exception):
    pass


def bench_config() -> dict:
    modes = yaml.safe_load(MODES_PATH.read_text())
    wh = modes["warehouse"]
    return {
        "bench_version": modes["bench_version"],
        "as_of": str(wh["as_of"]),
        "dataset": f'{wh["project"]}.{wh["dataset"]}',
    }


def load_specs(specs_dir: pathlib.Path) -> list[dict]:
    out = []
    for path in sorted(specs_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        for q in doc["questions"]:
            q = dict(q)
            q["domain"] = doc["domain"]
            q["_file"] = path.name
            out.append(q)
    return out


# --------------------------------------------------------------------------- validation

def validate_spec(q: dict, bench: dict, split: str) -> list[str]:
    """Structural rules a spec must satisfy before anything is derived."""
    errs = []
    qid = q.get("id", "<missing id>")
    extra = set(q) - SPEC_KEYS - {"domain", "_file"}
    if extra:
        errs.append(f"unknown keys {sorted(extra)}")
    for key in ("id", "tier", "trap_tag", "prompt", "intent", "status", "gold", "split", "provenance"):
        if key not in q:
            errs.append(f"missing {key}")
    if errs:
        return [f"{qid}: {e}" for e in errs]
    if not ID_RE.match(q["id"]):
        errs.append("id must be snake_case")
    if q["tier"] not in TIERS:
        errs.append(f"tier {q['tier']!r} not in {TIERS}")
    if q["trap_tag"] not in TRAP_TAGS:
        errs.append(f"trap_tag {q['trap_tag']!r} not in {TRAP_TAGS}")
    if not isinstance(q["intent"], str) or not q["intent"].strip():
        errs.append("intent must say, in words, what the gold measures")
    if q["status"] not in STATUSES:
        errs.append(f"status {q['status']!r} not in {STATUSES}")
    if q["split"] != split:
        errs.append(f"split {q['split']!r} does not match this build ({split!r})")
    if ID_RE.match(q["id"]) and q["split"] != assigned_split(q["id"]):
        errs.append(f"the hash rule assigns this id to {assigned_split(q['id'])!r}, not {q['split']!r} "
                    "(python evals/build_bank.py --which-split <id>)")
    gold = q["gold"]
    kind = gold.get("kind")
    if kind not in GOLD_KINDS:
        errs.append(f"gold.kind {kind!r} not in {GOLD_KINDS}")
    # tier, trap tag and gold kind must tell one story
    if (q["tier"] == "unanswerable") != (q["trap_tag"] == "unanswerable"):
        errs.append("tier unanswerable <=> trap_tag unanswerable")
    if (q["tier"] == "unanswerable") != (kind == "refusal"):
        errs.append("tier unanswerable <=> gold.kind refusal")
    if (q["tier"] == "diagnostic") != (kind == "criteria"):
        errs.append("tier diagnostic <=> gold.kind criteria")
    if kind in ("value", "result_set"):
        if not q.get("gold_sql"):
            errs.append("value and result_set golds need gold_sql (the second derivation)")
        elif "{bench}" not in q["gold_sql"]:
            errs.append("gold_sql must address tables as `{bench}.<table>`")
        if kind == "value" and gold.get("unit") not in UNITS:
            errs.append(f"gold.unit must be one of {UNITS}")
        if kind == "result_set":
            units = gold.get("units") or {}
            if not units or any(u not in UNITS for u in units.values()):
                errs.append("result_set gold needs units: {column: usd|count|ratio} for numeric columns")
    if kind == "criteria":
        if not gold.get("must"):
            errs.append("criteria gold needs a non-empty `must` list")
    if kind == "refusal":
        if not gold.get("reason"):
            errs.append("refusal gold needs a reason")
    if q["trap_tag"] != "none" and not (q.get("trap") or "").strip():
        errs.append("a trapped question documents its plausible-wrong path in `trap`")
    if q["trap_tag"] not in ("none", "unanswerable") and not q.get("context_required"):
        errs.append("a trapped question names the context that resolves it (context_required)")
    for ref in q.get("context_required") or []:
        if not re.match(r"^(shorelane|acf|dbt):", ref):
            errs.append(f"context_required entry {ref!r} must be prefixed shorelane:, acf: or dbt:")
    scope = q.get("pinned_scope") or {}
    window = scope.get("window")
    if window:
        start, end = str(window["start"]), str(window["end"])
        if not start <= end:
            errs.append("window start after end")
        if end > bench["as_of"]:
            errs.append(f"window ends {end}, after the bench as_of {bench['as_of']}")
    if scope.get("at") and str(scope["at"]) > bench["as_of"]:
        errs.append(f"snapshot date {scope['at']} is after the bench as_of {bench['as_of']}")
    prov = q["provenance"]
    if not isinstance(prov, dict) or not prov.get("source"):
        errs.append("provenance.source is required")
    elif "context_seed" in prov:
        errs.append("provenance.context_seed is replaced by the list provenance.context_seeds")
    else:
        seeds = prov.get("context_seeds")
        if not isinstance(seeds, list) or not all(
                isinstance(s, str) and s.endswith(".seed.yaml") and "/" not in s for s in seeds):
            errs.append("provenance.context_seeds must be a list of analytics-context seed file names "
                        "(`[]` once checked against the pinned context and none overlaps)")
    return [f"{qid}: {e}" for e in errs]


# --------------------------------------------------------------------------- derivation

def _params(q: dict, bench: dict, fn) -> dict:
    """Spec params, plus the pinned scope for the parameters the function takes."""
    params = dict(q["gold"].get("derive", {}).get("params") or {})
    scope = q.get("pinned_scope") or {}
    sig = inspect.signature(fn).parameters
    injected = {"as_of": str(scope.get("question_as_of") or bench["as_of"])}
    if scope.get("window"):
        injected.update(start=str(scope["window"]["start"]), end=str(scope["window"]["end"]))
    if scope.get("at"):
        injected["at"] = str(scope["at"])
    for key, val in injected.items():
        if key in sig:
            params.setdefault(key, val)
    return params


def derive(q: dict, tables, bench: dict):
    from evals.bank.derive import DERIVERS

    name = q["gold"].get("derive", {}).get("fn", "refusal" if q["gold"]["kind"] == "refusal" else None)
    if name not in DERIVERS:
        raise SpecError(f"{q['id']}: unknown derivation {name!r}")
    fn = DERIVERS[name]
    return fn(tables, **_params(q, bench, fn))


def _clean(v: Any) -> Any:
    """Plain YAML scalars (numpy ints and floats become Python ones)."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15 and not isinstance(v, bool):
        return v
    return v


def _differs(a: Any, b: Any, tol: float) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.fabs(a - b) > tol
    return a != b


def render_entry(q: dict, d, bench: dict) -> tuple[dict, list[str]]:
    """The bank entry for one spec, plus rule violations found on the derived gold."""
    errs = []
    kind = q["gold"]["kind"]
    gold: dict[str, Any] = {"kind": kind}
    if kind == "value":
        unit = q["gold"]["unit"]
        gold.update(value=_clean(d.value), unit=unit, tolerance=TOLERANCE[unit])
        if q["gold"].get("measure"):
            gold["measure"] = q["gold"]["measure"]
        if d.components:
            gold["components"] = _clean(d.components)
        if d.value is None:
            errs.append("value gold derived no value")
        for label, wrong in d.silent_fail.items():
            if not _differs(wrong, d.value, TOLERANCE[unit]):
                errs.append(f"silent-fail path {label!r} equals the gold: the trap does not bite")
    elif kind == "result_set":
        gold.update(columns=list(d.columns), rows=_clean(d.rows), units=dict(q["gold"]["units"]))
        if not d.rows:
            errs.append("result_set gold derived no rows")
    elif kind == "criteria":
        gold.update(must=list(q["gold"]["must"]), must_not=list(q["gold"].get("must_not") or []),
                    evidence=_clean(d.evidence))
    elif kind == "refusal":
        gold.update(reason=q["gold"]["reason"].strip())
        if q["gold"].get("absent_terms"):
            gold["absent_terms"] = list(q["gold"]["absent_terms"])
    if q["trap_tag"] not in ("none", "unanswerable") and kind in ("value", "result_set") and not d.silent_fail:
        errs.append("a trapped question needs at least one derived silent-fail value")

    scope = {"as_of": bench["as_of"]}
    for key in ("window", "at", "question_as_of"):
        val = (q.get("pinned_scope") or {}).get(key)
        if val:
            scope[key] = {k: str(v) for k, v in val.items()} if isinstance(val, dict) else str(val)
    entry = {
        "id": q["id"],
        "domain": q["domain"],
        "tier": q["tier"],
        "trap_tag": q["trap_tag"],
        "prompt": " ".join(q["prompt"].split()),
        "persona": q.get("persona"),
        "pinned_scope": scope,
        "gold": gold,
        "gold_sql": q["gold_sql"].replace("{bench}", bench["dataset"]).strip() + "\n" if q.get("gold_sql") else None,
        "silent_fail_values": _clean(d.silent_fail),
        "trap": " ".join((q.get("trap") or "").split()) or None,
        "intent": " ".join(q["intent"].split()),
        "status": q["status"],
        "context_required": list(q.get("context_required") or []),
        "split": q["split"],
        "provenance": dict(q["provenance"]),
    }
    return entry, [f"{q['id']}: {e}" for e in errs]


def _comparable(d) -> tuple:
    # Silent-fail values are left out on purpose: they are what a wrong query
    # returns on the snapshot, and some wrong paths (status = 'open') are wrong
    # precisely because they read the snapshot's state.
    return (d.value, d.components, d.columns, d.rows, d.evidence)


def _object_strings(tables: dict) -> dict:
    """Arrow-backed string columns as plain objects. Values are unchanged; pandas'
    Arrow-string isin is ~30x slower, and the derivations call it constantly."""
    import pandas as pd

    out = {}
    for name, df in tables.items():
        df = df.copy()
        for col in df.columns:
            if pd.api.types.is_string_dtype(df[col]) and not pd.api.types.is_object_dtype(df[col]):
                df[col] = df[col].astype(object)
        out[name] = df
    return out


def build(specs_dir: pathlib.Path, split: str, check_future: bool = True) -> tuple[dict, list[str]]:
    from generators import dataset
    from loaders.visibility import visible_tables

    bench = bench_config()
    specs = load_specs(specs_dir)
    errs = []
    seen = set()
    for q in specs:
        errs += validate_spec(q, bench, split)
        if q.get("id") in seen:
            errs.append(f"{q['id']}: duplicate id")
        seen.add(q.get("id"))
    if errs:
        return {}, errs

    full = _object_strings(dataset.generate())
    visible = visible_tables(full, bench["as_of"])
    from evals.bank.derive import schema_columns

    columns = schema_columns(visible)
    entries = []
    for q in specs:
        d = derive(q, visible, bench)
        if check_future and _comparable(d) != _comparable(derive(q, full, bench)):
            errs.append(f"{q['id']}: the gold changes when rows after the bench as_of "
                        f"({bench['as_of']}) are added; the question reads the future")
        entry, e = render_entry(q, d, bench)
        errs += e
        for term in (q["gold"].get("absent_terms") or []):
            hits = sorted(c for c in columns if term.lower() in c)
            if hits:
                errs.append(f"{q['id']}: 'unanswerable' term {term!r} appears in the schema: {hits}")
        entries.append(entry)

    bank = {
        "bank_version": 1,
        "dataset_version": config.DATASET_VERSION,
        "bench_version": bench["bench_version"],
        "warehouse": bench["dataset"],
        "as_of": bench["as_of"],
        "split": split,
        "questions": entries,
    }
    return bank, errs


HEADER = """\
# The Shorelane benchmark question bank ({split} split).
#
# GENERATED by evals/build_bank.py from evals/bank/specs/*.yaml. Do not hand-edit:
# every number below is derived from the generators (evals/bank/derive.py) over
# the tables as the bench warehouse sees them at its as_of. Schema and protocol:
# evals/bank/README.md.
"""


def dump(bank: dict) -> str:
    class Dumper(yaml.SafeDumper):
        pass

    def str_rep(dumper, data):
        style = "|" if "\n" in data else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)

    Dumper.add_representer(str, str_rep)
    body = yaml.dump(bank, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=100)
    return HEADER.format(split=bank["split"]) + "\n" + body


def summarize(bank: dict) -> str:
    from collections import Counter

    qs = bank["questions"]
    tiers = Counter(q["tier"] for q in qs)
    tags = Counter(q["trap_tag"] for q in qs)
    doms = Counter(q["domain"] for q in qs)
    return (f"{len(qs)} questions | tiers {dict(tiers)} | trap tags {dict(tags)} | domains {dict(doms)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--specs", type=pathlib.Path, default=SPECS_DIR)
    ap.add_argument("--split", choices=SPLITS, default="dev")
    ap.add_argument("--out", type=pathlib.Path, default=None)
    ap.add_argument("--check", action="store_true", help="fail if the committed bank is stale or invalid")
    ap.add_argument("--which-split", metavar="ID", help="print the split the hash rule assigns to a question id")
    args = ap.parse_args(argv)
    if args.which_split:
        print(assigned_split(args.which_split))
        return 0
    out = args.out or BANK_DIR / f"{args.split}.yaml"
    if args.split == "holdout" and out.resolve().is_relative_to(REPO_ROOT):
        print("refusing to write a holdout bank inside the public shorelane repo", file=sys.stderr)
        return 2

    bank, errs = build(args.specs, args.split)
    if errs:
        print("bank is invalid:", *errs, sep="\n  ", file=sys.stderr)
        return 1
    text = dump(bank)
    if args.check:
        current = out.read_text() if out.exists() else ""
        if current != text:
            diff = difflib.unified_diff(current.splitlines(), text.splitlines(), str(out), "rebuilt", lineterm="", n=1)
            print(f"{out} is stale; run `python evals/build_bank.py`:", *list(diff)[:60], sep="\n", file=sys.stderr)
            return 1
        print(f"{out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out} is current: {summarize(bank)}")
        return 0
    out.write_text(text)
    print(f"wrote {out}: {summarize(bank)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

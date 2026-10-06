#!/usr/bin/env python3
"""The Shorelane benchmark QA record: its format, and a verifier for it.

A QA record is one benchmark question as a person authors it: the prompt, what it
means, how its gold is derived, the plausible-wrong path it is built around. It
holds no graded numbers; shorelane's evals/build_bank.py derives those. This file
is the single definition of the format: build_bank.py validates every spec with
it, so a record that passes here passes the bank's format rules there.

It is self-contained (Python 3.10+ and PyYAML) so other repos can copy it as is.
A copy is current when its RECORD_FORMAT matches shorelane's.

    python qa_record.py check records/                 # every *.yaml under records/
    python qa_record.py check q.yaml --as-of 2026-08-31 --derive-fns ../shorelane/evals/bank/derive.py
    python qa_record.py which-split mkt_new_metric_2025
    python qa_record.py export records/ --out ../shorelane/evals/bank/specs --split dev

What this checks is the format. What it cannot check without shorelane's
generators: that `gold.derive.fn` produces a gold, that the gold does not read
past the as_of, that every silent-fail path differs from the gold, and that
`gold_sql` reproduces it. `make bank` and `tests/check_bench_golds.py --sql` in
shorelane check those once the record lands there.

Record files may hold one record (a mapping with `id`), a list of records, or a
shorelane spec file (`domain:` plus `questions:`, whose records inherit the domain).
A record outside a spec file carries its own `domain`.

Fields (R = required):

  id                R  snake_case, unique, stable forever (results are keyed on it)
  domain            R  customers | diagnostics | marketing | operations | revenue |
                       subscriptions | unanswerable (others warn: they have no
                       analytics-context mapping yet)
  tier              R  descriptive (a number or table) | diagnostic (why did X move) |
                       unanswerable
  trap_tag          R  the one silent-SQL failure the question is built around:
                       none | ambiguous_definition | definition_outside_schema |
                       as_of_temporal | fanout_cardinality | unanswerable
  prompt            R  exactly what the agent receives
  intent            R  what the asker means, in words: the definition the gold
                       measures. Never shown to the agent
  status            R  draft | confirmed (a person checked intent and gold)
  persona              who is asking (metadata; anything the agent needs is in prompt)
  pinned_scope         {window: {start, end}} | {at: date} | {question_as_of: date};
                       inclusive dates, none after the bench as_of
  gold              R  kind: value | result_set | criteria | refusal
                         value:      unit (usd|count|ratio), derive {fn, params}, measure?
                         result_set: units {column: usd|count|ratio}, derive {fn, params}
                         criteria:   must [..] (non-empty), must_not [..], derive {fn, params}
                         refusal:    reason, absent_terms [..]
  gold_sql             BigQuery SQL over `{bench}.<table>`; required for value and
                       result_set (the second, independent derivation). A value
                       query returns a `value` column plus one per component
  trap                 the plausible-wrong path, in words; required unless trap_tag none
  context_required     artifacts that resolve the trap, prefixed shorelane:, acf: or dbt:;
                       required unless trap_tag is none or unanswerable
  split             R  dev | holdout, and it must be what the hash rule assigns the id
  provenance        R  {source: where it came from, related: a supporting source (optional),
                        context_seeds: [<analytics-context *.seed.yaml names>]}
                       context_seeds is [] once checked and no seed overlaps

The tier, trap tag and gold kind must tell one story: unanswerable <=> trap_tag
unanswerable <=> refusal gold, and diagnostic <=> criteria gold.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import pathlib
import re
import sys
from typing import Any, Iterable

import yaml

# Bump when a rule changes; copies in other repos compare against it.
RECORD_FORMAT = "1.0"

BENCH_AS_OF = "2026-08-31"   # bench v1 warehouse as_of (shorelane bench/modes.yaml)

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
STATUSES = ("draft", "confirmed")
DOMAINS = ("customers", "diagnostics", "marketing", "operations", "revenue", "subscriptions", "unanswerable")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

RECORD_KEYS = {
    "id", "tier", "trap_tag", "prompt", "persona", "pinned_scope", "gold", "gold_sql",
    "trap", "context_required", "split", "provenance", "intent", "status",
}
REQUIRED_KEYS = ("id", "tier", "trap_tag", "prompt", "intent", "status", "gold", "split", "provenance")
GOLD_KEYS = {"kind", "unit", "units", "measure", "derive", "must", "must_not", "reason", "absent_terms"}
SCOPE_KEYS = {"window", "at", "question_as_of"}
PROVENANCE_KEYS = {"source", "related", "context_seeds"}

# Split assignment. A question's split is decided by its id, not by its author:
# sha256(id) lands in dev for the lowest DEV_SHARE of the hash space, holdout for
# the rest. Pick the id BEFORE hashing it, for what the question asks; re-rolling
# ids to steer a question into a split defeats the rule.
DEV_SHARE = 0.40
# Public before the rule was adopted (2026-09-29), so dev whatever their hash.
# Never add to this list.
GRANDFATHERED_DEV = frozenset({
    "cust_current_customers_2025", "cust_multi_channel_2022", "cust_new_customers_q2_2026",
    "diag_aov_drop_2024_09", "diag_consumer_orders_dip_2023_03", "diag_enterprise_churn_2022_q4",
    "diag_new_d2c_drop_2026_02", "diag_subscription_starts_dip_2025",
    "id_customer_count_2025", "id_multi_source_gmv_2024", "id_pre_migration_shopify",
    "mkt_ad_spend_by_platform_2025", "mkt_btb15_usage_2024", "mkt_category_margin_2025",
    "mkt_d2c_cac_h1_2026", "mkt_new_d2c_customers_q1_2026", "mkt_paper_order_gmv_2025",
    "na_email_open_rate_btb", "na_gift_card_revenue_2025", "na_nps_q2_2026",
    "na_revenue_september_2026", "na_store_visits_2025",
    "ops_open_tickets_2026_06_30", "ops_shipments_in_transit_2026_06_30", "ops_tickets_by_category_2025",
    "rev_d2c_gmv_by_year", "rev_five_measures_by_quarter_2025", "rev_fy2025_gmv", "rev_last_quarter",
    "rev_marketplace_take_q2_2026", "rev_orders_q2_2026", "rev_q1_2024_collected",
    "rev_q1_2024_marketing_persona", "rev_q1_2024_unqualified", "rev_q2_2026_net", "rev_q4_2025_billed",
    "rev_recognized_by_channel_2025", "rev_ytd_growth_2026",
    "sub_active_2025_12_31", "sub_active_by_generation_2025_12_31", "sub_churn_by_segment_2022",
    "sub_growth_price_paid_2025", "sub_new_subscriptions_2025", "sub_renewal_rate_2025",
})


def assigned_split(qid: str) -> str:
    """The split the hash rule assigns to a question id."""
    if qid in GRANDFATHERED_DEV:
        return "dev"
    bucket = int(hashlib.sha256(qid.encode()).hexdigest(), 16) / 16 ** 64
    return "dev" if bucket < DEV_SHARE else "holdout"


def _date(v: Any) -> str | None:
    """ISO date string, or None when v is not a date."""
    if isinstance(v, dt.datetime):
        return None
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        try:
            return dt.date.fromisoformat(v).isoformat()
        except ValueError:
            return None
    return None


def _str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)


def validate_record(q: dict, *, as_of: str = BENCH_AS_OF, split: str | None = None,
                    derive_fns: Iterable[str] | None = None) -> list[str]:
    """Format errors for one record, each prefixed with its id. Empty means valid.

    as_of: the bench warehouse as_of no pinned date may pass.
    split: when given, the split being built; a record of the other split is an error.
    derive_fns: when given, the derivation names that exist (shorelane's DERIVERS).
    """
    if not isinstance(q, dict):
        return [f"<record>: a record is a mapping, not {type(q).__name__}"]
    qid = q.get("id", "<missing id>")
    errs: list[str] = []
    extra = set(q) - RECORD_KEYS - {"domain", "_file"}
    if extra:
        errs.append(f"unknown keys {sorted(extra)}")
    errs += [f"missing {k}" for k in REQUIRED_KEYS if k not in q]
    if "domain" not in q:
        errs.append("missing domain (a record outside a spec file names its own)")
    if errs:
        return [f"{qid}: {e}" for e in errs]

    if not isinstance(q["id"], str) or not ID_RE.match(q["id"]):
        errs.append("id must be snake_case")
    if not isinstance(q["domain"], str) or not ID_RE.match(q["domain"]):
        errs.append("domain must be a snake_case name")
    if q["tier"] not in TIERS:
        errs.append(f"tier {q['tier']!r} not in {TIERS}")
    if q["trap_tag"] not in TRAP_TAGS:
        errs.append(f"trap_tag {q['trap_tag']!r} not in {TRAP_TAGS}")
    if not isinstance(q["prompt"], str) or not q["prompt"].strip():
        errs.append("prompt must be non-empty text")
    if not isinstance(q["intent"], str) or not q["intent"].strip():
        errs.append("intent must say, in words, what the gold measures")
    if q["status"] not in STATUSES:
        errs.append(f"status {q['status']!r} not in {STATUSES}")
    if q.get("persona") is not None and not isinstance(q["persona"], str):
        errs.append("persona must be a name or null")

    if q["split"] not in SPLITS:
        errs.append(f"split {q['split']!r} not in {SPLITS}")
    elif split and q["split"] != split:
        errs.append(f"split {q['split']!r} does not match this build ({split!r})")
    if isinstance(q["id"], str) and ID_RE.match(q["id"]) and q["split"] in SPLITS \
            and q["split"] != assigned_split(q["id"]):
        errs.append(f"the hash rule assigns this id to {assigned_split(q['id'])!r}, not {q['split']!r} "
                    "(python qa_record.py which-split <id>)")

    gold = q["gold"]
    if not isinstance(gold, dict):
        return [f"{qid}: {e}" for e in errs + ["gold must be a mapping"]]
    kind = gold.get("kind")
    if kind not in GOLD_KINDS:
        errs.append(f"gold.kind {kind!r} not in {GOLD_KINDS}")
    if set(gold) - GOLD_KEYS:
        errs.append(f"unknown gold keys {sorted(set(gold) - GOLD_KEYS)} (a record holds no graded numbers)")
    # tier, trap tag and gold kind must tell one story
    if (q["tier"] == "unanswerable") != (q["trap_tag"] == "unanswerable"):
        errs.append("tier unanswerable <=> trap_tag unanswerable")
    if (q["tier"] == "unanswerable") != (kind == "refusal"):
        errs.append("tier unanswerable <=> gold.kind refusal")
    if (q["tier"] == "diagnostic") != (kind == "criteria"):
        errs.append("tier diagnostic <=> gold.kind criteria")
    if kind in ("value", "result_set", "criteria"):
        derive = gold.get("derive")
        if not isinstance(derive, dict) or not isinstance(derive.get("fn"), str) or not derive["fn"]:
            errs.append("gold.derive.fn names the derivation that produces the gold")
        else:
            if set(derive) - {"fn", "params"}:
                errs.append(f"unknown gold.derive keys {sorted(set(derive) - {'fn', 'params'})}")
            if derive.get("params") is not None and not isinstance(derive["params"], dict):
                errs.append("gold.derive.params must be a mapping")
            if derive_fns is not None and derive["fn"] not in set(derive_fns):
                errs.append(f"unknown derivation {derive['fn']!r} (add it to shorelane's evals/bank/derive.py)")
    if kind in ("value", "result_set"):
        if not q.get("gold_sql"):
            errs.append("value and result_set golds need gold_sql (the second derivation)")
        elif "{bench}" not in q["gold_sql"]:
            errs.append("gold_sql must address tables as `{bench}.<table>`")
        if kind == "value" and gold.get("unit") not in UNITS:
            errs.append(f"gold.unit must be one of {UNITS}")
        if kind == "result_set":
            units = gold.get("units") or {}
            if not isinstance(units, dict) or not units or any(u not in UNITS for u in units.values()):
                errs.append("result_set gold needs units: {column: usd|count|ratio} for numeric columns")
    if kind == "criteria":
        if not gold.get("must") or not _str_list(gold["must"]):
            errs.append("criteria gold needs a non-empty `must` list")
        if gold.get("must_not") is not None and not _str_list(gold["must_not"]):
            errs.append("gold.must_not must be a list of text")
    if kind == "refusal":
        if not isinstance(gold.get("reason"), str) or not gold["reason"].strip():
            errs.append("refusal gold needs a reason")
        if gold.get("absent_terms") is not None and not _str_list(gold["absent_terms"]):
            errs.append("gold.absent_terms must be a list of terms")

    if q["trap_tag"] != "none" and not (q.get("trap") or "").strip():
        errs.append("a trapped question documents its plausible-wrong path in `trap`")
    if q["trap_tag"] not in ("none", "unanswerable") and not q.get("context_required"):
        errs.append("a trapped question names the context that resolves it (context_required)")
    refs = q.get("context_required") or []
    if not isinstance(refs, list):
        errs.append("context_required must be a list")
    else:
        for ref in refs:
            if not isinstance(ref, str) or not re.match(r"^(shorelane|acf|dbt):", ref):
                errs.append(f"context_required entry {ref!r} must be prefixed shorelane:, acf: or dbt:")

    scope = q.get("pinned_scope") or {}
    if not isinstance(scope, dict):
        errs.append("pinned_scope must be a mapping")
        scope = {}
    if set(scope) - SCOPE_KEYS:
        errs.append(f"unknown pinned_scope keys {sorted(set(scope) - SCOPE_KEYS)}")
    window = scope.get("window")
    if window is not None:
        start, end = (_date(window.get(k)) if isinstance(window, dict) else None for k in ("start", "end"))
        if not start or not end:
            errs.append("pinned_scope.window needs start and end dates (YYYY-MM-DD)")
        else:
            if not start <= end:
                errs.append("window start after end")
            if end > as_of:
                errs.append(f"window ends {end}, after the bench as_of {as_of}")
    for key, what in (("at", "snapshot date"), ("question_as_of", "question as_of")):
        if scope.get(key) is not None:
            d = _date(scope[key])
            if not d:
                errs.append(f"pinned_scope.{key} must be a date (YYYY-MM-DD)")
            elif d > as_of:
                errs.append(f"{what} {d} is after the bench as_of {as_of}")

    prov = q["provenance"]
    if not isinstance(prov, dict) or not prov.get("source"):
        errs.append("provenance.source is required")
    elif "context_seed" in prov:
        errs.append("provenance.context_seed is replaced by the list provenance.context_seeds")
    else:
        if set(prov) - PROVENANCE_KEYS:
            errs.append(f"unknown provenance keys {sorted(set(prov) - PROVENANCE_KEYS)}")
        seeds = prov.get("context_seeds")
        if not isinstance(seeds, list) or not all(
                isinstance(s, str) and s.endswith(".seed.yaml") and "/" not in s for s in seeds):
            errs.append("provenance.context_seeds must be a list of analytics-context seed file names "
                        "(`[]` once checked against the pinned context and none overlaps)")
    return [f"{qid}: {e}" for e in errs]


def validate_records(records: list[dict], **kw) -> list[str]:
    """validate_record over a set, plus the cross-record rule: ids are unique."""
    errs, seen = [], set()
    for q in records:
        errs += validate_record(q, **kw)
        qid = q.get("id") if isinstance(q, dict) else None
        if qid in seen:
            errs.append(f"{qid}: duplicate id")
        seen.add(qid)
    return errs


def warnings(records: list[dict]) -> list[str]:
    out = []
    for q in records:
        if isinstance(q, dict) and q.get("domain") and q["domain"] not in DOMAINS:
            out.append(f"{q.get('id')}: domain {q['domain']!r} is new (known: {', '.join(DOMAINS)}); "
                       "shorelane's seed export maps only known domains")
    return out


# --------------------------------------------------------------------------- files

def load_file(path: pathlib.Path) -> list[dict]:
    """The records in one file: a record, a list of records, or a spec file."""
    doc = yaml.safe_load(path.read_text())
    if isinstance(doc, dict) and "questions" in doc:
        return [{**q, "domain": q.get("domain", doc.get("domain")), "_file": path.name} if isinstance(q, dict)
                else q for q in doc["questions"] or []]
    docs = doc if isinstance(doc, list) else [doc]
    return [{**q, "_file": path.name} if isinstance(q, dict) else q for q in docs]


def load(paths: Iterable[pathlib.Path]) -> list[dict]:
    out = []
    for p in paths:
        files = sorted(p.rglob("*.yaml")) + sorted(p.rglob("*.yml")) if p.is_dir() else [p]
        for f in files:
            out += load_file(f)
    return out


def derive_fns_from(path: pathlib.Path) -> set[str]:
    """The derivation names in shorelane's evals/bank/derive.py, read without importing it."""
    return set(re.findall(r"^@deriver\s*\ndef (\w+)\(", path.read_text(), flags=re.M))


def to_spec_files(records: list[dict]) -> dict[str, dict]:
    """Group records into shorelane spec files: {"<domain>.yaml": {domain, questions}}."""
    out: dict[str, dict] = {}
    for q in records:
        spec = {k: v for k, v in q.items() if k in RECORD_KEYS}
        out.setdefault(f"{q['domain']}.yaml", {"domain": q["domain"], "questions": []})["questions"].append(spec)
    return out


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(str, lambda d, v: d.represent_scalar(
    "tag:yaml.org,2002:str", v, style="|" if "\n" in v else None))


def dump_records(records: list[dict]) -> str:
    """Records as a spec file's `questions:` items: indented, a blank line apart."""
    out = []
    for q in records:
        text = yaml.dump([q], Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
        out.append("".join(f"  {line}" if line.strip() else line for line in text.splitlines(keepends=True)))
    return "\n".join(out)


def export(records: list[dict], out: pathlib.Path, **kw) -> int:
    """Write records into <out>/<domain>.yaml, appending to a spec file that exists.

    Appending keeps the file's comments and existing records untouched. The records
    already in <out> are validated together with the new ones first (ids stay unique,
    and a record already there is an error, not an overwrite)."""
    out.mkdir(parents=True, exist_ok=True)
    existing = load([out]) if any(out.glob("*.yaml")) else []
    errs = validate_records(existing + records, **kw)
    if errs:
        for e in errs:
            print(f"error: {e}", file=sys.stderr)
        return 1
    for name, doc in to_spec_files(records).items():
        target = out / name
        appended = target.exists()
        if appended:
            head = yaml.safe_load(target.read_text()) or {}
            if head.get("domain") != doc["domain"] or "questions" not in head:
                print(f"error: {target} is not the spec file for domain {doc['domain']!r}", file=sys.stderr)
                return 1
            text = target.read_text()
            target.write_text(text.rstrip("\n") + "\n\n" + dump_records(doc["questions"]))
        else:
            target.write_text(f"domain: {doc['domain']}\nquestions:\n\n" + dump_records(doc["questions"]))
        print(f"{'appended to' if appended else 'wrote'} {target}: {len(doc['questions'])} records")
    return 0


# --------------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="verify record files or directories")
    exp = sub.add_parser("export", help="write valid records as shorelane spec files, one per domain")
    for p in (chk, exp):
        p.add_argument("paths", nargs="+", type=pathlib.Path)
        p.add_argument("--as-of", default=BENCH_AS_OF, help=f"bench as_of (default {BENCH_AS_OF})")
        p.add_argument("--split", choices=SPLITS, help="only this split is allowed")
        p.add_argument("--derive-fns", type=pathlib.Path, metavar="DERIVE_PY",
                       help="shorelane's evals/bank/derive.py, to check derivation names")
    exp.add_argument("--out", type=pathlib.Path, required=True, help="directory for <domain>.yaml spec files")
    ws = sub.add_parser("which-split", help="print the split the hash rule assigns to ids")
    ws.add_argument("ids", nargs="+")
    args = ap.parse_args(argv)

    if args.cmd == "which-split":
        for qid in args.ids:
            print(f"{qid}\t{assigned_split(qid)}")
        return 0

    records = load(args.paths)
    fns = derive_fns_from(args.derive_fns) if args.derive_fns else None
    errs = validate_records(records, as_of=args.as_of, split=args.split, derive_fns=fns)
    for w in warnings(records):
        print(f"warning: {w}", file=sys.stderr)
    for e in errs:
        print(f"error: {e}", file=sys.stderr)
    if errs:
        print(f"{len(records)} records, {len(errs)} errors (format {RECORD_FORMAT})", file=sys.stderr)
        return 1
    if args.cmd == "export":
        return export(records, args.out, as_of=args.as_of, split=args.split, derive_fns=fns)
    print(f"{len(records)} records OK (format {RECORD_FORMAT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

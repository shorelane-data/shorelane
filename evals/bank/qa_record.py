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
    python qa_record.py which-split mkt_new_metric_2025 --split-manifest splits.yaml
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
                         value:      unit (usd|count|ratio), derive {fn, params}, measure?,
                                     asked [..]?, accept [..]?
                         result_set: units {column: usd|count|ratio}, derive {fn, params},
                                     asked [..]?, headline?
                         criteria:   must [..] (non-empty), must_not [..], derive {fn, params}
                         refusal:    reason, absent_terms [..], criteria_for_partial?
                       Optional scoring fields (1.2), none of them a number:
                         asked       what the prompt explicitly asks for; only these are graded.
                                     value: gold component names (the headline is always graded);
                                     result_set: column names, label columns included. Without
                                     it every component is supporting and every unit column graded
                         accept      [{path, reason}]: other defensible readings, scored
                                     `acceptable`. `path` names an alternative the derivation
                                     emits (Derived.alternatives); never a typed number
                         headline    result_set: {row: {<label column>: <value>, ..}, column: <unit
                                     column>}, the one cell a single-number answer should equal
                         criteria_for_partial  refusal: {must [..], must_not [..]}. The question is
                                     partly answerable: answers are judged against these criteria
                                     instead of being failed for not refusing
  lint_waive           [{check, reason}]: gold-lint findings the author has reviewed and accepts
  gold_sql             BigQuery SQL over `{bench}.<table>`; required for value and
                       result_set (the second, independent derivation). A value
                       query returns a `value` column plus one per component
  trap                 the plausible-wrong path, in words; required unless trap_tag none
  context_required     artifacts that resolve the trap, prefixed shorelane:, acf: or dbt:;
                       required unless trap_tag is none or unanswerable
  split             R  dev | holdout, and it must match the versioned split manifest
  provenance        R  {source: where it came from, related: a supporting source (optional),
                        context_seeds: [<analytics-context *.seed.yaml names>]}
                       context_seeds is [] once checked and no seed overlaps

The tier, trap tag and gold kind must tell one story: unanswerable <=> trap_tag
unanswerable <=> refusal gold, and diagnostic <=> criteria gold.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys
from typing import Any, Iterable

import yaml

# Bump when a rule changes; copies in other repos compare against it.
RECORD_FORMAT = "1.2"

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
    "trap", "context_required", "split", "provenance", "intent", "status", "lint_waive",
}
REQUIRED_KEYS = ("id", "tier", "trap_tag", "prompt", "intent", "status", "gold", "split", "provenance")
GOLD_KEYS = {"kind", "unit", "units", "measure", "derive", "must", "must_not", "reason", "absent_terms",
             "asked", "accept", "headline", "criteria_for_partial"}
# Which gold kinds may carry each 1.2 scoring field.
SCORING_FIELDS = {"asked": ("value", "result_set"), "accept": ("value",), "headline": ("result_set",),
                  "criteria_for_partial": ("refusal",)}
SCOPE_KEYS = {"window", "at", "question_as_of"}
PROVENANCE_KEYS = {"source", "related", "context_seeds"}

# Split policy v2: development exposure, recorded in a versioned manifest.
# Keep private holdout IDs in the private repository, never in this module.
SPLIT_POLICY = "independent-authoring-v2"


def load_split_manifest(path: pathlib.Path) -> dict[str, str]:
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict) or doc.get("policy") != SPLIT_POLICY:
        raise ValueError(f"{path}: expected split policy {SPLIT_POLICY}")
    assignments = doc.get("assignments")
    if not isinstance(assignments, dict) or not assignments:
        raise ValueError(f"{path}: assignments must be a non-empty mapping")
    for qid, item in assignments.items():
        if not isinstance(qid, str) or not ID_RE.fullmatch(qid):
            raise ValueError(f"{path}: invalid question ID {qid!r}")
        if not isinstance(item, dict) or item.get("split") not in SPLITS or not item.get("reason"):
            raise ValueError(f"{path}: {qid}: split and reason required")
    return {qid: item["split"] for qid, item in assignments.items()}


def assigned_split(qid: str, assignments: dict[str, str]) -> str:
    """Look up an explicit assignment; unknown IDs must be reviewed first."""
    if qid not in assignments:
        raise ValueError(f"{qid}: absent from the split manifest")
    return assignments[qid]


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
                    derive_fns: Iterable[str] | None = None,
                    split_assignments: dict[str, str] | None = None) -> list[str]:
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
    if split_assignments is not None:
        if q["id"] not in split_assignments:
            errs.append("id is absent from the split manifest")
        elif q["split"] != split_assignments[q["id"]]:
            errs.append(f"split {q['split']!r} disagrees with the split manifest "
                        f"({split_assignments[q['id']]!r})")

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

    errs += _scoring_field_errors(gold, kind)
    waive = q.get("lint_waive")
    if waive is not None and not (isinstance(waive, list) and all(
            isinstance(w, dict) and set(w) == {"check", "reason"} and isinstance(w["check"], str)
            and isinstance(w["reason"], str) and w["reason"].strip() for w in waive)):
        errs.append("lint_waive must be a list of {check, reason}, each with a reason")

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


def _scoring_field_errors(gold: dict, kind: Any) -> list[str]:
    """The 1.2 scoring fields: allowed for the gold kind, and well formed."""
    errs = []
    for key, kinds in SCORING_FIELDS.items():
        if key in gold and kind not in kinds:
            errs.append(f"gold.{key} applies only to {' / '.join(kinds)} golds")
    if "asked" in gold and not (_str_list(gold["asked"]) and gold["asked"]):
        errs.append("gold.asked must be a non-empty list of component or column names")
    if kind == "result_set" and _str_list(gold.get("asked")) and isinstance(gold.get("units"), dict) \
            and not set(gold["asked"]) & set(gold["units"]):
        errs.append("gold.asked names no graded (unit) column")
    if "accept" in gold:
        acc = gold["accept"]
        if not isinstance(acc, list) or not acc or not all(
                isinstance(a, dict) and set(a) == {"path", "reason"} and isinstance(a["path"], str)
                and ID_RE.match(a["path"]) and isinstance(a["reason"], str) and a["reason"].strip() for a in acc):
            errs.append("gold.accept must be a list of {path: <derivation alternative>, reason: <why defensible>}")
    if "headline" in gold:
        h = gold["headline"]
        if not (isinstance(h, dict) and set(h) == {"row", "column"} and isinstance(h["row"], dict) and h["row"]
                and isinstance(h["column"], str)):
            errs.append("gold.headline must be {row: {<label column>: <value>}, column: <unit column>}")
        elif isinstance(gold.get("units"), dict) and h["column"] not in gold["units"]:
            errs.append(f"gold.headline.column {h['column']!r} is not a unit column")
    if "criteria_for_partial" in gold:
        c = gold["criteria_for_partial"]
        if not (isinstance(c, dict) and set(c) <= {"must", "must_not"} and c.get("must") and _str_list(c["must"])
                and (c.get("must_not") is None or _str_list(c["must_not"]))):
            errs.append("gold.criteria_for_partial must be {must: [..] (non-empty), must_not: [..]}")
    return errs


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
        p.add_argument("--split-manifest", type=pathlib.Path, required=True)
        p.add_argument("--derive-fns", type=pathlib.Path, metavar="DERIVE_PY",
                       help="shorelane's evals/bank/derive.py, to check derivation names")
    exp.add_argument("--out", type=pathlib.Path, required=True, help="directory for <domain>.yaml spec files")
    ws = sub.add_parser("which-split", help="print the split the manifest assigns to ids")
    ws.add_argument("ids", nargs="+")
    ws.add_argument("--split-manifest", type=pathlib.Path, required=True)
    args = ap.parse_args(argv)

    assignments = load_split_manifest(args.split_manifest)
    if args.cmd == "which-split":
        for qid in args.ids:
            print(f"{qid}\t{assigned_split(qid, assignments)}")
        return 0

    records = load(args.paths)
    fns = derive_fns_from(args.derive_fns) if args.derive_fns else None
    errs = validate_records(records, as_of=args.as_of, split=args.split, derive_fns=fns, split_assignments=assignments)
    for w in warnings(records):
        print(f"warning: {w}", file=sys.stderr)
    for e in errs:
        print(f"error: {e}", file=sys.stderr)
    if errs:
        print(f"{len(records)} records, {len(errs)} errors (format {RECORD_FORMAT})", file=sys.stderr)
        return 1
    if args.cmd == "export":
        return export(records, args.out, as_of=args.as_of, split=args.split, derive_fns=fns, split_assignments=assignments)
    print(f"{len(records)} records OK (format {RECORD_FORMAT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

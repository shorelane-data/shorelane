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
import inspect
import math
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

import config  # noqa: E402

BANK_DIR = REPO_ROOT / "evals" / "bank"
SPECS_DIR = BANK_DIR / "specs"
MODES_PATH = REPO_ROOT / "bench" / "modes.yaml"

# The record format (fields, enums, split rule) lives in evals/bank/qa_record.py,
# a standalone copy-able verifier; this builder adds what needs the generators.
from evals.bank.qa_record import SPLITS, SPLIT_POLICY, assigned_split, load_split_manifest, validate_record  # noqa: E402

# Parity between the two derivations (generators vs gold_sql), not the scorer's
# answer tolerance: the runner compares agent answers at display rounding.
TOLERANCE = {"usd": 0.005, "count": 0, "ratio": 0.0001}


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

def validate_spec(q: dict, bench: dict, split: str, split_assignments=None) -> list[str]:
    """Structural rules a spec must satisfy before anything is derived (qa_record.py)."""
    from evals.bank.derive import DERIVERS

    return validate_record(q, as_of=bench["as_of"], split=split, derive_fns=DERIVERS, split_assignments=split_assignments)


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
        if q["gold"].get("accept"):
            accept, e = _accept(q["gold"]["accept"], d, unit)
            gold["accept"] = accept
            errs += e
    elif kind == "result_set":
        gold.update(columns=list(d.columns), rows=_clean(d.rows), units=dict(q["gold"]["units"]))
        if not d.rows:
            errs.append("result_set gold derived no rows")
        missing = sorted(set(gold["units"]) - set(gold["columns"]))
        if missing:
            errs.append(f"gold.units names columns the derivation does not return: {missing}")
        if q["gold"].get("headline"):
            h = q["gold"]["headline"]
            idx = {c: i for i, c in enumerate(gold["columns"])}
            unknown = sorted(set(h["row"]) - set(idx))
            hits = [] if unknown else [r for r in gold["rows"]
                                       if all(str(r[idx[c]]) == str(v) for c, v in h["row"].items())]
            if unknown:
                errs.append(f"gold.headline.row names unknown columns {unknown}")
            elif len(hits) != 1:
                errs.append(f"gold.headline.row matches {len(hits)} rows; it must pick exactly one")
            gold["headline"] = {"row": dict(h["row"]), "column": h["column"]}
    elif kind == "criteria":
        gold.update(must=list(q["gold"]["must"]), must_not=list(q["gold"].get("must_not") or []),
                    evidence=_clean(d.evidence))
    elif kind == "refusal":
        gold.update(reason=q["gold"]["reason"].strip())
        if q["gold"].get("absent_terms"):
            gold["absent_terms"] = list(q["gold"]["absent_terms"])
        if q["gold"].get("criteria_for_partial"):
            c = q["gold"]["criteria_for_partial"]
            gold["criteria_for_partial"] = {"must": list(c["must"]), "must_not": list(c.get("must_not") or [])}
    if q["gold"].get("asked"):
        asked = list(q["gold"]["asked"])
        known = set(gold.get("components") or {}) if kind == "value" else set(gold.get("columns") or [])
        unknown = sorted(set(asked) - known)
        if unknown:
            what = "components" if kind == "value" else "columns"
            errs.append(f"gold.asked names {what} the derivation does not return: {unknown}")
        gold["asked"] = asked
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


def _accept(accept: list[dict], d, unit: str) -> tuple[list[dict], list[str]]:
    """gold.accept rendered with each alternative's derived value. An accepted reading must
    be an alternative the derivation names, differ from the gold, and never equal a
    silent-fail value: a trap reading can't also be a defensible one."""
    out, errs = [], []
    for a in accept:
        if a["path"] not in d.alternatives:
            errs.append(f"gold.accept path {a['path']!r} is not an alternative the derivation emits "
                        f"({sorted(d.alternatives) or 'none'})")
            continue
        v = d.alternatives[a["path"]]
        if not _differs(v, d.value, TOLERANCE[unit]):
            errs.append(f"gold.accept path {a['path']!r} equals the gold")
        for label, wrong in d.silent_fail.items():
            if not _differs(v, wrong, TOLERANCE[unit]):
                errs.append(f"gold.accept path {a['path']!r} equals silent-fail value {label!r}")
        out.append({"path": a["path"], "value": _clean(v), "reason": " ".join(a["reason"].split())})
    return out, errs


def _comparable(d) -> tuple:
    # Silent-fail values are left out on purpose: they are what a wrong query
    # returns on the snapshot, and some wrong paths (status = 'open') are wrong
    # precisely because they read the snapshot's state.
    return (d.value, d.components, d.columns, d.rows, d.evidence, d.alternatives)


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


def build(specs_dir: pathlib.Path, split: str, check_future: bool = True, split_manifest: pathlib.Path | None = None) -> tuple[dict, list[str]]:
    from generators import dataset
    from loaders.visibility import visible_tables

    bench = bench_config()
    specs = load_specs(specs_dir)
    assignments = load_split_manifest(split_manifest or specs_dir.parent / "splits.yaml")
    errs = []
    seen = set()
    for q in specs:
        errs += validate_spec(q, bench, split, assignments)
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
        "bank_version": 2,
        "split_policy": SPLIT_POLICY,
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
    ap.add_argument("--split-manifest", type=pathlib.Path, default=None)
    ap.add_argument("--which-split", metavar="ID", help="look up an explicit split assignment")
    args = ap.parse_args(argv)
    if args.which_split:
        print(assigned_split(args.which_split, load_split_manifest(args.split_manifest or args.specs.parent / "splits.yaml")))
        return 0
    out = args.out or BANK_DIR / f"{args.split}.yaml"
    if args.split == "holdout" and out.resolve().is_relative_to(REPO_ROOT):
        print("refusing to write a holdout bank inside the public shorelane repo", file=sys.stderr)
        return 2

    bank, errs = build(args.specs, args.split, split_manifest=args.split_manifest)
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

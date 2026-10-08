"""evals/bank/qa_record.py is the bank's record format, standalone and exportable.

1. It runs from a copy outside this repo (python -I, PyYAML only).
2. Every spec passes, and build_bank.py validates with it (one rule set).
3. Each broken record below fails.
4. Records exported into a copy of the specs pass build_bank.py's validation.
"""
import copy
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals import build_bank  # noqa: E402
from evals.bank import qa_record  # noqa: E402
from evals.bank.derive import DERIVERS  # noqa: E402

SPECS = ROOT / "evals" / "bank" / "specs"
NEW = {
    "id": "rev_q3_2025_net",
    "domain": "revenue",
    "tier": "descriptive",
    "trap_tag": "none",
    "prompt": "What was net revenue in Q3 2025?",
    "intent": "Net revenue for Q3 2025.",
    "status": "draft",
    "persona": None,
    "pinned_scope": {"window": {"start": "2025-07-01", "end": "2025-09-30"}},
    "gold": {"kind": "value", "unit": "usd", "derive": {"fn": "revenue_measure", "params": {"measure": "net_revenue"}}},
    "gold_sql": "SELECT ROUND(SUM(amount), 2) AS value FROM `{bench}.fct_revenue`\n"
                "WHERE measure_name = 'net_revenue' AND activity_date BETWEEN '2025-07-01' AND '2025-09-30'\n",
    "context_required": [],
    "split": "dev",
    "provenance": {"source": "authored", "context_seeds": []},
}


def broken(**changes):
    q = copy.deepcopy(NEW)
    for path, val in changes.items():
        *parents, leaf = path.split("__")
        d = q
        for p in parents:
            d = d[p]
        if val is KeyError:
            d.pop(leaf)
        else:
            d[leaf] = val
    return q


CASES = {
    "missing intent": broken(intent=KeyError),
    "missing domain": broken(domain=KeyError),
    "bad status": broken(status="final"),
    "invalid split": broken(split="evaluation"),
    "value gold without gold_sql": broken(gold_sql=KeyError),
    "gold_sql without {bench}": broken(gold_sql="SELECT 1 AS value"),
    "graded number in the record": broken(gold__value=123.0),
    "unknown derivation": broken(gold__derive__fn="no_such_fn"),
    "window after the as_of": broken(pinned_scope__window__end="2026-09-30"),
    "unanswerable tier without a refusal gold": broken(tier="unanswerable", trap_tag="unanswerable"),
    "trap tag without trap text": broken(trap_tag="as_of_temporal", context_required=["acf:domains/x/"]),
    "trap without context_required": broken(trap_tag="as_of_temporal", trap="Uses status today."),
    "context_seeds as a path": broken(provenance__context_seeds=["evals/seeds/revenue.seed.yaml"]),
    "unknown key": broken(gold_value=1),
    # format 1.2 scoring fields
    "accept as a typed number": broken(gold__accept=[{"path": "x", "reason": "r", "value": 5}]),
    "accept without a reason": broken(gold__accept=[{"path": "alt", "reason": " "}]),
    "headline on a value gold": broken(gold__headline={"row": {"q": "2025Q3"}, "column": "x"}),
    "asked empty": broken(gold__asked=[]),
    "criteria_for_partial on a value gold": broken(gold__criteria_for_partial={"must": ["x"]}),
    "lint_waive without a reason": broken(lint_waive=[{"check": "scope_stated"}]),
}

# Well-formed 1.2 fields pass.
VALID_12 = {
    "value with asked and accept": broken(gold__asked=["c"], gold__accept=[{"path": "alt", "reason": "Defensible."}],
                                          lint_waive=[{"check": "scope_stated", "reason": "Checked."}]),
    "result_set with headline": broken(gold={"kind": "result_set", "units": {"share": "ratio"},
                                             "derive": {"fn": "revenue_measure"}, "asked": ["category", "share"],
                                             "headline": {"row": {"category": "paper"}, "column": "share"}}),
    "refusal with criteria_for_partial": broken(
        tier="unanswerable", trap_tag="unanswerable", trap="Fabricates a number.",
        gold={"kind": "refusal", "reason": "No attribution.",
              "criteria_for_partial": {"must": ["Says what cannot be derived"], "must_not": ["Presents X as Y"]}}),
}

failures = []

# 1. standalone: a copy outside the repo, isolated mode
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    shutil.copy(ROOT / "evals" / "bank" / "qa_record.py", tmp / "qa_record.py")
    (tmp / "records").mkdir()
    (tmp / "records" / "new.yaml").write_text(yaml.safe_dump(NEW, sort_keys=False))
    manifest = yaml.safe_load((SPECS.parent / "splits.yaml").read_text())
    manifest["assignments"][NEW["id"]] = {"split": "dev", "reason": "Test fixture"}
    (tmp / "splits.yaml").write_text(yaml.safe_dump(manifest))
    r = subprocess.run([sys.executable, "-I", str(tmp / "qa_record.py"), "check", str(tmp / "records"),
                        str(SPECS), "--split-manifest", str(tmp / "splits.yaml"), "--derive-fns", str(ROOT / "evals" / "bank" / "derive.py")],
                       capture_output=True, text=True, cwd=tmp)
    if r.returncode != 0:
        failures.append(f"standalone copy failed: {r.stderr.strip()}")

# 2. every spec passes, through both entry points
specs = build_bank.load_specs(SPECS)
bench = build_bank.bench_config()
errs = qa_record.validate_records(specs, as_of=bench["as_of"], split="dev", derive_fns=DERIVERS)
errs += [e for q in specs for e in build_bank.validate_spec(q, bench, "dev")]
failures += [f"spec rejected: {e}" for e in errs]
if qa_record.derive_fns_from(ROOT / "evals" / "bank" / "derive.py") != set(DERIVERS):
    failures.append("derive_fns_from does not read every derivation name in derive.py")
if qa_record.BENCH_AS_OF != bench["as_of"]:
    failures.append(f"qa_record.BENCH_AS_OF {qa_record.BENCH_AS_OF} != bench/modes.yaml as_of {bench['as_of']}")

# 3. broken records fail (and the base record passes)
if qa_record.validate_record(NEW, derive_fns=DERIVERS):
    failures.append(f"base record rejected: {qa_record.validate_record(NEW, derive_fns=DERIVERS)}")
for name, q in CASES.items():
    if not qa_record.validate_record(q, derive_fns=DERIVERS):
        failures.append(f"accepted a broken record: {name}")
for name, q in VALID_12.items():
    if qa_record.validate_record(q, derive_fns=DERIVERS):
        failures.append(f"rejected a valid 1.2 record ({name}): {qa_record.validate_record(q, derive_fns=DERIVERS)}")
if not qa_record.validate_records(specs[:1] + [dict(specs[0])]):
    failures.append("accepted a duplicate id")

# 4. export into a copy of the specs; build_bank reads and validates the result
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    out = tmp / "specs"
    shutil.copytree(SPECS, out)
    before = (out / "revenue.yaml").read_text()
    if qa_record.export([dict(NEW)], out, as_of=bench["as_of"], derive_fns=DERIVERS) != 0:
        failures.append("export failed")
    else:
        after = (out / "revenue.yaml").read_text()
        if not after.startswith(before.rstrip("\n")):
            failures.append("export changed existing records or comments in revenue.yaml")
        exported = build_bank.load_specs(out)
        if len(exported) != len(specs) + 1:
            failures.append(f"export: build_bank reads {len(exported)} specs, expected {len(specs) + 1}")
        failures += [f"exported spec rejected: {e}" for q in exported for e in build_bank.validate_spec(q, bench, "dev")]
        if qa_record.export([dict(NEW)], out, as_of=bench["as_of"]) == 0:
            failures.append("export accepted a record whose id is already in the specs")

assignments = {NEW["id"]: "holdout"}
holdout = dict(NEW, split="holdout")
if qa_record.validate_record(holdout, derive_fns=DERIVERS, split_assignments=assignments):
    failures.append("independently authored holdout rejected")
if not qa_record.validate_record(NEW, split_assignments=assignments):
    failures.append("manifest disagreement accepted")
if not qa_record.validate_record(NEW, split_assignments={}):
    failures.append("unassigned question accepted")
try:
    qa_record.assigned_split("unknown", assignments)
    failures.append("unknown split lookup accepted")
except ValueError:
    pass

for f in failures:
    print(f"FAIL {f}")
print("OK" if not failures else f"{len(failures)} failures")
sys.exit(1 if failures else 0)

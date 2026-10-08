"""The 1.2 scoring fields as build_bank.py renders them (no generators needed).

1. gold.accept renders each alternative's derived value; it must be an alternative the
   derivation emits, differ from the gold, and never equal a silent-fail value.
2. gold.asked must name components (value) or columns (result_set) the derivation returns.
3. gold.headline must pick exactly one derived row.
4. criteria_for_partial is carried onto a refusal gold.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals import build_bank  # noqa: E402
from evals.bank.derive import Derived  # noqa: E402

BENCH = {"as_of": "2026-08-31", "dataset": "p.d"}
BASE = {"id": "q", "domain": "revenue", "tier": "descriptive", "trap_tag": "ambiguous_definition",
        "prompt": "p", "intent": "i", "status": "confirmed", "split": "dev", "trap": "t",
        "provenance": {"source": "s", "context_seeds": []}}


def entry(gold: dict, d: Derived, **kw):
    return build_bank.render_entry({**BASE, **kw, "gold": gold}, d, BENCH)


failures = []
d = Derived(value=100, components={"c": 5}, silent_fail={"trap": 120}, alternatives={"alt": 95, "bad": 120})
value = {"kind": "value", "unit": "count", "derive": {"fn": "f"}}

e, errs = entry({**value, "asked": ["c"], "accept": [{"path": "alt", "reason": "A  defensible\nreading."}]}, d)
if errs or e["gold"].get("accept") != [{"path": "alt", "value": 95, "reason": "A defensible reading."}] \
        or e["gold"].get("asked") != ["c"]:
    failures.append(f"accept/asked not rendered: {errs} {e['gold']}")
for path, why in (("bad", "equals silent-fail"), ("missing", "is not an alternative")):
    _, errs = entry({**value, "accept": [{"path": path, "reason": "r"}]}, d)
    if not any(why in x for x in errs):
        failures.append(f"accept {path!r} not rejected ({why}): {errs}")
_, errs = entry({**value, "accept": [{"path": "same", "reason": "r"}]},
                Derived(value=100, silent_fail={"trap": 120}, alternatives={"same": 100}))
if not any("equals the gold" in x for x in errs):
    failures.append("accept equal to the gold not rejected")
_, errs = entry({**value, "asked": ["nope"]}, d)
if not any("asked names components" in x for x in errs):
    failures.append("unknown asked component not rejected")

table = Derived(columns=["category", "share"], rows=[["paper", 0.2], ["ink", 0.1]], silent_fail={"x": 1})
rs = {"kind": "result_set", "units": {"share": "ratio"}, "derive": {"fn": "f"}}
e, errs = entry({**rs, "asked": ["category", "share"], "headline": {"row": {"category": "paper"}, "column": "share"}}, table)
if errs or e["gold"]["headline"] != {"row": {"category": "paper"}, "column": "share"}:
    failures.append(f"headline not rendered: {errs}")
_, errs = entry({**rs, "headline": {"row": {"category": "toner"}, "column": "share"}}, table)
if not any("matches 0 rows" in x for x in errs):
    failures.append("headline matching no row not rejected")
_, errs = entry({**rs, "asked": ["category", "rate"]}, table)
if not any("asked names columns" in x for x in errs):
    failures.append("unknown asked column not rejected")

e, errs = entry({"kind": "refusal", "reason": "r", "criteria_for_partial": {"must": ["m"]}}, Derived(),
                tier="unanswerable", trap_tag="unanswerable")
if e["gold"].get("criteria_for_partial") != {"must": ["m"], "must_not": []}:
    failures.append(f"criteria_for_partial not carried: {e['gold']}")

for f in failures:
    print(f"FAIL {f}")
print("OK" if not failures else f"{len(failures)} failures")
sys.exit(1 if failures else 0)

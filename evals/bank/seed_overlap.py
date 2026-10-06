"""Check which bank questions overlap the analytics-context eval seeds.

A question overlaps a seed when the seed's intent (or must_include) settles the
definition the question's gold rests on: the context author had that decision in
front of them, so lift on the question is not independent of how the context was
written. Overlaps are recorded by hand in each spec as `provenance.context_seeds`
(`[]` once checked and none applies); this tool keeps that record honest.

    python evals/bank/seed_overlap.py --context ../shorelane-analytics-context
    python evals/bank/seed_overlap.py --context ... --specs ../shorelane-bench/bank/specs --suggest

It fails when a question names a seed the context checkout does not have, and warns
when the checkout is not at the context commit pinned in bench/modes.yaml (overlap
is only meaningful against the context under test). `--suggest` lists, for every
question, the most similar seeds by word overlap: a shortlist for a human to judge,
never a decision. Questions without a recorded `context_seeds` always get one.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
STOP = set("""a an and are as at be by did do does for from how in is it its many much of on or our
our that the their this to was we were what when which who why with you your""".split())


def words(*texts: str) -> set[str]:
    return {w for t in texts for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if w not in STOP and len(w) > 2}


def load_questions(bank: pathlib.Path | None, specs: pathlib.Path | None) -> list[dict]:
    if specs:
        out = []
        for path in sorted(specs.glob("*.yaml")):
            doc = yaml.safe_load(path.read_text()) or {}
            out += doc.get("questions", doc) if isinstance(doc, dict) else doc
        return out
    return yaml.safe_load(bank.read_text())["questions"]


def load_seeds(context: pathlib.Path) -> dict[str, dict]:
    return {p.name: yaml.safe_load(p.read_text()) for p in sorted((context / "evals" / "seeds").glob("*.seed.yaml"))}


def pinned_context_commit() -> str | None:
    modes = yaml.safe_load((ROOT / "bench" / "modes.yaml").read_text())
    return (modes.get("sources", {}).get("context") or {}).get("commit")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--context", type=pathlib.Path, required=True, help="shorelane-analytics-context checkout")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--bank", type=pathlib.Path, default=ROOT / "evals" / "bank" / "dev.yaml")
    src.add_argument("--specs", type=pathlib.Path, help="a specs directory instead of a built bank")
    ap.add_argument("--suggest", action="store_true", help="shortlist similar seeds for every question")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args(argv)

    pin = pinned_context_commit()
    head = subprocess.run(["git", "-C", str(args.context), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    if pin and head and head != pin:
        print(f"warning: {args.context} is at {head[:7]}, not the pinned context {pin[:7]}", file=sys.stderr)

    seeds = load_seeds(args.context)
    questions = load_questions(None if args.specs else args.bank, args.specs)
    missing, unrecorded, named = [], [], set()
    for q in questions:
        rec = (q.get("provenance") or {}).get("context_seeds")
        if rec is None:
            unrecorded.append(q["id"])
            continue
        for s in rec:
            (named.add(s) if s in seeds else missing.append((q["id"], s)))

    overlapping = [q for q in questions if (q.get("provenance") or {}).get("context_seeds")]
    print(f"{len(questions)} questions, {len(seeds)} seeds in {args.context}")
    print(f"overlap a seed: {len(overlapping)}; independent: {len(questions) - len(overlapping) - len(unrecorded)}"
          + (f"; not yet checked: {len(unrecorded)}" if unrecorded else ""))
    print(f"seeds named by some question: {len(named)}/{len(seeds)}")
    unnamed = sorted(set(seeds) - named)
    if unnamed:
        print("seeds no question names: " + ", ".join(s.removesuffix(".seed.yaml") for s in unnamed))

    seed_words = {name: words(s.get("question"), s.get("intent"), *((s.get("expected") or {}).get("must_include") or []))
                  for name, s in seeds.items()}
    for q in questions:
        rec = (q.get("provenance") or {}).get("context_seeds")
        if not args.suggest and rec is not None:
            continue
        qw = words(q.get("prompt"), q.get("trap"))
        ranked = sorted(seeds, key=lambda n: -len(qw & seed_words[n]) / (len(qw | seed_words[n]) or 1))[:args.top]
        mark = "not checked" if rec is None else f"recorded {len(rec)}"
        print(f"\n{q['id']} ({mark}): {q.get('prompt', '')[:100]}")
        for n in ranked:
            flag = "*" if rec and n in rec else " "
            print(f"  {flag} {n.removesuffix('.seed.yaml'):45s} {seeds[n].get('question', '')[:80]}")

    for qid, s in missing:
        print(f"error: {qid} names {s}, which {args.context} does not have", file=sys.stderr)
    for qid in unrecorded:
        print(f"error: {qid} has no provenance.context_seeds (record [] once checked)", file=sys.stderr)
    return 1 if missing or unrecorded else 0


if __name__ == "__main__":
    sys.exit(main())

"""Leakage guard for benchmark workspaces.

A benchmark workspace must contain the mode's context and nothing that answers
the questions or changes which agent sees what. Three rules:

1. **No auto-loaded instruction files.** Agents read different files on their own
   (Claude Code: CLAUDE.md; Codex: AGENTS.md; Gemini CLI: GEMINI.md; Cursor:
   .cursorrules). If one landed in a workspace, context would reach some entries
   automatically and others only if they went looking, and the "lift" would partly
   measure file-name conventions. Context is only ever read on purpose.
2. **No evaluation material by path**: ground truth, eval banks and seeds,
   benchmark runs, the reference measures and the parity checks.
3. **No gold values.** Every distinctive number the evals are graded against
   (currency to the cent, and counts >= 1,000) is collected from the committed
   ground truth and eval files and searched for, with and without thousands
   separators, in every text file of the workspace.
"""
from __future__ import annotations

import fnmatch
import pathlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

AUTO_LOADED_INSTRUCTION_FILES = (
    "CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.md",
    "AGENTS.override.md",
    "GEMINI.md",
    ".cursorrules",
    "copilot-instructions.md",
)
AUTO_LOADED_INSTRUCTION_DIRS = (".claude", ".codex", ".gemini", ".cursor", ".github")

FORBIDDEN_PATH_PATTERNS = (
    "*ground_truth*",
    "evals/*",
    "*/evals/*",
    "benchmarks/*",
    "*/benchmarks/*",
    "eval_harness/*",
    "*/eval_harness/*",
    "parity/*",
    "*/parity/*",
    "*measures.py",
)

MIN_INTEGER_GOLD = 1000

_MONEY = re.compile(r"(?<![\d.])\$?(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?!\d)")
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.rule}] {self.detail}"


def _walk_numbers(node: object) -> Iterable[object]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_numbers(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_numbers(value)
    else:
        yield node


def _distinctive(value: object) -> str | None:
    """Canonical text for a gold number, or None when it is too common to police."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        return None
    if dec != dec.to_integral_value():
        # Currency: compared to the cent (4757319.7 and 4,757,319.70 are one value).
        return f"{dec:.2f}" if abs(dec) >= 100 else None
    return str(int(dec)) if abs(dec) >= MIN_INTEGER_GOLD else None


def gold_values(repo_root: pathlib.Path = REPO_ROOT) -> set[str]:
    """Every distinctive graded number committed in this repo's evals and ground truth."""
    golds: set[str] = set()
    for rel in ("evals/questions.yaml", "evals/demo/cases.yaml"):
        path = repo_root / rel
        if path.exists():
            for value in _walk_numbers(yaml.safe_load(path.read_text())):
                canonical = _distinctive(value)
                if canonical:
                    golds.add(canonical)
    for md in sorted((repo_root / "context" / "ground_truth").glob("*.md")):
        for whole, cents in _MONEY.findall(md.read_text()):
            canonical = _distinctive(Decimal(f"{whole.replace(',', '')}.{cents}"))
            if canonical:
                golds.add(canonical)
    return golds


def numbers_in(text: str) -> set[str]:
    """Numbers in `text`, normalized the way gold_values() normalizes them."""
    found: set[str] = set()
    for whole, frac in _NUMBER.findall(text):
        digits = whole.replace(",", "")
        canonical = _distinctive(Decimal(f"{digits}.{frac}") if frac else int(digits))
        if canonical:
            found.add(canonical)
    return found


def check_paths(paths: Iterable[str]) -> list[Finding]:
    findings = []
    for path in paths:
        parts = path.split("/")
        if parts[-1] in AUTO_LOADED_INSTRUCTION_FILES:
            findings.append(Finding(path, "instruction-file", "auto-loaded by some agents"))
        if any(part in AUTO_LOADED_INSTRUCTION_DIRS for part in parts[:-1]):
            findings.append(Finding(path, "instruction-file", "agent configuration directory"))
        for pattern in FORBIDDEN_PATH_PATTERNS:
            if fnmatch.fnmatchcase(path, pattern):
                findings.append(Finding(path, "eval-material", f"matches {pattern}"))
                break
    return findings


def scan_workspace(root: pathlib.Path, golds: set[str]) -> list[Finding]:
    files = sorted(p for p in root.rglob("*") if p.is_file())
    rels = [p.relative_to(root).as_posix() for p in files]
    findings = check_paths(rels)
    for path, rel in zip(files, rels):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for hit in sorted(numbers_in(text) & golds):
            findings.append(Finding(rel, "gold-value", hit))
    return findings

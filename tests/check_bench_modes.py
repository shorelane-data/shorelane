#!/usr/bin/env python3
"""Credential-free checks for the benchmark's three context modes (bench/).

Uses throwaway git repos, so CI needs neither the private shorelane-dbt nor the
analytics-context checkout. It also scans this repo's dbt mirror with the real
gold values: dbt documentation is allowed to say anything EXCEPT the answers.

    python tests/check_bench_modes.py
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from bench import leakage, workspace  # noqa: E402

CONFIG = workspace.load_config()


def git_repo(root: pathlib.Path, files: dict[str, str]) -> str:
    root.mkdir(parents=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


DBT_FILES = {
    "dbt_project.yml": "name: shorelane\n",
    "models/marts/fct_revenue.sql": "select 1 as amount\n",
    "models/marts/_marts.yml": "version: 2\n",
    "macros/money.sql": "{% macro money(c) %}{{ c }}{% endmacro %}\n",
    "tests/fct_revenue_excludes_non_customer_accounts.sql": "select 1 where false\n",
    "tests/check_identity_models.py": "print('ops script, not the dbt project')\n",
    "parity/check_parity.py": "from generators.measures import five_revenues\n",
    "README.md": "prose about the fixture\n",
}
CONTEXT_FILES = {
    "AGENTS.md": "# how to answer\n",
    "README.md": "headline benchmark result\n",
    "company/terminology.md": "revenue means recognized revenue\n",
    "domains/executive-revenue/metrics.yaml": "metrics: []\n",
    "domains/_domain-template/metrics.yaml": "template\n",
    "entities/revenue-subjects.yaml": "entities: []\n",
    "entities/_entity-template.yaml": "template\n",
    "evals/seeds/s01.seed.yaml": "question: revenue?\n",
    "benchmarks/20260915/results.json": "{}\n",
}


class ModesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.dbt_commit = git_repo(self.root / "dbt", DBT_FILES)
        self.ctx_commit = git_repo(self.root / "ctx", CONTEXT_FILES)
        self.readers = {
            "dbt": workspace.GitReader(self.root / "dbt", self.dbt_commit),
            "context": workspace.GitReader(self.root / "ctx", self.ctx_commit),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, mode, readers=None, golds=frozenset()):
        return workspace.build(CONFIG, mode, self.root / "out" / mode, readers or self.readers, set(golds))

    def test_declared_modes_are_the_three_step_ablation(self):
        self.assertEqual(list(CONFIG["modes"]), ["none", "dbt", "dbt_context"])
        self.assertEqual(CONFIG["modes"]["none"]["sources"], [])
        self.assertEqual(CONFIG["modes"]["dbt"]["sources"], ["dbt"])
        self.assertEqual(CONFIG["modes"]["dbt_context"]["sources"], ["dbt", "context"])
        mounts = [s.mount for s in CONFIG["sources"].values()]
        self.assertEqual(len(mounts), len(set(mounts)))

    def test_preamble_is_mode_independent_and_names_no_context(self):
        preamble = CONFIG["preamble"]
        for placeholder in ("{project}", "{dataset}", "{as_of}"):
            self.assertIn(placeholder, preamble)
        for word in ("dbt", "context/", "metric", "definition"):
            self.assertNotIn(word, preamble.lower())

    def test_none_is_empty(self):
        self.assertEqual(self.build("none")["files"], [])

    def test_dbt_mounts_the_project_only(self):
        paths = [f["path"] for f in self.build("dbt")["files"]]
        self.assertEqual(paths, [
            "dbt/dbt_project.yml",
            "dbt/macros/money.sql",
            "dbt/models/marts/_marts.yml",
            "dbt/models/marts/fct_revenue.sql",
            "dbt/tests/fct_revenue_excludes_non_customer_accounts.sql",
        ])

    def test_dbt_context_adds_acf_with_neutral_readme(self):
        manifest = self.build("dbt_context")
        paths = [f["path"] for f in manifest["files"] if f["source"] == "context"]
        self.assertEqual(paths, [
            "context/README.md",
            "context/company/terminology.md",
            "context/domains/executive-revenue/metrics.yaml",
            "context/entities/revenue-subjects.yaml",
        ])
        readme = (self.root / "out" / "dbt_context" / "context" / "README.md").read_text()
        self.assertEqual(readme, CONTEXT_FILES["AGENTS.md"])
        self.assertEqual(
            [(s["name"], s["commit"]) for s in manifest["sources"]],
            [("dbt", self.dbt_commit), ("context", self.ctx_commit)],
        )

    def test_modes_nest(self):
        manifests = {m: self.build(m) for m in CONFIG["modes"]}
        self.assertEqual(workspace.check_ablation(manifests, CONFIG), [])

    def test_ablation_check_catches_a_changed_file(self):
        manifests = {m: self.build(m) for m in CONFIG["modes"]}
        shared = next(f for f in manifests["dbt_context"]["files"] if f["path"].startswith("dbt/"))
        shared["sha256"] = "0" * 64
        self.assertTrue(workspace.check_ablation(manifests, CONFIG))

    def test_pinned_reads_the_commit_not_the_working_tree(self):
        (self.root / "dbt" / "models" / "marts" / "fct_revenue.sql").write_text("-- 4932192.31\n")
        self.build("dbt", golds={"4932192.31"})  # the dirty edit never reaches the workspace

    def test_gold_value_in_documentation_fails_the_build(self):
        commit = git_repo(self.root / "dbt3", {**DBT_FILES, "models/marts/_marts.yml": "description: Q1 was $4,932,192.31\n"})
        readers = {"dbt": workspace.GitReader(self.root / "dbt3", commit)}
        with self.assertRaises(workspace.LeakageError) as ctx:
            self.build("dbt", readers=readers, golds={"4932192.31"})
        self.assertEqual(ctx.exception.findings[0].rule, "gold-value")

    def test_instruction_files_and_eval_material_are_rejected(self):
        found = {(f.path, f.rule) for f in leakage.check_paths([
            "context/AGENTS.md", "dbt/CLAUDE.md", "GEMINI.md", "x/.claude/settings.json",
            "context/evals/seeds/a.yaml", "context/ground_truth.md", "dbt/parity/check.py",
            "dbt/models/marts/fct_revenue.sql",
        ])}
        self.assertEqual(found, {
            ("context/AGENTS.md", "instruction-file"),
            ("dbt/CLAUDE.md", "instruction-file"),
            ("GEMINI.md", "instruction-file"),
            ("x/.claude/settings.json", "instruction-file"),
            ("context/evals/seeds/a.yaml", "eval-material"),
            ("context/ground_truth.md", "eval-material"),
            ("dbt/parity/check.py", "eval-material"),
        })

    def test_unpinned_requires_the_flag(self):
        source = workspace.Source("x", "repo", None, "x", ("**",))
        with self.assertRaisesRegex(workspace.WorkspaceError, "allow-unpinned"):
            workspace.open_source(source, self.root / "dbt", allow_unpinned=False)
        self.assertEqual(workspace.open_source(source, self.root / "dbt", True).revision, self.dbt_commit)

    def test_workspace_must_start_empty(self):
        out = self.root / "out" / "dbt"
        out.mkdir(parents=True)
        (out / "stale.txt").write_text("x")
        with self.assertRaisesRegex(workspace.WorkspaceError, "not empty"):
            self.build("dbt")

    def test_cli_writes_manifest_outside_workspace(self):
        # The committed config pins real commits; point the CLI at a copy pinned
        # to the throwaway repo's commit instead.
        raw = yaml.safe_load(workspace.MODES_PATH.read_text())
        raw["sources"]["dbt"]["commit"] = self.dbt_commit
        config = self.root / "modes.yaml"
        config.write_text(yaml.safe_dump(raw))
        out, manifest = self.root / "ws", self.root / "ws.json"
        rc = workspace.main(["build", "--mode", "dbt", "--out", str(out), "--manifest", str(manifest),
                             "--dbt", str(self.root / "dbt"), "--config", str(config)])
        self.assertEqual(rc, 0)
        data = json.loads(manifest.read_text())
        self.assertEqual(data["mode"], "dbt")
        self.assertEqual(data["sources"][0], {
            "name": "dbt", "repo": raw["sources"]["dbt"]["repo"], "commit": self.dbt_commit, "pinned": True,
        })
        self.assertFalse((out / "ws.json").exists())

    def test_committed_config_is_fully_pinned(self):
        for name, source in CONFIG["sources"].items():
            self.assertRegex(source.commit or "", r"^[0-9a-f]{40}$", f"{name} is not pinned")
        self.assertRegex(CONFIG["warehouse"]["as_of"] or "", r"^\d{4}-\d{2}-\d{2}$")


class GoldValuesTest(unittest.TestCase):
    def test_gold_values_cover_the_eval_answers(self):
        golds = leakage.gold_values()
        for value in ("4932192.31", "4757319.70", "22628", "25733431.14", "91761496.64"):
            self.assertIn(value, golds)

    def test_number_normalization(self):
        self.assertEqual(
            leakage.numbers_in("$4,932,192.31 | 4757319.7 | 22,628 | 2024-01-01 | 0.016626 | v4"),
            {"4932192.31", "4757319.70", "22628", "2024"},
        )

    def test_dbt_mirror_documents_no_answers(self):
        source = CONFIG["sources"]["dbt"]
        reader = workspace.DirReader(REPO_ROOT / "dbt")
        with tempfile.TemporaryDirectory() as tmp:
            workspace.build(CONFIG, "dbt", pathlib.Path(tmp) / "ws", {"dbt": reader})
        self.assertTrue(workspace.select(reader.list_files(), source))


if __name__ == "__main__":
    unittest.main()

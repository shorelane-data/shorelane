#!/usr/bin/env python3
"""Executable contract for the customer-identity eval triple (no pytest).

Run from the repository root:

    python tests/check_identity_eval.py
"""
from __future__ import annotations

import pathlib
import re
import sys
from decimal import Decimal

import yaml

from generators import dataset
from generators.identity_measures import (
    AS_OF,
    GMV_END,
    GMV_START,
    derive_identity_measures,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
QUESTIONS = REPO / "evals" / "questions.yaml"
RUBRIC = REPO / "evals" / "rubrics" / "customer_identity.yml"
GUIDE = REPO / "context" / "guides" / "customer_identity.md"
LOOKML = REPO / "context" / "semantic" / "customer_identity.view.lkml"
GROUND_TRUTH = "context/ground_truth/customer_identity_2021_migration.md"
CONTEXT_REQUIRED = [
    "context/guides/customer_identity.md",
    "context/semantic/customer_identity.view.lkml",
]
QUESTION_IDS = [
    "identity_customer_count_2025",
    "identity_pre_migration_shopify",
    "identity_multi_source_gmv_2024",
]


def _load_yaml(path: pathlib.Path) -> dict:
    assert path.is_file(), f"missing required artifact: {path.relative_to(REPO)}"
    loaded = yaml.safe_load(path.read_text())
    assert isinstance(loaded, dict), f"{path.relative_to(REPO)} must contain a YAML mapping"
    return loaded


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def main() -> int:
    measures = derive_identity_measures(
        dataset.generate(), as_of=AS_OF, gmv_start=GMV_START, gmv_end=GMV_END
    )
    questions_doc = _load_yaml(QUESTIONS)
    questions = {
        question["id"]: question for question in questions_doc.get("questions", [])
    }

    assert questions_doc["dataset_version"] == measures["dataset_version"]
    assert [question_id for question_id in questions if question_id.startswith("identity_")] == QUESTION_IDS

    expected = {
        "identity_customer_count_2025": {
            "canonical_answer": {
                "measure": "ordered_canonical_customer_count",
                "value": measures["ordered_canonical_customer_count"],
                "unresolved_source_id_count": measures["unresolved_source_id_count"],
                "resolution_null_rate": measures["resolution_null_rate"],
            },
            "silent_fail_values": [
                measures["naive_distinct_source_id_count"],
                measures["inner_join_retained_source_id_count"],
                measures["distinct_resolved_canonical_id_count"],
            ],
            "pinned_scope": {"as_of": measures["as_of"]},
        },
        "identity_pre_migration_shopify": {
            "canonical_answer": {
                "measure": "pre_migration_shopify_resolved_count",
                "value": measures["pre_migration_shopify_resolved_count"],
                "missing_count": measures["pre_migration_shopify_missing_count"],
            },
            "silent_fail_values": [
                measures["pre_migration_shopify_observed_count"],
            ],
            "pinned_scope": {
                "migration_cutoff": measures["identity_migration_date"],
                "as_of": measures["as_of"],
            },
        },
        "identity_multi_source_gmv_2024": {
            "canonical_answer": {
                "measure": "correct_multi_source_gmv",
                "value": measures["correct_multi_source_gmv"],
                "order_count": measures["correct_multi_source_order_count"],
                "eligible_canonical_customer_count": measures[
                    "multi_source_canonical_customer_count"
                ],
            },
            "silent_fail_values": [
                measures["unsafe_fanout_gmv"],
            ],
            "pinned_scope": {
                "gmv_start": measures["gmv_start"],
                "gmv_end": measures["gmv_end"],
                "as_of": measures["as_of"],
            },
        },
    }

    for question_id, contract in expected.items():
        assert question_id in questions, f"missing identity eval question: {question_id}"
        question = questions[question_id]
        assert question["ground_truth"] == GROUND_TRUTH
        assert question["context_required"] == CONTEXT_REQUIRED
        assert question["pinned_scope"] == contract["pinned_scope"]
        assert question.get("trap", "").strip(), f"{question_id} must document its trap"
        assert question["silent_fail_values"] == contract["silent_fail_values"]

        answer = question["canonical_answer"]
        assert answer.keys() == contract["canonical_answer"].keys()
        canonical_numbers = {
            _decimal(value)
            for value in answer.values()
            if isinstance(value, (int, float))
        }
        silent_numbers = {_decimal(value) for value in question["silent_fail_values"]}
        assert not canonical_numbers & silent_numbers, (
            f"{question_id}: canonical supporting values must not also be silent fails"
        )
        for key, expected_value in contract["canonical_answer"].items():
            actual_value = answer[key]
            if isinstance(expected_value, float):
                assert _decimal(actual_value) == _decimal(expected_value)
            else:
                assert actual_value == expected_value

    customer_prompt = questions["identity_customer_count_2025"]["prompt"].lower()
    shopify_prompt = questions["identity_pre_migration_shopify"]["prompt"].lower()
    gmv_prompt = questions["identity_multi_source_gmv_2024"]["prompt"].lower()
    assert "end of 2025" in customer_prompt
    assert "pre-migration" in shopify_prompt
    assert "2024" in gmv_prompt
    assert "2025" in gmv_prompt and ("as of" in gmv_prompt or "end of" in gmv_prompt)

    rubric = _load_yaml(RUBRIC)
    assert rubric["rubric"] == "customer_identity_answer"
    assert rubric["applies_to"] == QUESTION_IDS
    criteria = {criterion["id"]: criterion for criterion in rubric["criteria"]}
    assert set(criteria) == {
        "reject_silent_values",
        "correct_grain",
        "unresolved_reporting",
        "no_identity_fanout",
    }
    assert criteria["reject_silent_values"]["type"] == "deterministic"
    for criterion_id in (
        "correct_grain",
        "unresolved_reporting",
        "no_identity_fanout",
    ):
        assert criteria[criterion_id]["type"] == "llm_judge"
        assert criteria[criterion_id].get("judge_prompt", "").strip()
    assert "automatic 0" in criteria["reject_silent_values"]["check"].lower()
    assert "silent_fail_values" in criteria["reject_silent_values"]["check"]
    assert "canonical" in criteria["correct_grain"]["judge_prompt"].lower()
    assert "unresolved" in criteria["unresolved_reporting"]["judge_prompt"].lower()
    assert "fanout" in criteria["no_identity_fanout"]["judge_prompt"].lower()
    assert _decimal(sum(_decimal(c["weight"]) for c in criteria.values())) == Decimal("1")

    assert GUIDE.is_file(), f"missing required artifact: {GUIDE.relative_to(REPO)}"
    guide = GUIDE.read_text().lower()
    guide_rules = [
        "one row per canonical app id",
        "has_order = true",
        "one row per source alias",
        "(source_system, source_customer_id)",
        "nullable app_db_customer_id",
        "never inner join",
        "never guess",
        "sync lag",
        "permanent migration gap",
        "at least two distinct resolved source systems",
        "app_db counts",
        "historical stripe aliases",
        "fan out",
        "deduplicated canonical customer set",
        "fct_identity_resolution_quality",
        "fully elapsed",
        "as of 2025-12-31",
    ]
    for rule in guide_rules:
        assert rule in guide, f"identity guide is missing required safety rule: {rule!r}"

    assert LOOKML.is_file(), f"missing required artifact: {LOOKML.relative_to(REPO)}"
    lookml = LOOKML.read_text()
    view_names = re.findall(r"(?m)^view:\s*([a-zA-Z0-9_]+)\s*\{", lookml)
    assert view_names == ["dim_customers", "fct_identity_resolution_quality"]
    assert "one row per canonical app id" in lookml.lower()
    assert "has_order" in lookml
    assert "resolution_null_rate" in lookml
    for quality_column in (
        "observed_id_count",
        "resolved_id_count",
        "unresolved_id_count",
    ):
        assert f"${{TABLE}}.{quality_column}" in lookml
    assert not re.search(r"(?m)^explore:\s*int_customer_identity\b", lookml)
    assert not re.search(r"(?m)^view:\s*int_customer_identity\b", lookml)
    assert "do not run a looker instance" in lookml.lower()

    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    assert "python tests/check_identity_eval.py" in ci

    print("identity eval triple matches derived metrics and enforces safe identity semantics")
    return 0


if __name__ == "__main__":
    sys.exit(main())

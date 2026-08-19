#!/usr/bin/env python3
"""Verify the reviewed shorelane-dbt artifact mirror.

    python tests/check_dbt_mirror.py [--canonical-root ../shorelane-dbt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MIRROR_ROOT = REPO_ROOT / "dbt"
MANIFEST_PATH = MIRROR_ROOT / "mirror_manifest.json"
CANONICAL_URL = "https://github.com/shorelane-data/shorelane-dbt.git"
CANONICAL_COMMIT = "c8a0a3f69fa10e21ca106bc278f583ab1fb3d771"

EXPECTED_SOURCE_PATHS = (
    "dbt_project.yml",
    "macros/money.sql",
    "models/intermediate/_intermediate.yml",
    "models/intermediate/int_customer_identity.sql",
    "models/marts/_exposures.yml",
    "models/marts/_marts.yml",
    "models/marts/dim_customers.sql",
    "models/marts/fct_identity_resolution_quality.sql",
    "models/marts/fct_revenue.sql",
    "models/staging/_sources.yml",
    "models/staging/_staging.yml",
    "models/staging/stg_app_customers.sql",
    "models/staging/stg_customer_id_crosswalk.sql",
    "models/staging/stg_invoices.sql",
    "models/staging/stg_orders.sql",
    "models/staging/stg_refunds.sql",
    "models/staging/stg_revenue_recognition.sql",
    "models/staging/stg_salesforce_customers.sql",
    "models/staging/stg_shopify_customers.sql",
    "models/staging/stg_stripe_customers.sql",
    "tests/customer_id_crosswalk_integrity.sql",
    "tests/customer_id_crosswalk_no_duplicate_mappings.sql",
    "tests/dim_customers_resolved_system_range.sql",
    "tests/fct_identity_resolution_quality_rate.sql",
    "tests/fct_identity_resolution_quality_reconciliation.sql",
    "tests/int_customer_identity_qualified_key_unique.sql",
    "tests/int_customer_identity_status_consistency.sql",
    "tests/orders_dim_customers_preserves_metrics.sql",
)
EXPECTED_MAPPINGS = tuple(
    (source, f"dbt/{source}") for source in EXPECTED_SOURCE_PATHS
)


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_errors(manifest: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    required = {"canonical_repo_url", "canonical_commit", "files"}
    if set(manifest) != required:
        errors.append(
            f"manifest fields: expected {sorted(required)!r}, got {sorted(manifest)!r}"
        )
    if manifest.get("canonical_repo_url") != CANONICAL_URL:
        errors.append(
            "canonical_repo_url: "
            f"expected {CANONICAL_URL!r}, got {manifest.get('canonical_repo_url')!r}"
        )
    if manifest.get("canonical_commit") != CANONICAL_COMMIT:
        errors.append(
            "canonical_commit: "
            f"expected {CANONICAL_COMMIT!r}, got {manifest.get('canonical_commit')!r}"
        )

    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append("files must be a list")
        return errors
    expected_fields = {"source", "mirror", "sha256"}
    for index, entry in enumerate(files):
        if not isinstance(entry, dict) or set(entry) != expected_fields:
            got = sorted(entry) if isinstance(entry, dict) else type(entry).__name__
            errors.append(
                f"files[{index}] fields: expected {sorted(expected_fields)!r}, got {got!r}"
            )

    valid_entries = [
        entry
        for entry in files
        if isinstance(entry, dict) and set(entry) == expected_fields
    ]
    mappings = [(entry["source"], entry["mirror"]) for entry in valid_entries]
    if mappings != list(EXPECTED_MAPPINGS):
        errors.append(
            "source-to-mirror mappings are incomplete, extra, incorrectly mapped, "
            "or not sorted"
        )
    for entry in valid_entries:
        digest = entry["sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            errors.append(f"invalid SHA256 for {entry['source']!r}: {digest!r}")
    return errors


def _mirrored_file_set_errors() -> list[str]:
    expected = {mirror.removeprefix("dbt/") for _, mirror in EXPECTED_MAPPINGS}
    actual = set()
    if (MIRROR_ROOT / "dbt_project.yml").is_file():
        actual.add("dbt_project.yml")
    for directory in ("models", "macros"):
        root = MIRROR_ROOT / directory
        if root.exists():
            actual.update(
                path.relative_to(MIRROR_ROOT).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
    tests_root = MIRROR_ROOT / "tests"
    if tests_root.exists():
        actual.update(
            path.relative_to(MIRROR_ROOT).as_posix()
            for path in tests_root.rglob("*.sql")
            if path.is_file()
        )

    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    errors = []
    if missing:
        errors.append(f"missing mirrored files: {missing!r}")
    if extra:
        errors.append(f"extra mirrored model/macro/test files: {extra!r}")
    return errors


def _canonical_head(root: pathlib.Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"cannot read canonical checkout HEAD: {detail}")
    return result.stdout.strip()


def check(canonical_root: pathlib.Path | None, allow_dirty_canonical: bool) -> list[str]:
    if not MANIFEST_PATH.is_file():
        return [f"missing manifest: {MANIFEST_PATH.relative_to(REPO_ROOT)}"]
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read manifest: {exc}"]

    errors = _manifest_errors(manifest)
    errors.extend(_mirrored_file_set_errors())
    if errors:
        return errors

    for entry in manifest["files"]:
        local_path = REPO_ROOT / entry["mirror"]
        if not local_path.is_file():
            errors.append(f"missing mirrored file: {entry['mirror']}")
            continue
        actual_hash = sha256(local_path)
        if actual_hash != entry["sha256"]:
            errors.append(
                f"SHA256 mismatch for {entry['mirror']}: "
                f"expected {entry['sha256']}, got {actual_hash}"
            )

    if canonical_root is not None:
        canonical_root = canonical_root.resolve()
        try:
            head = _canonical_head(canonical_root)
        except RuntimeError as exc:
            errors.append(str(exc))
            return errors
        if head != CANONICAL_COMMIT and not allow_dirty_canonical:
            errors.append(
                f"canonical checkout HEAD is {head}, expected {CANONICAL_COMMIT}; "
                "pass --allow-dirty-canonical only for an intentional non-pinned checkout"
            )
        for entry in manifest["files"]:
            source_path = canonical_root / entry["source"]
            local_path = REPO_ROOT / entry["mirror"]
            if not source_path.is_file():
                errors.append(f"canonical source is missing: {entry['source']}")
            elif local_path.is_file() and source_path.read_bytes() != local_path.read_bytes():
                errors.append(f"byte mismatch against canonical: {entry['mirror']}")

        discovered = set()
        project = canonical_root / "dbt_project.yml"
        if project.is_file():
            discovered.add("dbt_project.yml")
        for directory in ("models", "macros"):
            root = canonical_root / directory
            if root.exists():
                discovered.update(
                    path.relative_to(canonical_root).as_posix()
                    for path in root.rglob("*")
                    if path.is_file()
                )
        tests_root = canonical_root / "tests"
        if tests_root.exists():
            discovered.update(
                path.relative_to(canonical_root).as_posix()
                for path in tests_root.rglob("*.sql")
                if path.is_file()
            )
        expected_sources = set(EXPECTED_SOURCE_PATHS)
        if discovered != expected_sources:
            errors.append(
                "canonical checkout file set differs from the pinned mirror contract: "
                f"missing={sorted(expected_sources - discovered)!r}, "
                f"extra={sorted(discovered - expected_sources)!r}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--canonical-root",
        type=pathlib.Path,
        help="optional shorelane-dbt checkout for byte-for-byte comparison",
    )
    parser.add_argument(
        "--allow-dirty-canonical",
        action="store_true",
        help="allow --canonical-root HEAD to differ from the pinned commit",
    )
    args = parser.parse_args()
    if args.allow_dirty_canonical and args.canonical_root is None:
        parser.error("--allow-dirty-canonical requires --canonical-root")

    failures = check(args.canonical_root, args.allow_dirty_canonical)
    if failures:
        print("dbt mirror check FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"dbt mirror matches {CANONICAL_URL}@{CANONICAL_COMMIT} "
        f"({len(EXPECTED_SOURCE_PATHS)} files)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

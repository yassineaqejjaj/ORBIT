"""Versioned wire contract served to FORGE and NOVA (NOV-74): ``contracts/orbit/*.json``.

No service needed. The committed files are the real ``ContextPackage`` / ``Snapshot`` serialised by
``scripts/export_contract_fixtures.py``; FORGE and NOVA keep verified copies (docs/CONTRACTS.md). Changing a
schema without regenerating the fixtures (and refreshing the copies) fails here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from app.schemas.common import CONTEXT_SCHEMA_VERSION
from app.schemas.context import ContextItem, ContextPackage, ExcludedItem
from app.schemas.snapshots import Snapshot, SnapshotItem

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts" / "orbit"
SCRIPT = ROOT / "backend" / "scripts" / "export_contract_fixtures.py"

#: Frozen key sets of the contract version below. Adding a key is allowed (bump the list, regenerate the
#: fixtures, refresh the FORGE / NOVA copies, add a row to docs/CONTRACTS.md); renaming or removing one is not.
FROZEN_SCHEMA_VERSION = 2
FROZEN_ITEM_KEYS = {
    "citation", "candidate_type", "id", "document_id", "memory_item_id", "title", "source_kind", "memory_kind",
    "memory_scope", "uri", "version", "excerpt", "tokens", "scores", "classification", "access_scope", "date",
    "pii_redacted", "reason_code", "reason_detail",
}  # fmt: skip
FROZEN_EXCLUDED_KEYS = {
    "candidate_type", "id", "title", "excerpt", "source_kind", "memory_kind", "classification", "scores",
    "reason_code", "reason_detail", "redacted", "related_citation",
}  # fmt: skip
FROZEN_PACKAGE_KEYS = {
    "schema_version", "request_id", "trace_id", "task", "intent", "created_at", "context", "items", "excluded",
    "exclusion_summary", "tokens_used", "token_budget", "candidates_count", "timings", "snapshot", "config",
    "warnings", "cache_prefix_hash", "cache_prefix_tokens", "cache_prefix_reused", "cache_hints", "mode", "index",
    "profile", "sufficiency", "max_classification", "orion_project_id",
}  # fmt: skip
FROZEN_SNAPSHOT_ITEM_KEYS = {
    "key", "citation", "candidate_type", "id", "title", "excerpt", "source_kind", "memory_kind", "version",
    "forgotten", "classification",
}  # fmt: skip
FROZEN_SNAPSHOT_KEYS = {
    "schema_version", "id", "name", "version", "parent_version", "task", "intent", "token_count", "items_count",
    "content_hash", "created_by_label", "created_at", "content", "items", "request_id", "max_classification",
    "orion_project_id",
}  # fmt: skip


def load(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def exporter() -> Any:
    spec = importlib.util.spec_from_file_location("export_contract_fixtures", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixtures_are_what_the_current_schemas_serialise(exporter: Any) -> None:
    """Fails when a schema changes (or a fixture is hand-edited) without re-running the export script."""
    expected = exporter.build()
    committed = {p.name for p in CONTRACTS.glob("*.json")}
    assert committed == set(expected), (
        "contracts/orbit holds files the export script does not produce (or lacks some)"
    )
    for name, text in expected.items():
        assert (CONTRACTS / name).read_text(encoding="utf-8") == text, (
            f"contracts/orbit/{name} is stale: run `uv run python scripts/export_contract_fixtures.py`, "
            "then refresh the copies in FORGE and NOVA (docs/CONTRACTS.md)"
        )


def test_the_manifest_pins_every_fixture_by_hash() -> None:
    manifest = load("manifest.json")
    assert manifest["contract"] == "orbit-context" and manifest["schema_version"] == CONTEXT_SCHEMA_VERSION
    names = {p.name for p in CONTRACTS.glob("*.json")} - {"manifest.json"}
    assert set(manifest["files"]) == names
    for name, entry in manifest["files"].items():
        assert hashlib.sha256((CONTRACTS / name).read_bytes()).hexdigest() == entry["sha256"], name


def test_the_contract_version_is_the_frozen_one() -> None:
    """A new ``schema_version`` is a deliberate act: update FROZEN_* here and the compatibility matrix."""
    assert CONTEXT_SCHEMA_VERSION == FROZEN_SCHEMA_VERSION
    for name in ("context_package.json", "context_package_limited_rights.json", "snapshot.json"):
        assert load(name)["schema_version"] == FROZEN_SCHEMA_VERSION


def test_the_schemas_expose_exactly_the_frozen_keys() -> None:
    assert set(ContextItem.model_fields) == FROZEN_ITEM_KEYS
    assert set(ExcludedItem.model_fields) == FROZEN_EXCLUDED_KEYS
    assert set(ContextPackage.model_fields) == FROZEN_PACKAGE_KEYS
    assert set(SnapshotItem.model_fields) == FROZEN_SNAPSHOT_ITEM_KEYS
    assert set(Snapshot.model_fields) == FROZEN_SNAPSHOT_KEYS


def test_the_fixtures_carry_exactly_the_frozen_keys() -> None:
    for name in ("context_package.json", "context_package_limited_rights.json"):
        package = load(name)
        assert set(package) == FROZEN_PACKAGE_KEYS, name
        assert package["items"] and all(set(item) == FROZEN_ITEM_KEYS for item in package["items"]), name
        assert package["excluded"] and all(
            set(item) == FROZEN_EXCLUDED_KEYS for item in package["excluded"]
        ), name
    snapshot = load("snapshot.json")
    assert set(snapshot) == FROZEN_SNAPSHOT_KEYS
    assert all(set(item) == FROZEN_SNAPSHOT_ITEM_KEYS for item in snapshot["items"])


def test_the_fixtures_validate_against_the_real_schemas() -> None:
    for name in ("context_package.json", "context_package_limited_rights.json"):
        assert ContextPackage.model_validate(load(name)).items
    assert Snapshot.model_validate(load("snapshot.json")).items


def test_the_mandatory_scenarios_are_present() -> None:
    package = load("context_package.json")
    levels = {item["classification"] for item in package["items"]}
    assert {1, 2, 3} <= levels and package["max_classification"] == 3  # real context with a C3 item
    assert all(item["excerpt"].strip() for item in package["items"])
    assert any(item["access_scope"] == "restricted" for item in package["items"])
    assert all(
        e["redacted"] and e["excerpt"] is None for e in package["excluded"]
    )  # nothing leaks from hidden items

    limited = load("context_package_limited_rights.json")
    assert [item["classification"] for item in limited["items"]] == [1] and limited["max_classification"] == 1
    assert {e["reason_code"] for e in limited["excluded"]} >= {"EXCLUDED_ACL", "EXCLUDED_CLASSIFICATION"}
    assert "120 EUR" not in json.dumps(limited, ensure_ascii=False)  # no C3 text served to a C1 reader

    snapshot = load("snapshot.json")
    forgotten = [item for item in snapshot["items"] if item["forgotten"]]
    assert len(forgotten) == 1 and forgotten[0]["excerpt"] == "[contenu oublié]"
    assert "contenu oublié" not in snapshot["content"] and snapshot["max_classification"] == 3
    assert any(item["classification"] == 3 for item in snapshot["items"] if not item["forgotten"])

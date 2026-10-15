"""Context / snapshot wire contract (NOV-73): changes are additive, NOVA and FORGE read the old keys."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.enums import CandidateType, Intent, MemoryKind, MemoryScope, ReasonCode, SourceKind
from app.schemas.context import (
    CONTEXT_SCHEMA_VERSION,
    ContextConfig,
    ContextItem,
    ContextPackage,
    ContextTimings,
    Scores,
)
from app.schemas.snapshots import Snapshot, SnapshotItem

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)

#: Keys served before NOV-73 (scratchpad/o3_serialize.py): none may be renamed or removed.
LEGACY_PACKAGE_KEYS = {
    "request_id", "trace_id", "task", "intent", "created_at", "context", "items", "excluded",
    "exclusion_summary", "tokens_used", "token_budget", "candidates_count", "timings", "snapshot",
    "config", "warnings", "cache_prefix_hash", "cache_prefix_tokens", "cache_prefix_reused",
    "cache_hints", "mode", "index", "profile", "sufficiency",
}  # fmt: skip
LEGACY_ITEM_KEYS = {
    "citation", "candidate_type", "id", "document_id", "memory_item_id", "title", "source_kind",
    "memory_kind", "memory_scope", "uri", "version", "excerpt", "tokens", "scores", "classification",
    "date", "pii_redacted", "reason_code", "reason_detail",
}  # fmt: skip
LEGACY_SNAPSHOT_ITEM_KEYS = {
    "key", "citation", "candidate_type", "id", "title", "excerpt", "source_kind", "memory_kind",
    "version", "forgotten",
}  # fmt: skip
LEGACY_SNAPSHOT_KEYS = {
    "id", "name", "version", "parent_version", "task", "intent", "token_count", "items_count",
    "content_hash", "created_by_label", "created_at", "content", "items", "request_id",
}  # fmt: skip


def _item(**overrides: object) -> ContextItem:
    base: dict[str, object] = {
        "citation": "S1",
        "candidate_type": CandidateType.memory,
        "id": str(uuid.uuid4()),
        "title": "Décision synthétique",
        "memory_kind": MemoryKind.decision,
        "memory_scope": MemoryScope.project,
        "excerpt": "Texte synthétique",
        "tokens": 2,
        "scores": Scores(final=0.5),
        "classification": 2,
        "reason_code": ReasonCode.INCLUDED_RELEVANT,
    }
    return ContextItem(**{**base, **overrides})  # type: ignore[arg-type]


def test_context_package_only_adds_keys() -> None:
    package = ContextPackage(
        request_id=uuid.uuid4(),
        trace_id="t" * 32,
        task="t",
        intent=Intent.general,
        created_at=NOW,
        context="## ...",
        items=[_item(access_scope="project")],
        excluded=[],
        exclusion_summary={},
        tokens_used=2,
        token_budget=4000,
        candidates_count=1,
        timings=ContextTimings(),
        config=ContextConfig(reranker="heuristic", embedding_model="m"),
        max_classification=2,
    )
    data = package.model_dump(mode="json")
    assert set(data) >= LEGACY_PACKAGE_KEYS
    assert set(data) - LEGACY_PACKAGE_KEYS == {"max_classification", "schema_version"}
    assert data["schema_version"] == CONTEXT_SCHEMA_VERSION == 2
    assert set(data["items"][0]) >= LEGACY_ITEM_KEYS
    assert set(data["items"][0]) - LEGACY_ITEM_KEYS == {"access_scope"}
    assert not any("acl" in key for key in data["items"][0])  # never the raw ACL entries


def test_old_payloads_still_validate() -> None:
    """A stored or remote payload without the new keys loads with safe defaults."""
    item = _item().model_dump(mode="json")
    item.pop("access_scope")
    assert ContextItem.model_validate(item).access_scope is None
    legacy_snapshot_item = {
        "key": f"chunk:{uuid.uuid4()}",
        "citation": "S1",
        "candidate_type": "chunk",
        "id": str(uuid.uuid4()),
        "title": "t",
        "excerpt": "e",
    }
    assert SnapshotItem.model_validate(legacy_snapshot_item).classification is None


def test_snapshot_only_adds_keys() -> None:
    item = SnapshotItem(
        key="chunk:1",
        citation="S1",
        candidate_type=CandidateType.chunk,
        id="1",
        title="t",
        excerpt="e",
        source_kind=SourceKind.document,
        classification=1,
    )
    snapshot = Snapshot(
        id=uuid.uuid4(),
        name="n",
        version=1,
        task="t",
        intent=Intent.general,
        token_count=1,
        content_hash="h",
        created_at=NOW,
        content="c",
        items=[item],
        request_id=None,
        max_classification=1,
    )
    data = snapshot.model_dump(mode="json")
    assert set(data) >= LEGACY_SNAPSHOT_KEYS
    assert set(data) - LEGACY_SNAPSHOT_KEYS == {"max_classification", "schema_version"}
    assert set(data["items"][0]) >= LEGACY_SNAPSHOT_ITEM_KEYS
    assert set(data["items"][0]) - LEGACY_SNAPSHOT_ITEM_KEYS == {"classification"}

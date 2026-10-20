"""Serialise the ORBIT context contract (NOV-74): real ContextPackage / Snapshot to ``contracts/orbit/``.

    uv run python scripts/export_contract_fixtures.py          # rewrite contracts/orbit/*.json
    uv run python scripts/export_contract_fixtures.py --check  # exit 1 when the committed files are stale

The files are the **source** of the contract that FORGE and NOVA copy (see docs/CONTRACTS.md): synthetic
content only, deterministic output (fixed ids and dates), built with the real Pydantic schemas and
``model_dump(mode="json")``. A schema change makes ``tests/test_contract_fixtures.py`` fail until this script
is re-run and the copies in FORGE / NOVA are refreshed. Never edit the JSON by hand.

Scenarios covered: real context (C1 + C2 + C3, ACL exclusion), limited rights (the reader sees C1 only),
snapshot with a C3 item and a forgotten item.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.enums import (  # noqa: E402
    AccessScope,
    CandidateType,
    Intent,
    MemoryKind,
    MemoryScope,
    ReasonCode,
    SourceKind,
)
from app.schemas.common import CONTEXT_SCHEMA_VERSION  # noqa: E402
from app.schemas.context import (  # noqa: E402
    ContextConfig,
    ContextItem,
    ContextPackage,
    ContextSnapshotInfo,
    ContextTimings,
    ExcludedItem,
    Scores,
)
from app.schemas.snapshots import Snapshot, SnapshotItem  # noqa: E402

CONTRACTS_DIR = BACKEND.parent / "contracts" / "orbit"
MANIFEST = "manifest.json"
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
REQUEST_ID = uuid.UUID("9a9a9a9a-0000-4000-8000-000000000001")
SNAPSHOT_ID = uuid.UUID("d0d62e58-0010-4373-9403-7c6a253b3383")
#: Id shared by the ORION services for the synthetic project (``orion_project_id``, NOV-106, additive).
ORION_PROJECT_ID = uuid.UUID("0a0b0c0d-0000-4000-8000-000000000106")


def _uuid(n: int) -> uuid.UUID:
    return uuid.UUID(f"60b7e3f2-0000-4000-8000-{n:012d}")


def _scores(final: float) -> Scores:
    return Scores(final=final)


def _items() -> list[ContextItem]:
    return [
        ContextItem(
            citation="S1",
            candidate_type=CandidateType.chunk,
            id="3bc8be0b-0000-4000-8000-000000000001",
            document_id=_uuid(1),
            title="Note client",
            source_kind=SourceKind.document,
            uri="orbit://synthetic/note-client",
            version=2,
            excerpt="Le client veut un export CSV hebdomadaire.",
            tokens=3,
            scores=_scores(0.8),
            classification=1,
            access_scope=AccessScope.public,
            date=NOW,
            reason_code=ReasonCode.INCLUDED_RELEVANT,
        ),
        ContextItem(
            citation="S2",
            candidate_type=CandidateType.memory,
            id="8bead5e8-0000-4000-8000-000000000002",
            memory_item_id=_uuid(2),
            title="Décision export",
            memory_kind=MemoryKind.decision,
            memory_scope=MemoryScope.project,
            version=1,
            excerpt="Décision : export CSV le lundi.",
            tokens=2,
            scores=_scores(0.5),
            classification=2,
            access_scope=AccessScope.project,
            reason_code=ReasonCode.INCLUDED_RELEVANT,
        ),
        ContextItem(
            citation="S3",
            candidate_type=CandidateType.chunk,
            id="3bc8be0b-0000-4000-8000-000000000003",
            document_id=_uuid(3),
            title="Grille tarifaire [C3 synthétique]",
            source_kind=SourceKind.document,
            uri="orbit://synthetic/grille-tarifaire",
            version=4,
            excerpt="Le prix plancher synthétique est de 120 EUR.",
            tokens=3,
            scores=_scores(0.8),
            classification=3,
            access_scope=AccessScope.restricted,
            date=NOW,
            reason_code=ReasonCode.INCLUDED_RELEVANT,
        ),
    ]


def _package(
    items: list[ContextItem], excluded: list[ExcludedItem], summary: dict[ReasonCode, int]
) -> ContextPackage:
    text = "\n".join(f"[{i.citation}] {i.excerpt}" for i in items)
    return ContextPackage(
        request_id=REQUEST_ID,
        trace_id="t" * 32,
        task="Préparer l'atelier de cadrage",
        intent=Intent.general,
        created_at=NOW,
        context=text,
        items=items,
        excluded=excluded,
        exclusion_summary=summary,
        tokens_used=sum(i.tokens for i in items),
        token_budget=4000,
        candidates_count=len(items) + len(excluded),
        timings=ContextTimings(),
        snapshot=ContextSnapshotInfo(id=SNAPSHOT_ID, name="discovery", version=7),
        config=ContextConfig(reranker="heuristic", embedding_model="synthetic-hash"),
        max_classification=max((i.classification for i in items), default=0),
        orion_project_id=ORION_PROJECT_ID,
    )


def context_package() -> ContextPackage:
    """A reader who may see everything: C1 + C2 + C3, plus one item hidden by an ACL (redacted)."""
    hidden = ExcludedItem(
        candidate_type=CandidateType.chunk, reason_code=ReasonCode.EXCLUDED_ACL, redacted=True
    )
    return _package(_items(), [hidden], {ReasonCode.EXCLUDED_ACL: 1})


def context_package_limited_rights() -> ContextPackage:
    """A reader with limited rights: only the C1 item is served, the C2/C3 ones are hidden and redacted."""
    hidden = [
        ExcludedItem(candidate_type=CandidateType.memory, reason_code=ReasonCode.EXCLUDED_ACL, redacted=True),
        ExcludedItem(
            candidate_type=CandidateType.chunk, reason_code=ReasonCode.EXCLUDED_CLASSIFICATION, redacted=True
        ),
    ]
    summary = {ReasonCode.EXCLUDED_ACL: 1, ReasonCode.EXCLUDED_CLASSIFICATION: 1}
    return _package(_items()[:1], hidden, summary)


def snapshot() -> Snapshot:
    """Snapshot v7: C1, C2 and C3 passages, plus an item forgotten since (content removed)."""
    items = [
        SnapshotItem(
            key="chunk:c1",
            citation="S1",
            candidate_type=CandidateType.chunk,
            id="c1",
            title="Note client",
            excerpt="Le client veut un export CSV hebdomadaire.",
            source_kind=SourceKind.document,
            version=3,
            classification=1,
        ),
        SnapshotItem(
            key="memory:m1",
            citation="S2",
            candidate_type=CandidateType.memory,
            id="m1",
            title="Décision export",
            excerpt="Décision : export CSV le lundi.",
            memory_kind=MemoryKind.decision,
            version=1,
            classification=2,
        ),
        SnapshotItem(
            key="chunk:c3",
            citation="S3",
            candidate_type=CandidateType.chunk,
            id="c3",
            title="Grille tarifaire [C3 synthétique]",
            excerpt="Le prix plancher synthétique est de 120 EUR.",
            source_kind=SourceKind.document,
            version=4,
            classification=3,
        ),
        SnapshotItem(
            key="chunk:c2",
            citation="S4",
            candidate_type=CandidateType.chunk,
            id="c2",
            title="Contenu retiré",
            excerpt="[contenu oublié]",
            source_kind=SourceKind.document,
            version=1,
            forgotten=True,
            classification=1,
        ),
    ]
    return Snapshot(
        id=_uuid(7),
        name="discovery",
        version=7,
        parent_version=6,
        task="Préparer l'atelier de cadrage",
        intent=Intent.general,
        token_count=42,
        items_count=len(items),
        content_hash="sha256:" + "ab" * 32,
        created_by_label="agent",
        created_at=NOW,
        content="\n".join(f"[{i.citation}] {i.excerpt}" for i in items if not i.forgotten),
        items=items,
        request_id=REQUEST_ID,
        max_classification=3,
        orion_project_id=ORION_PROJECT_ID,
    )


def render(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build() -> dict[str, str]:
    """``{file name: content}`` of the whole contract directory, manifest included."""
    files = {
        "context_package.json": render(context_package()),
        "context_package_limited_rights.json": render(context_package_limited_rights()),
        "snapshot.json": render(snapshot()),
    }
    manifest = {
        "contract": "orbit-context",
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "source": "ORBIT backend/scripts/export_contract_fixtures.py (real Pydantic schemas, synthetic data)",
        "files": {name: {"sha256": sha256(text)} for name, text in sorted(files.items())},
    }
    files[MANIFEST] = json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"
    return files


def main(argv: list[str]) -> int:
    expected = build()
    if "--check" in argv:
        stale = [
            name
            for name, text in expected.items()
            if not (CONTRACTS_DIR / name).is_file()
            or (CONTRACTS_DIR / name).read_text(encoding="utf-8") != text
        ]
        if stale:
            print(f"contracts/orbit is stale ({', '.join(stale)}): run scripts/export_contract_fixtures.py")
            return 1
        print("contracts/orbit is up to date")
        return 0
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in expected.items():
        (CONTRACTS_DIR / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(expected)} files to {CONTRACTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Memory lifecycle (ARCHITECTURE §8): supersession, contradiction, versioning, forgetting, maintenance."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import (
    DocumentStatus,
    MemoryEventType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RelationType,
    SourceKind,
)
from app.memory import lifecycle
from app.models import Chunk, Document, MemoryEvent, MemoryItem, Relation, Source
from app.schemas.memory import MemoryIn, ProvenanceIn
from app.services.audit import Actor
from tests.conftest import UserInfo

SYSTEM = Actor.system()


def _decision(title: str, content: str, days_ago: int, status: str = "validated") -> MemoryIn:
    return MemoryIn(
        scope=MemoryScope.project,
        kind=MemoryKind.decision,
        title=title,
        content=content,
        status=status,  # type: ignore[arg-type]
        valid_from=utcnow() - timedelta(days=days_ago),
    )


async def _events(session: AsyncSession, item: MemoryItem) -> list[MemoryEventType]:
    rows = await session.scalars(select(MemoryEvent.event).where(MemoryEvent.lineage_id == item.lineage_id))
    return [MemoryEventType(e) for e in rows]


async def _document(session: AsyncSession, project_id: uuid.UUID, title: str) -> tuple[Document, Chunk]:
    source = await session.scalar(select(Source).where(Source.project_id == project_id))
    if source is None:
        source = Source(project_id=project_id, name="Comptes rendus", kind=SourceKind.note)
        session.add(source)
        await session.flush()
    document = Document(
        project_id=project_id,
        source_id=source.id,
        title=title,
        classification=1,
        acl_principals=["project:*"],
        source_updated_at=utcnow() - timedelta(days=10),
    )
    session.add(document)
    await session.flush()
    text = f"{title} : Le site de Lyon compte 720 postes."
    chunk = Chunk(
        project_id=project_id,
        document_id=document.id,
        version=1,
        ordinal=0,
        text=text,
        text_redacted=text,
        classification=1,
        acl_principals=["project:*"],
    )
    session.add(chunk)
    await session.flush()
    return document, chunk


async def test_decision_native_superseded_by_pwa(
    db_session: AsyncSession, project: dict[str, object]
) -> None:
    project_id = uuid.UUID(str(project["id"]))
    native = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=_decision(
            "Application mobile native iOS/Android", "Décision : application mobile native iOS/Android.", 56
        ),
        actor=SYSTEM,
    )
    pwa = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=_decision(
            "L'application sera une PWA",
            "Décision : l'application sera une PWA plutôt qu'une application native.",
            35,
        ),
        actor=SYSTEM,
    )
    await db_session.commit()
    assert native.status == MemoryStatus.superseded
    assert native.superseded_by_id == pwa.id
    assert pwa.supersedes_id == native.id
    assert pwa.status == MemoryStatus.validated
    relation = await db_session.scalar(
        select(Relation).where(Relation.src_id == pwa.id, Relation.dst_id == native.id)
    )
    assert relation is not None and relation.rel_type == RelationType.supersedes
    assert MemoryEventType.superseded in await _events(db_session, native)
    assert MemoryEventType.superseded in await _events(db_session, pwa)

    restored = await lifecycle.restore(db_session, native, SYSTEM, "Retour arrière pour la démo")
    await db_session.commit()
    assert restored.status == MemoryStatus.validated
    assert restored.superseded_by_id is None
    assert MemoryEventType.restored in await _events(db_session, native)


async def test_contradiction_720_vs_650_postes(db_session: AsyncSession, project: dict[str, object]) -> None:
    project_id = uuid.UUID(str(project["id"]))
    base = {"scope": MemoryScope.project, "kind": MemoryKind.fact, "status": "validated"}
    old = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=MemoryIn(
            **base,  # type: ignore[arg-type]
            title="Capacité du site de Lyon",
            content="Le site de Lyon compte 720 postes.",
            valid_from=utcnow() - timedelta(days=70),
        ),
        actor=SYSTEM,
    )
    new = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=MemoryIn(
            **base,  # type: ignore[arg-type]
            title="Capacité du site de Lyon après réaménagement",
            content="Le site de Lyon compte 650 postes après réaménagement.",
            valid_from=utcnow() - timedelta(days=6),
        ),
        actor=SYSTEM,
    )
    await db_session.commit()
    relation = await db_session.scalar(
        select(Relation).where(
            Relation.rel_type == RelationType.contradicts,
            Relation.src_id.in_([old.id, new.id]),
            Relation.dst_id.in_([old.id, new.id]),
        )
    )
    assert relation is not None
    assert relation.detail and "720" in relation.detail and "650" in relation.detail
    assert MemoryEventType.conflict_detected in await _events(db_session, old)
    assert MemoryEventType.conflict_detected in await _events(db_session, new)
    # Facts are never auto-superseded: both stay active.
    assert old.status == MemoryStatus.validated and new.status == MemoryStatus.validated


async def test_append_only_versioning(db_session: AsyncSession, project: dict[str, object]) -> None:
    project_id = uuid.UUID(str(project["id"]))
    v1 = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=MemoryIn(
            scope=MemoryScope.project,
            kind=MemoryKind.constraint,
            title="Conformité RGAA",
            content="Conformité RGAA AA obligatoire.",
        ),
        actor=SYSTEM,
    )
    v2 = await lifecycle.new_version(
        db_session, v1, {"content": "Conformité RGAA AA obligatoire sur toutes les interfaces."}, SYSTEM
    )
    await db_session.commit()
    assert v2.id != v1.id and v2.lineage_id == v1.lineage_id
    assert v2.version == 2 and v2.is_current
    assert not v1.is_current
    assert v1.content == "Conformité RGAA AA obligatoire."
    versions = await lifecycle.lineage_versions(db_session, v1.lineage_id)
    assert [v.version for v in versions] == [2, 1]
    edited = await db_session.scalar(
        select(MemoryEvent).where(
            MemoryEvent.lineage_id == v1.lineage_id, MemoryEvent.event == MemoryEventType.edited
        )
    )
    assert edited is not None and "content" in str(edited.data)


async def test_forget_item_and_invalid_transitions(
    db_session: AsyncSession, project: dict[str, object]
) -> None:
    project_id = uuid.UUID(str(project["id"]))
    item = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=MemoryIn(
            scope=MemoryScope.project,
            kind=MemoryKind.fact,
            title="Budget pilote",
            content="Le budget du pilote est de 120 000 euros.",
            status="proposed",
        ),
        actor=SYSTEM,
    )
    await lifecycle.new_version(db_session, item, {"title": "Budget du pilote"}, SYSTEM)
    current = await lifecycle.current_version(db_session, item.lineage_id)
    assert current is not None
    await lifecycle.forget(db_session, current, SYSTEM, "Donnée erronée")
    await db_session.commit()
    for version in await lifecycle.lineage_versions(db_session, item.lineage_id):
        assert version.content == lifecycle.FORGOTTEN_CONTENT
    assert current.status == MemoryStatus.forgotten
    assert current.title == "Budget du pilote"
    with pytest.raises(HTTPException) as excinfo:
        await lifecycle.validate(db_session, current, SYSTEM)
    assert excinfo.value.status_code == 409
    assert "oublié" in str(excinfo.value.detail)
    await db_session.rollback()


async def test_document_forget_propagation(db_session: AsyncSession, project: dict[str, object]) -> None:
    project_id = uuid.UUID(str(project["id"]))
    doc_a, chunk_a = await _document(db_session, project_id, "Inventaire immobilier Lyon")
    _doc_b, chunk_b = await _document(db_session, project_id, "Plan des étages")
    only_a = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=MemoryIn(
            scope=MemoryScope.project,
            kind=MemoryKind.fact,
            title="Nombre de postes à Lyon",
            content="Le site de Lyon compte 720 postes.",
            provenance=[ProvenanceIn(chunk_id=chunk_a.id)],
        ),
        actor=SYSTEM,
        detect=False,
    )
    both = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=MemoryIn(
            scope=MemoryScope.project,
            kind=MemoryKind.fact,
            title="Étages du site de Lyon",
            content="Le site de Lyon est réparti sur quatre étages.",
            confidence=0.8,
            provenance=[ProvenanceIn(chunk_id=chunk_a.id), ProvenanceIn(chunk_id=chunk_b.id)],
        ),
        actor=SYSTEM,
        detect=False,
    )
    assert only_a.classification == 1
    doc_a.status = DocumentStatus.forgotten
    await db_session.flush()
    affected = await lifecycle.propagate_document_forget(db_session, doc_a, SYSTEM)
    await db_session.commit()
    assert affected == 2
    only_a_now = await lifecycle.current_version(db_session, only_a.lineage_id)
    both_now = await lifecycle.current_version(db_session, both.lineage_id)
    assert only_a_now is not None and only_a_now.status == MemoryStatus.forgotten
    assert both_now is not None
    assert both_now.status in {MemoryStatus.validated, MemoryStatus.proposed}
    assert both_now.confidence == pytest.approx(0.8 * 0.6, abs=0.01)


async def test_user_scope_acl_and_short_term_expiry(
    db_session: AsyncSession, project: dict[str, object], make_user: Callable[..., Awaitable[UserInfo]]
) -> None:
    project_id = uuid.UUID(str(project["id"]))
    user = await make_user()
    preference = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=MemoryIn(
            scope=MemoryScope.user,
            kind=MemoryKind.preference,
            title="Réponses concises",
            content="Préfère des réponses concises en français.",
            subject_user_id=user.id,
        ),
        actor=SYSTEM,
    )
    assert preference.acl_principals == [f"user:{user.id}"]
    short = await lifecycle.create_item(
        db_session,
        project_id=project_id,
        data=MemoryIn(
            scope=MemoryScope.short_term,
            kind=MemoryKind.fact,
            title="Contexte de tâche",
            content="L'agent rédige la user story QR code.",
            session_id="sess-expiry",
        ),
        actor=SYSTEM,
    )
    assert short.expires_at is not None and short.expires_at > utcnow()
    short.expires_at = utcnow() - timedelta(minutes=1)
    await db_session.commit()
    counters = await lifecycle.run_periodic_maintenance(db_session)
    await db_session.commit()
    await db_session.refresh(short)
    assert counters.get("expired_short_term", 0) >= 1
    assert short.status == MemoryStatus.obsolete
    assert MemoryEventType.obsoleted in await _events(db_session, short)

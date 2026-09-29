"""Assembler pipeline with faked retrieval and an in-memory session (no infrastructure).

Exercises understand → retrieve → fuse → rerank → govern → select → compress → package → persist,
the non-leak presentation of exclusions for the caller and the ``explain`` switch for agents.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.context import assembler, retrieval, selection
from app.context.retrieval import ChunkRow, IndexHit, MemoryRow, RawRetrieval
from app.context.visibility import Viewer
from app.deps import Principal, ProjectAccess
from app.enums import (
    ActorType,
    ChunkStatus,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    ReasonCode,
    Role,
    SourceKind,
)
from app.models import AuditLog, Chunk, ContextDecision, ContextRequest, Document, MemoryItem, Project, User
from app.schemas import ContextRequestIn

NOW = datetime.now(UTC)
PROJECT_ID = uuid.uuid4()


class FakeSession:
    """Collects what the assembler persists."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: Any) -> None:
        self.added.extend(objs)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    def of(self, cls: type) -> list[Any]:
        return [o for o in self.added if isinstance(o, cls)]


def _doc(title: str, **kwargs: Any) -> Document:
    return Document(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_id=uuid.uuid4(),
        title=title,
        uri=f"https://wiki.example/{title.lower().replace(' ', '-')}",
        classification=kwargs.pop("classification", 1),
        acl_principals=kwargs.pop("acl_principals", ["project:*"]),
        current_version=kwargs.pop("current_version", 1),
        source_updated_at=kwargs.pop("source_updated_at", NOW - timedelta(days=8)),
        forgotten_at=None,
        **kwargs,
    )


def _chunk(doc: Document, text: str, **kwargs: Any) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        document_id=doc.id,
        version=kwargs.pop("version", doc.current_version),
        ordinal=0,
        text=text,
        text_redacted=kwargs.pop("text_redacted", text),
        classification=doc.classification,
        acl_principals=list(doc.acl_principals),
        status=kwargs.pop("status", ChunkStatus.active),
        pii=kwargs.pop("pii", []),
        section=None,
    )


def _memory(title: str, content: str, **kwargs: Any) -> MemoryItem:
    return MemoryItem(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        lineage_id=uuid.uuid4(),
        version=1,
        is_current=True,
        scope=kwargs.pop("scope", MemoryScope.project),
        kind=kwargs.pop("kind", MemoryKind.decision),
        status=kwargs.pop("status", MemoryStatus.validated),
        title=title,
        content=content,
        confidence=0.9,
        classification=kwargs.pop("classification", 1),
        acl_principals=kwargs.pop("acl_principals", ["project:*"]),
        valid_from=kwargs.pop("valid_from", NOW - timedelta(days=3)),
        created_by_type=ActorType.system,
        **kwargs,
    )


def _hit(item_id: uuid.UUID, rank: int) -> IndexHit:
    rrf = 1.0 / (60 + rank)
    return IndexHit(
        id=str(item_id), rrf=rrf, rrf_norm=61 / (60 + rank), bm25=10.0 / rank, bm25_rank=rank, via="hybrid"
    )


@pytest.fixture
def corpus(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    spec = _doc("Spécification Atlas")
    board = _doc("Note de direction Atlas", acl_principals=["role:owner"])
    secret = _doc("Audit Atlas", classification=3)
    email_doc = _doc("Compte rendu Atlas")
    chunks = {
        "spec": ChunkRow(
            chunk=_chunk(
                spec, "L'authentification Atlas repose sur OIDC. Les sessions expirent après trente minutes."
            ),
            document=spec,
            source_kind=SourceKind.document,
        ),
        "board": ChunkRow(
            chunk=_chunk(board, "Budget confidentiel de l'authentification Atlas."),
            document=board,
            source_kind=SourceKind.document,
        ),
        "secret": ChunkRow(
            chunk=_chunk(secret, "Faille d'authentification Atlas."),
            document=secret,
            source_kind=SourceKind.document,
        ),
        "pii": ChunkRow(
            chunk=_chunk(
                email_doc,
                "Contact authentification Atlas : alice@example.com.",
                text_redacted="Contact authentification Atlas : [EMAIL].",
                pii=[{"type": "EMAIL", "start": 33, "end": 50}],
            ),
            document=email_doc,
            source_kind=SourceKind.document,
        ),
    }
    decision = MemoryRow(
        item=_memory("SSO Atlas via OIDC", "Décision : l'authentification Atlas passe par OIDC.")
    )
    chunk_hits = [_hit(row.chunk.id, rank) for rank, row in enumerate(chunks.values(), start=1)]
    memory_hits = [_hit(decision.item.id, 1)]

    async def fake_retrieve(_session: Any, **kwargs: Any) -> RawRetrieval:
        raw = RawRetrieval(chunk_hits=list(chunk_hits), memory_hits=list(memory_hits))
        raw.chunks = {str(row.chunk.id): row for row in chunks.values()}
        raw.memory_resolution = {str(decision.item.id): decision}
        raw.memory_by_lineage = {str(decision.item.lineage_id): decision}
        raw.sources_used = {"chunks": "hybrid", "memory": "hybrid"}
        return raw

    async def no_contradictions(*_args: Any, **_kwargs: Any) -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr(retrieval, "retrieve", fake_retrieve)
    monkeypatch.setattr(selection, "load_contradictions", no_contradictions)
    return {"chunks": chunks, "decision": decision}


def _resolved(
    body: ContextRequestIn, *, role: Role = Role.viewer, is_admin: bool = False, agent: bool = False
) -> Any:
    user = User(
        id=uuid.uuid4(),
        email="vera@example.com",
        full_name="Vera",
        is_admin=is_admin,
        clearance=3 if is_admin else 1,
    )
    project = Project(id=PROJECT_ID, slug="atlas", name="Atlas", settings={})
    principal = Principal.for_user(user)
    principals = {"project:*", f"role:{role.value}", f"user:{user.id}"}
    if role == Role.owner:
        principals |= {"role:editor", "role:viewer"}
    access = ProjectAccess(project=project, principal=principal, role=role)
    viewer = Viewer(
        principals=frozenset(principals),
        clearance=int(user.clearance),
        user_id=user.id,
        sees_restricted_details=role == Role.owner or is_admin,
        is_admin=is_admin,
        is_agent=agent,
    )
    return assembler.ResolvedRequest(
        access=access,
        body=body,
        agent=None,
        on_behalf_of=user,
        principals=principals,
        clearance=int(user.clearance),
        scopes=set(MemoryScope),
        source_kinds=None,
        token_budget=assembler.clamp_budget(body.token_budget, 4000),
        min_relevance=0.0,
        freshness_days={"document": 365},
        explain=body.explain if body.explain is not None else not agent,
        base_snapshot=None,
        save_name=None,
        viewer=viewer,
    )


async def _run(resolved: Any) -> tuple[Any, FakeSession]:
    session = FakeSession()
    package = await assembler._run(session, resolved, assembler._Timer(), uuid.uuid4(), "trace-test")  # type: ignore[arg-type]
    return package, session


@pytest.mark.asyncio
async def test_pipeline_persists_every_decision_and_redacts_for_viewer(corpus: dict[str, Any]) -> None:
    package, session = await _run(_resolved(ContextRequestIn(task="Authentification Atlas ?")))

    assert set(package.timings.model_dump()) == set(assembler.STAGES) | {"total"}
    assert package.timings.total >= 0
    assert [i.citation for i in package.items] == [f"S{n}" for n in range(1, len(package.items) + 1)]
    assert package.items[0].memory_kind == MemoryKind.decision  # decisions come first
    included = {i.id for i in package.items}
    assert str(corpus["chunks"]["spec"].chunk.id) in included
    pii_item = next(i for i in package.items if i.id == str(corpus["chunks"]["pii"].chunk.id))
    assert (
        pii_item.pii_redacted and "alice@example.com" not in package.context and "[EMAIL]" in package.context
    )

    codes = {e.reason_code for e in package.excluded}
    assert codes == {ReasonCode.EXCLUDED_ACL, ReasonCode.EXCLUDED_CLASSIFICATION}
    for e in package.excluded:
        assert e.redacted and e.id is None and e.title is None
    assert "Note de direction" not in package.context and "Audit Atlas" not in package.context
    assert package.tokens_used <= package.token_budget
    assert package.candidates_count == 5

    (row,) = session.of(ContextRequest)
    assert row.included_count == len(package.items) and row.excluded_count == 2
    assert row.context_text == package.context and row.latency_ms is not None
    assert len(session.of(ContextDecision)) == 5
    (audit_row,) = session.of(AuditLog)
    assert audit_row.action == "context.request"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_owner_sees_titles_of_restricted_exclusions(corpus: dict[str, Any]) -> None:
    package, _ = await _run(_resolved(ContextRequestIn(task="Authentification Atlas ?"), role=Role.owner))
    # role:owner satisfies the ACL; the C3 document stays above the owner's C1 clearance.
    assert str(corpus["chunks"]["board"].chunk.id) in {i.id for i in package.items}
    (cls,) = package.excluded
    assert cls.reason_code == ReasonCode.EXCLUDED_CLASSIFICATION
    assert cls.reason_detail == "C3 > habilitation C1"
    # Non-leak: an owner without the clearance does not get the content either.
    assert cls.excerpt is None


@pytest.mark.asyncio
async def test_explain_false_returns_counters_only(corpus: dict[str, Any]) -> None:
    package, _ = await _run(_resolved(ContextRequestIn(task="Authentification Atlas ?", explain=False)))
    assert package.excluded == []
    assert package.exclusion_summary == {ReasonCode.EXCLUDED_ACL: 1, ReasonCode.EXCLUDED_CLASSIFICATION: 1}


@pytest.mark.asyncio
async def test_admin_gets_classified_warning(corpus: dict[str, Any]) -> None:
    package, _ = await _run(
        _resolved(ContextRequestIn(task="Authentification Atlas ?"), is_admin=True, role=Role.owner)
    )
    assert not package.excluded
    assert any("C3" in w for w in package.warnings)


@pytest.mark.asyncio
async def test_small_budget_is_respected(corpus: dict[str, Any]) -> None:
    package, _ = await _run(_resolved(ContextRequestIn(task="Authentification Atlas ?", token_budget=500)))
    assert package.token_budget == 500 and package.tokens_used <= 500


def test_budget_bounds() -> None:
    assert assembler.clamp_budget(None, 4000) == 4000
    assert assembler.clamp_budget(100, 4000) == 500
    assert assembler.clamp_budget(100_000, 4000) == 32_000
    with pytest.raises(ValueError):
        ContextRequestIn(task="x", token_budget=499)

"""Context snapshots (ARCHITECTURE §10).

Snapshots are immutable and versioned: ``(project_id, name, version)`` is unique and ``version`` is
auto-incremented per name (``parent_id`` = previous latest version). ``items`` stores ``SnapshotItem``
dicts whose ``key`` is ``"chunk:<chunk_id>"`` or ``"memory:<lineage_id>"`` so that diffs compare the
same logical item across versions; ``content_hash`` is the SHA-256 of the Markdown content.

At read time items are checked against the current state of the repository: forgotten content is
flagged (``forgotten: true``) and redacted, and content the reader may not access (ACL,
classification, another user's personal memory) is redacted too (non-leak principle).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.visibility import FORGOTTEN_TEXT, RESTRICTED_TITLE, Viewer, Visibility, redact_markdown
from app.enums import ActorType, CandidateType, ChunkStatus, DocumentStatus, MemoryStatus
from app.errors import validation_error
from app.governance.acl import DEFAULT_ACL
from app.models import Agent, Chunk, ContextRequest, ContextSnapshot, Document, MemoryItem, User
from app.schemas.context import ContextPackage
from app.schemas.snapshots import Snapshot, SnapshotDiff, SnapshotGroup, SnapshotItem, SnapshotSummary
from app.services.audit import ActorLike, resolve_actor

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
NAME_ERROR = (
    "Nom de snapshot invalide : lettres minuscules, chiffres, points, tirets ou soulignés "
    "(120 caractères maximum, ex. « spec-atlas »)"
)


def normalize_name(name: str) -> str:
    """Slug-like snapshot name (lower-cased). Raises a French 422 error when invalid."""
    candidate = (name or "").strip().lower()
    if not NAME_PATTERN.match(candidate):
        raise validation_error(NAME_ERROR)
    return candidate


def item_key(candidate_type: str, item_id: str, lineage_id: str | None = None) -> str:
    """Stable diff key: ``memory:<lineage_id>`` for memory items, ``<type>:<id>`` otherwise."""
    kind = str(getattr(candidate_type, "value", candidate_type))
    if kind == "memory" and lineage_id:
        return f"memory:{lineage_id}"
    return f"{kind}:{item_id}"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_version(raw: str | int | None) -> int | Literal["latest"] | None:
    """``"latest"`` / ``None`` / positive integer. Raises a French 422 error otherwise."""
    if raw is None:
        return None
    if isinstance(raw, int):
        if raw < 1:
            raise validation_error("Version de snapshot invalide (entier ≥ 1 ou « latest »)")
        return raw
    value = str(raw).strip().lower()
    if value == "latest":
        return "latest"
    if value.startswith("v"):
        value = value[1:]
    if not value.isdigit() or int(value) < 1:
        raise validation_error("Version de snapshot invalide (entier ≥ 1 ou « latest »)")
    return int(value)


# --- Creation -----------------------------------------------------------------------------------------


async def _lineages(session: AsyncSession, memory_ids: Sequence[uuid.UUID]) -> dict[str, str]:
    if not memory_ids:
        return {}
    rows = await session.execute(
        select(MemoryItem.id, MemoryItem.lineage_id).where(MemoryItem.id.in_(list(memory_ids)))
    )
    return {str(item_id): str(lineage_id) for item_id, lineage_id in rows.tuples()}


def _snapshot_items(package: ContextPackage, lineages: Mapping[str, str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in package.items:
        kind = item.candidate_type.value
        lineage = lineages.get(str(item.memory_item_id or item.id)) if kind == "memory" else None
        items.append(
            SnapshotItem(
                key=item_key(kind, item.id, lineage),
                citation=item.citation,
                candidate_type=item.candidate_type,
                id=item.id,
                title=item.title,
                excerpt=item.excerpt,
                source_kind=item.source_kind,
                memory_kind=item.memory_kind,
                version=item.version,
                forgotten=False,
            ).model_dump(mode="json")
        )
    return items


async def create_snapshot(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    name: str,
    request: ContextRequest,
    package: ContextPackage,
    actor: ActorLike,
) -> ContextSnapshot:
    """Persist a new version of snapshot ``name`` from a served package (flush, caller commits)."""
    normalized = normalize_name(name)
    # Serialise concurrent saves of the same name (version numbers stay gap-free and unique).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"orbit:snapshot:{project_id}:{normalized}"},
    )
    latest = await session.scalar(
        select(ContextSnapshot)
        .where(ContextSnapshot.project_id == project_id, ContextSnapshot.name == normalized)
        .order_by(ContextSnapshot.version.desc())
        .limit(1)
    )
    memory_ids = [i.memory_item_id for i in package.items if i.memory_item_id is not None]
    lineages = await _lineages(session, memory_ids)
    resolved = resolve_actor(actor)
    snapshot = ContextSnapshot(
        project_id=project_id,
        name=normalized,
        version=(latest.version + 1) if latest is not None else 1,
        parent_id=latest.id if latest is not None else None,
        request_id=request.id,
        task=request.task,
        intent=request.intent,
        content=package.context,
        items=_snapshot_items(package, lineages),
        content_hash=content_hash(package.context),
        token_count=package.tokens_used,
        created_by_type=resolved.type,
        created_by_id=resolved.id,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


# --- Queries ------------------------------------------------------------------------------------------


async def get_snapshot(
    session: AsyncSession, project_id: uuid.UUID, name: str, version: int | Literal["latest"] | None = None
) -> ContextSnapshot | None:
    """A given version, or the latest when ``version`` is ``None``/``"latest"``."""
    normalized = (name or "").strip().lower()
    stmt = select(ContextSnapshot).where(
        ContextSnapshot.project_id == project_id, ContextSnapshot.name == normalized
    )
    if version is None or version == "latest":
        stmt = stmt.order_by(ContextSnapshot.version.desc()).limit(1)
    else:
        stmt = stmt.where(ContextSnapshot.version == int(version))
    return await session.scalar(stmt)


async def list_groups(session: AsyncSession, project_id: uuid.UUID) -> list[SnapshotGroup]:
    stats = (
        select(
            ContextSnapshot.name.label("name"),
            func.max(ContextSnapshot.version).label("latest_version"),
            func.count().label("versions"),
            func.max(ContextSnapshot.created_at).label("updated_at"),
        )
        .where(ContextSnapshot.project_id == project_id)
        .group_by(ContextSnapshot.name)
        .subquery()
    )
    rows = await session.execute(
        select(
            stats.c.name, stats.c.latest_version, stats.c.versions, stats.c.updated_at, ContextSnapshot.task
        )
        .join(
            ContextSnapshot,
            (ContextSnapshot.project_id == project_id)
            & (ContextSnapshot.name == stats.c.name)
            & (ContextSnapshot.version == stats.c.latest_version),
        )
        .order_by(stats.c.updated_at.desc(), stats.c.name)
    )
    return [
        SnapshotGroup(
            name=name, latest_version=int(latest), versions=int(count), updated_at=updated_at, last_task=task
        )
        for name, latest, count, updated_at, task in rows.tuples()
    ]


async def list_versions(session: AsyncSession, project_id: uuid.UUID, name: str) -> list[ContextSnapshot]:
    """All versions of ``name``, newest first."""
    rows = await session.scalars(
        select(ContextSnapshot)
        .where(ContextSnapshot.project_id == project_id, ContextSnapshot.name == (name or "").strip().lower())
        .order_by(ContextSnapshot.version.desc())
    )
    return list(rows)


# --- Read-time checks ---------------------------------------------------------------------------------


@dataclass(slots=True)
class ItemState:
    """Current repository state of a snapshot item."""

    exists: bool
    forgotten: bool
    classification: int = 0
    acls: list[list[str]] = field(default_factory=list)
    memory_scope: str | None = None
    subject_user_id: uuid.UUID | None = None


def _split_key(key: str) -> tuple[str, str]:
    kind, _, ident = key.partition(":")
    return kind, ident


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


async def inspect_items(
    session: AsyncSession, project_id: uuid.UUID, items: Sequence[Mapping[str, Any]]
) -> dict[str, ItemState]:
    """Batch lookup of the current state of every chunk / memory lineage referenced by ``items``."""
    chunk_ids: set[uuid.UUID] = set()
    lineage_ids: set[uuid.UUID] = set()
    for item in items:
        kind, ident = _split_key(str(item.get("key", "")))
        parsed = _uuid(ident)
        if parsed is None:
            continue
        if kind == CandidateType.chunk.value:
            chunk_ids.add(parsed)
        elif kind == CandidateType.memory.value:
            lineage_ids.add(parsed)
    states: dict[str, ItemState] = {}
    if chunk_ids:
        rows = await session.execute(
            select(
                Chunk.id,
                Chunk.status,
                Chunk.classification,
                Chunk.acl_principals,
                Document.status,
                Document.forgotten_at,
                Document.classification,
                Document.acl_principals,
            )
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(chunk_ids), Chunk.project_id == project_id)
        )
        for cid, c_status, c_cls, c_acl, d_status, d_forgotten, d_cls, d_acl in rows.tuples():
            forgotten = (
                c_status == ChunkStatus.forgotten
                or d_status == DocumentStatus.forgotten
                or d_forgotten is not None
            )
            states[f"chunk:{cid}"] = ItemState(
                exists=True,
                forgotten=forgotten,
                classification=max(int(c_cls), int(d_cls)),
                acls=[list(c_acl or DEFAULT_ACL), list(d_acl or DEFAULT_ACL)],
            )
    if lineage_ids:
        rows = await session.scalars(
            select(MemoryItem)
            .where(MemoryItem.lineage_id.in_(lineage_ids))
            .order_by(MemoryItem.lineage_id, MemoryItem.is_current.desc(), MemoryItem.version.desc())
        )
        for item in rows:
            key = f"memory:{item.lineage_id}"
            if key in states:
                continue
            if item.project_id not in (project_id, None):
                continue
            states[key] = ItemState(
                exists=True,
                forgotten=item.status == MemoryStatus.forgotten,
                classification=int(item.classification),
                acls=[list(item.acl_principals or DEFAULT_ACL)],
                memory_scope=str(getattr(item.scope, "value", item.scope)),
                subject_user_id=item.subject_user_id,
            )
    return states


def present_items(
    items: Sequence[Mapping[str, Any]], states: Mapping[str, ItemState], viewer: Viewer | None
) -> tuple[list[SnapshotItem], dict[str, str]]:
    """Snapshot items as shown to ``viewer`` + the Markdown replacements (citation -> text) to apply."""
    shown: list[SnapshotItem] = []
    replacements: dict[str, str] = {}
    for raw in items:
        item = SnapshotItem.model_validate(raw)
        kind, _ident = _split_key(item.key)
        state = states.get(item.key)
        if kind in (CandidateType.chunk.value, CandidateType.memory.value) and (
            state is None or state.forgotten
        ):
            item = item.model_copy(
                update={"forgotten": True, "title": FORGOTTEN_TEXT, "excerpt": FORGOTTEN_TEXT}
            )
            replacements[item.citation] = FORGOTTEN_TEXT
        elif state is not None and viewer is not None:
            visibility = viewer.visibility(
                classification=state.classification,
                acls=state.acls,
                memory_scope=state.memory_scope,
                subject_user_id=state.subject_user_id,
            )
            if visibility == Visibility.partial:
                item = item.model_copy(update={"excerpt": ""})
                replacements[item.citation] = f"{item.title} — {RESTRICTED_TITLE.lower()}"
            elif visibility == Visibility.redacted:
                item = item.model_copy(update={"id": "", "title": RESTRICTED_TITLE, "excerpt": ""})
                replacements[item.citation] = RESTRICTED_TITLE
        shown.append(item)
    return shown, replacements


async def creator_labels(session: AsyncSession, snapshots: Sequence[ContextSnapshot]) -> dict[uuid.UUID, str]:
    user_ids = {s.created_by_id for s in snapshots if s.created_by_type == ActorType.user and s.created_by_id}
    agent_ids = {
        s.created_by_id for s in snapshots if s.created_by_type == ActorType.agent and s.created_by_id
    }
    labels: dict[uuid.UUID, str] = {}
    if user_ids:
        for uid, name, email in (
            await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(user_ids)))
        ).tuples():
            labels[uid] = name or email
    if agent_ids:
        for aid, name in (
            await session.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        ).tuples():
            labels[aid] = name
    return labels


def _creator(snapshot: ContextSnapshot, labels: Mapping[uuid.UUID, str]) -> str:
    if snapshot.created_by_id is not None and snapshot.created_by_id in labels:
        return labels[snapshot.created_by_id]
    return "Système ORBIT" if snapshot.created_by_type == ActorType.system else ""


def to_summary(
    snapshot: ContextSnapshot, *, parent_version: int | None, created_by_label: str
) -> SnapshotSummary:
    return SnapshotSummary(
        id=snapshot.id,
        name=snapshot.name,
        version=snapshot.version,
        parent_version=parent_version,
        task=snapshot.task,
        intent=snapshot.intent,
        token_count=snapshot.token_count,
        items_count=len(snapshot.items or []),
        content_hash=snapshot.content_hash,
        created_by_label=created_by_label,
        created_at=snapshot.created_at,
    )


async def summaries(session: AsyncSession, versions: Sequence[ContextSnapshot]) -> list[SnapshotSummary]:
    labels = await creator_labels(session, versions)
    parent_ids = {s.parent_id for s in versions if s.parent_id is not None}
    known = {s.id: s.version for s in versions}
    missing = parent_ids - set(known)
    if missing:
        rows = await session.execute(
            select(ContextSnapshot.id, ContextSnapshot.version).where(ContextSnapshot.id.in_(missing))
        )
        known.update(dict(rows.tuples().all()))
    return [
        to_summary(
            s,
            parent_version=known.get(s.parent_id) if s.parent_id else None,
            created_by_label=_creator(s, labels),
        )
        for s in versions
    ]


async def present(session: AsyncSession, snapshot: ContextSnapshot, viewer: Viewer | None) -> Snapshot:
    """Full snapshot as shown to ``viewer`` (forgotten and restricted items redacted)."""
    items = list(snapshot.items or [])
    states = await inspect_items(session, snapshot.project_id, items)
    shown, replacements = present_items(items, states, viewer)
    summary = (await summaries(session, [snapshot]))[0]
    return Snapshot(
        **summary.model_dump(),
        content=redact_markdown(snapshot.content, replacements),
        items=shown,
        request_id=snapshot.request_id,
    )


def diff(
    old: ContextSnapshot,
    new: ContextSnapshot,
    *,
    old_items: Sequence[SnapshotItem] | None = None,
    new_items: Sequence[SnapshotItem] | None = None,
) -> SnapshotDiff:
    """Added / removed / unchanged items between two versions (compared by ``key``).

    ``old_items`` / ``new_items`` may carry the read-time presentation (forgotten/redacted flags);
    otherwise the stored items are used.
    """
    before = (
        list(old_items)
        if old_items is not None
        else [SnapshotItem.model_validate(i) for i in old.items or []]
    )
    after = (
        list(new_items)
        if new_items is not None
        else [SnapshotItem.model_validate(i) for i in new.items or []]
    )
    before_keys = {i.key for i in before}
    after_keys = {i.key for i in after}
    return SnapshotDiff(
        from_=old.version,
        to=new.version,
        added=[i for i in after if i.key not in before_keys],
        removed=[i for i in before if i.key not in after_keys],
        unchanged=[i for i in after if i.key in before_keys],
    )


async def present_diff(
    session: AsyncSession, old: ContextSnapshot, new: ContextSnapshot, viewer: Viewer | None
) -> SnapshotDiff:
    items = [*(old.items or []), *(new.items or [])]
    states = await inspect_items(session, new.project_id, items)
    old_items, _ = present_items(list(old.items or []), states, viewer)
    new_items, _ = present_items(list(new.items or []), states, viewer)
    return diff(old, new, old_items=old_items, new_items=new_items)

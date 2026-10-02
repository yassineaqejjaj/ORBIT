"""Change feed queries, snapshot freshness, digests (UI + e-mail) and stale-document detection."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.enums import DocumentStatus, MemoryStatus, Role
from app.features.feed import events
from app.features.feed.schemas import (
    ChangeEventOut,
    Digest,
    DigestGroup,
    OutdatedItem,
    SinceSnapshot,
    SnapshotRef,
)
from app.features.feed.types import ChangeType, type_label
from app.governance import freshness
from app.governance.acl import acl_allows, effective_principals, principals_for_member
from app.memory.visibility import MemoryViewer, can_view
from app.models import ContextSnapshot, Document, MemoryItem, Project, ProjectMember, Source, User
from app.models.features_feed import ChangeEvent, Subscription
from app.services import audit
from app.services import projects as project_service

if TYPE_CHECKING:
    from app.deps import ProjectAccess

logger = logging.getLogger("orbit.feed")

PERIODS: dict[str, timedelta] = {"day": timedelta(days=1), "week": timedelta(days=7)}
DIGEST_FREQUENCIES: dict[str, str] = {"daily": "day", "weekly": "week"}
DIGEST_GROUP_LIMIT = 10
SINCE_SNAPSHOT_LIMIT = 200
STALE_BATCH = 200


@dataclass(frozen=True, slots=True)
class FeedViewer:
    project_id: uuid.UUID
    principals: frozenset[str]
    clearance: int

    @classmethod
    def from_access(cls, access: ProjectAccess) -> FeedViewer:
        return cls(
            access.project_id, frozenset(effective_principals(access)), int(access.principal.clearance)
        )


def to_out(event: ChangeEvent) -> ChangeEventOut:
    out = ChangeEventOut.model_validate(event)
    out.type_label = type_label(event.type)
    return out


def _conditions(
    viewer: FeedViewer, since: datetime | None, types: Sequence[str] | None, until: datetime | None = None
) -> list[Any]:
    conditions: list[Any] = [
        ChangeEvent.project_id == viewer.project_id,
        events.visibility_clause(viewer.principals, viewer.clearance),
    ]
    if since is not None:
        conditions.append(ChangeEvent.created_at > since)
    if until is not None:
        conditions.append(ChangeEvent.created_at <= until)
    if types:
        conditions.append(ChangeEvent.type.in_(list(types)))
    return conditions


async def list_changes(
    session: AsyncSession,
    viewer: FeedViewer,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    types: Sequence[str] | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[ChangeEvent], int]:
    conditions = _conditions(viewer, since, types, until)
    total = await session.scalar(select(func.count()).select_from(ChangeEvent).where(*conditions))
    rows = await session.scalars(
        select(ChangeEvent)
        .where(*conditions)
        .order_by(ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)


# --- Since a snapshot ------------------------------------------------------------------------------


def _document_visible(document: Document, viewer: FeedViewer) -> bool:
    return (
        document.project_id == viewer.project_id
        and int(document.classification) <= viewer.clearance
        and acl_allows(document.acl_principals, viewer.principals)
    )


async def since_snapshot(
    session: AsyncSession, access: ProjectAccess, snapshot: ContextSnapshot
) -> SinceSnapshot:
    viewer = FeedViewer.from_access(access)
    memory_viewer = MemoryViewer.from_access(access)
    rows, total = await list_changes(session, viewer, since=snapshot.created_at, limit=SINCE_SNAPSHOT_LIMIT)
    project = await session.get(Project, access.project_id)
    policy = project_service.normalize_settings(project.settings if project else None)["freshness_days"]
    now = utcnow()

    outdated: list[OutdatedItem] = []
    hidden = 0
    seen: set[uuid.UUID] = set()
    for raw in snapshot.items or []:
        memory_id = events._uuid(raw.get("memory_item_id"))
        document_id = events._uuid(raw.get("document_id"))
        if memory_id is not None and memory_id not in seen:
            seen.add(memory_id)
            item = await session.get(MemoryItem, memory_id)
            if item is None:
                continue
            entry = await _memory_outdated(session, item, memory_viewer)
            if entry is None:
                continue
            if can_view(item, memory_viewer):
                outdated.append(entry)
            else:
                hidden += 1
        elif document_id is not None and memory_id is None and document_id not in seen:
            seen.add(document_id)
            document = await session.get(Document, document_id)
            if document is None:
                continue
            entry = await _document_outdated(session, document, raw, policy, now)
            if entry is None:
                continue
            if _document_visible(document, viewer):
                outdated.append(entry)
            else:
                hidden += 1
    return SinceSnapshot(
        snapshot=SnapshotRef.model_validate(snapshot),
        total=total,
        changes=[to_out(row) for row in rows],
        outdated=outdated,
        hidden_outdated=hidden,
        is_up_to_date=not outdated and hidden == 0,
    )


async def _memory_outdated(
    session: AsyncSession, item: MemoryItem, viewer: MemoryViewer
) -> OutdatedItem | None:
    status = MemoryStatus(item.status)
    current = item
    if not item.is_current:
        current = (
            await session.scalar(
                select(MemoryItem).where(
                    MemoryItem.lineage_id == item.lineage_id, MemoryItem.is_current.is_(True)
                )
            )
            or item
        )
        status = MemoryStatus(current.status)
    if status == MemoryStatus.forgotten:
        return OutdatedItem(
            item_type="memory", id=item.id, title=events.FORGOTTEN_TITLE, reason="forgotten",
            detail="Oublié depuis le snapshot (oubli sélectif)",
        )  # fmt: skip
    if status == MemoryStatus.superseded:
        by = await session.get(MemoryItem, current.superseded_by_id) if current.superseded_by_id else None
        visible = by is not None and can_view(by, viewer)
        return OutdatedItem(
            item_type="memory",
            id=item.id,
            title=item.title,
            reason="superseded",
            detail=f"Remplacé par « {by.title} »" if visible and by else "Remplacé depuis le snapshot",
            replaced_by_id=by.id if visible and by else None,
            replaced_by_title=by.title if visible and by else None,
        )
    if status == MemoryStatus.obsolete:
        return OutdatedItem(
            item_type="memory", id=item.id, title=item.title, reason="obsolete",
            detail="Marqué obsolète depuis le snapshot",
        )  # fmt: skip
    if current.id != item.id:
        return OutdatedItem(
            item_type="memory", id=item.id, title=item.title, reason="edited",
            detail=f"Modifié depuis le snapshot (v{item.version} → v{current.version})",
            replaced_by_id=current.id, replaced_by_title=current.title,
        )  # fmt: skip
    return None


async def _document_outdated(
    session: AsyncSession, document: Document, raw: dict[str, Any], policy: dict[str, int], now: datetime
) -> OutdatedItem | None:
    if DocumentStatus(document.status) == DocumentStatus.forgotten:
        return OutdatedItem(
            item_type="document", id=document.id, title=events.FORGOTTEN_TITLE, reason="forgotten",
            detail="Document oublié depuis le snapshot",
        )  # fmt: skip
    version = raw.get("version")
    if isinstance(version, int) and document.current_version > version:
        return OutdatedItem(
            item_type="document", id=document.id, title=document.title, reason="new_version",
            detail=f"Nouvelle version disponible (v{version} → v{document.current_version})",
        )  # fmt: skip
    source = await session.get(Source, document.source_id)
    limit = freshness.policy_days(source.kind if source else None, policy)
    age = freshness.whole_days(document.source_updated_at, now)
    if limit is not None and age is not None and age > limit:
        return OutdatedItem(
            item_type="document", id=document.id, title=document.title, reason="stale",
            detail=f"Périmé : {age} j > {limit} j",
        )  # fmt: skip
    return None


# --- Digest ----------------------------------------------------------------------------------------


async def build_digest(
    session: AsyncSession,
    viewer: FeedViewer,
    period: Literal["day", "week"],
    *,
    types: Sequence[str] | None = None,
    project_name: str = "",
    until: datetime | None = None,
) -> Digest:
    until = until or utcnow()
    since = until - PERIODS[period]
    conditions = _conditions(viewer, since, types, until)
    counts = dict(
        (
            await session.execute(
                select(ChangeEvent.type, func.count()).where(*conditions).group_by(ChangeEvent.type)
            )
        ).all()
    )
    groups: list[DigestGroup] = []
    for change_type in ChangeType:
        count = int(counts.get(change_type.value, 0))
        if not count:
            continue
        rows = await session.scalars(
            select(ChangeEvent)
            .where(*conditions, ChangeEvent.type == change_type.value)
            .order_by(ChangeEvent.created_at.desc())
            .limit(DIGEST_GROUP_LIMIT)
        )
        groups.append(
            DigestGroup(
                type=change_type.value,
                label=type_label(change_type.value),
                count=count,
                items=[to_out(row) for row in rows],
            )
        )
    total = sum(group.count for group in groups)
    return Digest(
        period=period,
        since=since,
        until=until,
        total=total,
        groups=groups,
        text=digest_text(project_name, period, groups, total),
        email_enabled=smtp_configured(),
    )


def digest_text(project_name: str, period: str, groups: Sequence[DigestGroup], total: int) -> str:
    label = "dernières 24 heures" if period == "day" else "7 derniers jours"
    lines = [f"ORBIT — {project_name or 'Projet'} : changements des {label}", ""]
    if not total:
        lines.append("Aucun changement sur la période.")
    for group in groups:
        lines.append(f"{group.label} ({group.count})")
        for item in group.items:
            lines.append(f"  • {item.title}")
        if group.count > len(group.items):
            lines.append(f"  … et {group.count - len(group.items)} autre(s)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_port and settings.smtp_from)


def _send_mail_sync(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


async def send_mail(to: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_send_mail_sync, to, subject, body)


async def send_due_digests(session: AsyncSession, now: datetime | None = None) -> int:
    """E-mail the digests that are due (only when SMTP is configured). Returns the number sent."""
    if not smtp_configured():
        return 0
    now = now or utcnow()
    rows = (
        await session.execute(
            select(Subscription, User, Project, ProjectMember.role)
            .join(User, User.id == Subscription.user_id)
            .join(Project, Project.id == Subscription.project_id)
            .join(
                ProjectMember,
                and_(ProjectMember.project_id == Subscription.project_id, ProjectMember.user_id == User.id),
                isouter=True,
            )
            .where(Subscription.digest.in_(list(DIGEST_FREQUENCIES)))
        )
    ).all()
    sent = 0
    for subscription, user, project, role in rows:
        period = DIGEST_FREQUENCIES[subscription.digest]
        last = subscription.last_digest_at
        if last is not None and now - last < PERIODS[period]:
            continue
        if role is None and not user.is_admin:
            continue  # no longer a member
        if not getattr(user, "is_active", True):
            continue
        viewer = FeedViewer(
            project.id,
            frozenset(principals_for_member(user.id, role or Role.owner)),
            int(user.clearance),
        )
        digest = await build_digest(
            session, viewer, period, types=subscription.types or None, project_name=project.name, until=now
        )
        subscription.last_digest_at = now
        if not digest.total:
            continue
        try:
            await send_mail(user.email, f"[ORBIT] {project.name} — {digest.total} changement(s)", digest.text)
        except Exception:  # SMTP failures must not block the maintenance loop
            logger.exception("Digest e-mail to user %s failed", user.id)
            continue
        sent += 1
    await session.flush()
    return sent


# --- Stale documents --------------------------------------------------------------------------------


async def detect_stale_documents(session: AsyncSession, now: datetime | None = None) -> int:
    """Emit ``document.stale`` (audited) once per document version exceeding the project freshness policy."""
    now = now or utcnow()
    rows = (
        await session.execute(
            select(Document, Source.kind, Project.settings)
            .join(Source, Source.id == Document.source_id)
            .join(Project, Project.id == Document.project_id)
            .where(Document.status == DocumentStatus.indexed)
            .order_by(Document.source_updated_at)
        )
    ).all()
    emitted = 0
    for document, kind, raw_settings in rows:
        policy = project_service.normalize_settings(raw_settings)["freshness_days"]
        limit = freshness.policy_days(kind, policy)
        age = freshness.whole_days(document.source_updated_at, now)
        if limit is None or age is None or age <= limit:
            continue
        already = await session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(
                ChangeEvent.project_id == document.project_id,
                ChangeEvent.type == ChangeType.document_stale.value,
                ChangeEvent.target_id == str(document.id),
                ChangeEvent.data["version"].astext == str(document.current_version),
            )
        )
        if already:
            continue
        await audit.record(
            session,
            document.project_id,
            None,
            audit.AuditAction.document_stale,
            "document",
            document.id,
            summary=f"« {document.title} » est périmé ({age} j > {limit} j)",
            details={"age_days": age, "limit_days": limit, "version": document.current_version},
        )
        await session.flush()
        emitted += 1
        if emitted >= STALE_BATCH:
            break
    return emitted


async def run_feed_maintenance(session: AsyncSession) -> dict[str, int]:
    summary = {"stale_documents": await detect_stale_documents(session)}
    summary["digests_sent"] = await send_due_digests(session)
    return {k: v for k, v in summary.items() if v}

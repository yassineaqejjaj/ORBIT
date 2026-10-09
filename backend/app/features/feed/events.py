"""Change events: written with the audited action (hook in ``services.audit.record``), filtered by rights.

Each event copies the classification and ACL of its target so the feed obeys the same governance as
the context engine. User-scope and short-term memory never produce events (private / ephemeral).
Forgetting a target scrubs the titles of its earlier events.

The hook never flushes the session (``no_autoflush``; ids assigned in Python): it can run at any
point of the caller's transaction.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, cast, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from app.db import utcnow
from app.enums import MEMORY_KIND_LABELS, JobKind, JobStatus, MemoryKind, MemoryScope
from app.features.feed.types import OPT_IN_TYPES, ChangeType
from app.governance.acl import PROJECT_ALL
from app.models import ContextSnapshot, Document, IngestionJob, MemoryItem, Project
from app.models.features_feed import ChangeEvent, Webhook, WebhookDelivery

logger = logging.getLogger("orbit.feed")

#: Memory kinds whose creation is announced in the feed.
ANNOUNCED_KINDS = frozenset({MemoryKind.decision, MemoryKind.constraint})
PRIVATE_SCOPES = frozenset({MemoryScope.user, MemoryScope.short_term})
RESTRICTED_TITLE = "Élément restreint"
FORGOTTEN_TITLE = "Élément oublié"
#: Classification above which webhook payloads only carry ids (docs/FEATURES.md).
PUBLIC_MAX_CLASSIFICATION = 1
WEBHOOK_MAX_ATTEMPTS = 6


def _quote(title: str, limit: int = 90) -> str:
    title = " ".join((title or "").split())
    if len(title) > limit:
        title = title[: limit - 1].rstrip() + "…"
    return f"« {title} »"


def _kind_label(kind: Any) -> str:
    try:
        return MEMORY_KIND_LABELS[MemoryKind(kind)]
    except ValueError:
        return "Mémoire"


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return None


async def _find[T](session: AsyncSession, model: type[T], ident: Any) -> T | None:
    key = _uuid(ident)
    if key is None:
        return None
    for obj in session.new:
        if isinstance(obj, model) and getattr(obj, "id", None) == key:
            return obj
    return await session.get(model, key)


@dataclass(slots=True)
class Draft:
    type: ChangeType
    title: str
    summary: str
    target_type: str
    target_id: str | None
    classification: int
    acl_principals: list[str]
    data: dict[str, Any]


def _memory_draft(item: MemoryItem, type_: ChangeType, title: str, summary: str, **data: Any) -> Draft | None:
    if MemoryScope(item.scope) in PRIVATE_SCOPES or item.project_id is None:
        return None
    payload = {"lineage_id": str(item.lineage_id), "kind": str(item.kind), "version": item.version}
    payload.update({k: v for k, v in data.items() if v is not None})
    return Draft(
        type=type_,
        title=title,
        summary=summary,
        target_type="memory",
        target_id=str(item.id),
        classification=int(item.classification),
        acl_principals=list(item.acl_principals or [PROJECT_ALL]),
        data=payload,
    )


def _document_draft(document: Document, type_: ChangeType, title: str, summary: str, **data: Any) -> Draft:
    return Draft(
        type=type_,
        title=title,
        summary=summary,
        target_type="document",
        target_id=str(document.id),
        classification=int(document.classification),
        acl_principals=list(document.acl_principals or [PROJECT_ALL]),
        data={"version": document.current_version, **{k: v for k, v in data.items() if v is not None}},
    )


async def _draft_for(
    session: AsyncSession,
    action: str,
    actor_label: str,
    target_id: Any,
    summary: str,
    details: Mapping[str, Any],
) -> Draft | None:
    if action.startswith("memory."):
        item = await _find(session, MemoryItem, target_id)
        if item is None:
            return None
        kind = _kind_label(item.kind)
        if action == "memory.create":
            if MemoryKind(item.kind) not in ANNOUNCED_KINDS:
                return None
            return _memory_draft(
                item,
                ChangeType.memory_created,
                f"{kind} : {item.title}",
                f"{kind} {_quote(item.title)} ajoutée ({item.status}) par {actor_label}",
            )
        if action == "memory.validate":
            return _memory_draft(
                item,
                ChangeType.memory_validated,
                f"{kind} validée : {item.title}",
                f"{_quote(item.title)} validé par {actor_label}",
            )
        if action == "memory.supersede":
            new = await _find(session, MemoryItem, details.get("by_id"))
            by = f" par {_quote(new.title)}" if new is not None else ""
            return _memory_draft(
                item,
                ChangeType.memory_superseded,
                f"{kind} remplacée : {item.title}",
                f"{_quote(item.title)} remplacé{by}" + (" (automatique)" if details.get("auto") else ""),
                by_id=str(new.id) if new is not None else None,
            )
        if action == "memory.obsolete":
            reason = details.get("reason")
            return _memory_draft(
                item,
                ChangeType.memory_obsoleted,
                f"{kind} obsolète : {item.title}",
                f"{_quote(item.title)} marqué obsolète par {actor_label}"
                + (f" — {reason}" if reason else ""),
            )
        if action == "memory.forget":
            return _memory_draft(
                item,
                ChangeType.memory_forgotten,
                f"{kind} oubliée",
                f"Oubli sélectif demandé par {actor_label}",
            )
        if action == "memory.conflict":
            ids = list(details.get("items") or [])
            other = await _find(session, MemoryItem, ids[1]) if len(ids) > 1 else None
            draft = _memory_draft(
                item,
                ChangeType.memory_conflict_detected,
                f"Contradiction : {item.title}",
                f"{_quote(item.title)} contredit "
                + (_quote(other.title) if other is not None else "un autre item"),
                with_id=str(other.id) if other is not None else None,
            )
            if draft is not None and other is not None:
                draft.classification = max(draft.classification, int(other.classification))
                if MemoryScope(other.scope) in PRIVATE_SCOPES:
                    return None
            return draft
        if action == "memory.conflict_resolved":
            loser = await _find(session, MemoryItem, details.get("loser_id"))
            draft = _memory_draft(
                item,
                ChangeType.memory_conflict_resolved,
                f"Contradiction arbitrée : {item.title}",
                f"{_quote(item.title)} conservé"
                + (f", {_quote(loser.title)} remplacé" if loser is not None else "")
                + f" par {actor_label}",
                loser_id=str(loser.id) if loser is not None else None,
            )
            if draft is not None and loser is not None:
                draft.classification = max(draft.classification, int(loser.classification))
            return draft
        return None
    if action.startswith("document."):
        if action not in ("document.indexed", "document.forget", "document.stale"):
            return None
        document = await _find(session, Document, target_id)
        if document is None:
            return None
        if action == "document.indexed":
            version = int(details.get("version") or document.current_version or 1)
            if version > 1:
                return _document_draft(
                    document,
                    ChangeType.document_new_version,
                    f"Nouvelle version : {document.title}",
                    f"{_quote(document.title)} mis à jour "
                    f"(v{version}, {details.get('chunks', 0)} fragment(s))",
                    version=version,
                )
            return _document_draft(
                document,
                ChangeType.document_ingested,
                f"Document ingéré : {document.title}",
                f"{_quote(document.title)} indexé ({details.get('chunks', 0)} fragment(s))",
                version=version,
            )
        if action == "document.forget":
            return _document_draft(
                document,
                ChangeType.document_forgotten,
                "Document oublié",
                f"Oubli sélectif demandé par {actor_label}",
            )
        return _document_draft(
            document,
            ChangeType.document_stale,
            f"Document périmé : {document.title}",
            summary or f"{_quote(document.title)} dépasse la durée de fraîcheur du projet",
            age_days=details.get("age_days"),
            limit_days=details.get("limit_days"),
        )
    if action == "snapshot.create":
        snapshot = await _find(session, ContextSnapshot, details.get("snapshot_id"))
        if snapshot is None:
            return None
        return Draft(
            type=ChangeType.snapshot_created,
            title=f"Snapshot « {snapshot.name} » v{snapshot.version}",
            summary=f"Snapshot « {snapshot.name} » v{snapshot.version} enregistré par {actor_label}",
            target_type="snapshot",
            target_id=str(snapshot.id),
            classification=0,
            acl_principals=[PROJECT_ALL],
            data={"name": snapshot.name, "version": snapshot.version},
        )
    if action in ("connector.sync", "connector.synced"):
        return Draft(
            type=ChangeType.connector_synced,
            title="Connecteur synchronisé",
            summary=summary,
            target_type="connector",
            target_id=str(target_id) if target_id is not None else None,
            classification=0,
            acl_principals=[PROJECT_ALL],
            data={k: details[k] for k in ("documents", "created", "updated", "failed") if k in details},
        )
    return None


async def on_audit(
    session: AsyncSession,
    project_id: uuid.UUID,
    actor_label: str,
    action: str,
    target_type: str,
    target_id: Any,
    summary: str,
    details: Mapping[str, Any],
) -> ChangeEvent | None:
    """Hook called by ``services.audit.record``: add the matching change event (and its deliveries)."""
    try:
        with session.no_autoflush:
            draft = await _draft_for(session, action, actor_label, target_id, summary, details)
            if draft is None:
                if action in ("memory.forget", "document.forget"):
                    await scrub(session, project_id, target_id)
                return None
            if draft.type in (ChangeType.memory_forgotten, ChangeType.document_forgotten):
                await scrub(session, project_id, target_id, lineage_id=draft.data.get("lineage_id"))
            return await emit(session, project_id, draft, actor_label)
    except Exception:  # the feed must never break the audited action
        logger.exception("Unable to record the change event of %s", action)
        return None


async def emit(session: AsyncSession, project_id: uuid.UUID, draft: Draft, actor_label: str) -> ChangeEvent:
    event = ChangeEvent(
        id=uuid.uuid4(),
        project_id=project_id,
        type=draft.type.value,
        title=draft.title[:300],
        summary=draft.summary[:1000],
        target_type=draft.target_type,
        target_id=draft.target_id,
        classification=draft.classification,
        acl_principals=draft.acl_principals,
        actor_label=actor_label,
        data=draft.data,
        created_at=utcnow(),
    )
    session.add(event)
    await enqueue_deliveries(session, event)
    return event


async def scrub(
    session: AsyncSession, project_id: uuid.UUID, target_id: Any, *, lineage_id: str | None = None
) -> None:
    """Forgetting: earlier events of the target keep their type and ids but lose their wording."""
    conditions: list[ColumnElement[bool]] = [ChangeEvent.target_id == str(target_id)]
    if lineage_id:
        conditions.append(ChangeEvent.data["lineage_id"].astext == str(lineage_id))
    await session.execute(
        update(ChangeEvent)
        .where(ChangeEvent.project_id == project_id, or_(*conditions))
        .values(title=FORGOTTEN_TITLE, summary="")
        .execution_options(synchronize_session=False)
    )


# --- Visibility & serialization -------------------------------------------------------------------------


def visibility_clause(principals: frozenset[str] | set[str], clearance: int) -> ColumnElement[bool]:
    values = sorted(principals) or ["__none__"]
    return and_(
        ChangeEvent.classification <= clearance,
        ChangeEvent.acl_principals.overlap(cast(array(values), ARRAY(Text))),
    )


def is_public(event: ChangeEvent) -> bool:
    return int(event.classification) <= PUBLIC_MAX_CLASSIFICATION and PROJECT_ALL in (
        event.acl_principals or []
    )


def webhook_payload(event: ChangeEvent, project: Project | None) -> dict[str, Any]:
    """Payload redacted at the ``project:*`` level: no C2+ nor ACL-restricted wording."""
    public = is_public(event)
    created: datetime = event.created_at or utcnow()
    payload: dict[str, Any] = {
        "id": str(event.id),
        "type": event.type,
        "project": {"id": str(event.project_id), "slug": project.slug if project else None},
        "target_type": event.target_type,
        "target_id": event.target_id,
        "created_at": created.isoformat(),
        "restricted": not public,
        "title": event.title if public else RESTRICTED_TITLE,
        "summary": event.summary if public else "",
    }
    if public and event.type == ChangeType.context_served.value:
        # ids and counters only: neither the requester's name nor any content
        payload["title"] = "Contexte servi"
        payload["summary"] = ""
        payload["data"] = {k: v for k, v in (event.data or {}).items() if not isinstance(v, dict | list)}
    elif public:
        payload["actor"] = event.actor_label
        payload["data"] = {k: v for k, v in (event.data or {}).items() if not isinstance(v, dict | list)}
    return payload


async def enqueue_deliveries(session: AsyncSession, event: ChangeEvent) -> int:
    """One delivery + one ``webhook`` job per enabled webhook subscribed to the event type."""
    hooks = list(
        await session.scalars(
            select(Webhook).where(Webhook.project_id == event.project_id, Webhook.enabled.is_(True))
        )
    )
    # Opt-in types (context.served) need an explicit selection: an empty list means « all other types ».
    targets = [
        hook
        for hook in hooks
        if (event.type in hook.types if event.type in OPT_IN_TYPES else (not hook.types or event.type in hook.types))
    ]
    if not targets:
        return 0
    project = await session.get(Project, event.project_id)
    payload = webhook_payload(event, project)
    for hook in targets:
        queue_delivery(session, hook, event.type, payload, change_event_id=event.id)
    return len(targets)


def queue_delivery(
    session: AsyncSession,
    hook: Webhook,
    event_type: str,
    payload: dict[str, Any],
    *,
    change_event_id: uuid.UUID | None = None,
) -> WebhookDelivery:
    delivery = WebhookDelivery(
        id=uuid.uuid4(),
        webhook_id=hook.id,
        project_id=hook.project_id,
        change_event_id=change_event_id,
        event_type=event_type,
        status="pending",
        attempts=0,
        payload=payload,
        created_at=utcnow(),
    )
    session.add(delivery)
    session.add(
        IngestionJob(
            id=uuid.uuid4(),
            project_id=hook.project_id,
            kind=JobKind.webhook,
            status=JobStatus.queued,
            attempts=0,
            max_attempts=WEBHOOK_MAX_ATTEMPTS,
            payload={"delivery_id": str(delivery.id), "webhook_id": str(hook.id)},
            steps=[],
            run_after=utcnow(),
        )
    )
    return delivery

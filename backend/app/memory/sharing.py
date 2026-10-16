"""Collective intelligence (ORION): share a validated learning with other projects, within access rights.

A learning verified in one project may help another. Sharing never moves or exposes the original: it creates
an independent **proposal** in each target project (the target's own people validate it, with the same
evidence), tied to its origin by ``learning_meta.shared_from``. Guardrails:

* only a human who is an editor of the source *and* of every target (or a platform admin) can share; an agent
  key is bound to one project and cannot;
* only a validated, current learning visible to the caller, at classification C0-C1 and open to the whole
  project (a restricted ACL is project-specific and does not travel): C2/C3 knowledge is never shared;
* the request is all-or-nothing: if one target is unknown or not editable by the caller, nothing is created;
* sharing again is a no-op for a project that already holds a copy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import ProjectAccess
from app.enums import MemoryKind, MemoryScope, MemoryStatus, Role, role_at_least
from app.errors import forbidden, not_found, validation_error
from app.governance.acl import PROJECT_ALL
from app.memory import lifecycle
from app.memory.visibility import MemoryViewer, can_view
from app.models import MemoryItem
from app.schemas.memory import MemoryIn, ProvenanceIn
from app.services import projects as project_service
from app.services import workspaces

MAX_SHAREABLE_CLASSIFICATION = 1


async def share_learning(
    session: AsyncSession, access: ProjectAccess, memory_id: Any, targets: list[str], note: str | None
) -> list[dict[str, Any]]:
    principal = access.principal
    if not principal.is_user:
        raise forbidden("Seul un utilisateur peut partager un apprentissage entre projets")
    item = await session.get(MemoryItem, memory_id)
    if (
        item is None
        or item.project_id != access.project_id
        or not can_view(item, MemoryViewer.from_access(access))
        or MemoryKind(item.kind) != MemoryKind.learning
    ):
        raise not_found("Apprentissage introuvable")
    if not item.is_current or MemoryStatus(item.status) != MemoryStatus.validated:
        raise validation_error("Seul un apprentissage validé (version courante) peut être partagé")
    if int(item.classification) > MAX_SHAREABLE_CLASSIFICATION:
        raise validation_error("Le partage entre projets est interdit au-delà de C1 (données C2/C3)")
    if PROJECT_ALL not in item.acl_principals:
        raise validation_error("Un apprentissage à accès restreint ne peut pas être partagé")

    slugs = list(dict.fromkeys(s.strip() for s in targets if s and s.strip()))
    if access.project.slug in slugs:
        raise validation_error("Le projet source ne peut pas être sa propre cible")
    projects = []
    for slug in slugs:
        target = await project_service.get_by_slug(session, slug)
        role = (
            await project_service.get_member_role(session, target.id, principal.user.id)
            if target and principal.user
            else None
        )
        if (
            target is not None
            and principal.user is not None
            and not workspaces.allows(principal.workspace_id, target.workspace_id, surface="project")
        ):
            target = None  # a project of another workspace answers like an unknown one
        if target is None or (role is None and not principal.is_admin):
            raise not_found(
                f"Projet « {slug} » introuvable"
            )  # same answer for unknown and not-yours (non-leak)
        if not principal.is_admin and not role_at_least(role, Role.editor):
            raise forbidden(f"Vous devez être éditeur du projet « {slug} » pour y partager un apprentissage")
        projects.append(target)

    results: list[dict[str, Any]] = []
    for target in projects:
        existing = await session.scalar(
            select(MemoryItem).where(
                MemoryItem.project_id == target.id,
                MemoryItem.kind == MemoryKind.learning,
                MemoryItem.is_current.is_(True),
                MemoryItem.learning_meta["shared_from"]["lineage_id"].astext == str(item.lineage_id),
            )
        )
        if existing is not None:
            results.append({"project": target.slug, "status": "already_shared", "item_id": existing.id})
            continue
        meta = {
            **(item.learning_meta or {}),
            "shared_from": {
                "project": access.project.slug,
                "memory_id": str(item.id),
                "lineage_id": str(item.lineage_id),
                "shared_by": principal.label,
                "shared_at": datetime.now(UTC).isoformat(),
            },
        }
        created = await lifecycle.create_item(
            session,
            project_id=target.id,
            data=MemoryIn(
                scope=MemoryScope.project,
                kind=MemoryKind.learning,
                title=item.title,
                content=item.content,
                classification=int(item.classification),
                tags=[*dict.fromkeys([*item.tags, "shared"])],
                provenance=[
                    ProvenanceIn(
                        source_label=f"Partagé depuis le projet {access.project.slug}"[:300],
                        excerpt=(note or "")[:4000] or None,
                    )
                ],
            ),
            actor=principal.actor,
            force_status=MemoryStatus.proposed.value,
            learning_meta=meta,
        )
        results.append({"project": target.slug, "status": "created", "item_id": created.id})
    return results

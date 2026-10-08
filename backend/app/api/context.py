"""Context assembly endpoints (API.md « Contexte »). The engine lives in ``app.context``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.context import persistence, profiles
from app.context.assembler import assemble_context
from app.context.visibility import Viewer
from app.deps import AgentViewerAccess, OwnerAccess, ProjectAccess, SessionDep, ViewerAccess
from app.enums import AgentKind, PrincipalKind
from app.errors import not_found
from app.schemas import (
    ContextPackage,
    ContextRequestDetail,
    ContextRequestIn,
    ContextRequestSummary,
    FeedbackIn,
    IdOut,
    Page,
    PageParams,
    page_params,
)
from app.schemas.context import AppliedProfile, ContextProfileIn, ContextProfileView, ProfileSuggestion
from app.services import audit

router = APIRouter(prefix="/projects/{slug}/context", tags=["context"])


@router.post("", response_model=ContextPackage, summary="Assembler un contexte gouverné")
async def request_context(
    body: ContextRequestIn, access: AgentViewerAccess, session: SessionDep
) -> ContextPackage:
    """Humans get the full explanation by default; agents only exclusion counters (``explain=false``)."""
    return await assemble_context(session, access, body)


@router.get(
    "/profiles", response_model=list[ContextProfileView], summary="Profils de contexte par type d'agent"
)
async def list_profiles(access: ViewerAccess, session: SessionDep) -> list[ContextProfileView]:
    """§C3: effective profile, built-in default and the adjustment suggested by the feedback."""
    return [await _profile_view(session, access, kind) for kind in AgentKind]


@router.put("/profiles/{kind}", response_model=ContextProfileView, summary="Modifier un profil de contexte")
async def update_profile(
    kind: AgentKind, body: ContextProfileIn, access: OwnerAccess, session: SessionDep
) -> ContextProfileView:
    before = profiles.profile_for(access.project, kind).as_dict()
    profile = profiles.Profile(kind=kind, **body.model_dump())
    profiles.store(access.project, profile)
    await _audit_profile(session, access, kind, before, profile.as_dict())
    await session.commit()
    return await _profile_view(session, access, kind)


@router.delete("/profiles/{kind}", response_model=ContextProfileView, summary="Réinitialiser un profil")
async def reset_profile(kind: AgentKind, access: OwnerAccess, session: SessionDep) -> ContextProfileView:
    before = profiles.profile_for(access.project, kind).as_dict()
    profiles.reset(access.project, kind)
    await _audit_profile(session, access, kind, before, profiles.profile_for(access.project, kind).as_dict())
    await session.commit()
    return await _profile_view(session, access, kind)


async def _profile_view(session: SessionDep, access: ProjectAccess, kind: AgentKind) -> ContextProfileView:
    profile = profiles.profile_for(access.project, kind)
    suggestion = await profiles.suggest(session, access.project, kind)
    return ContextProfileView(
        **profile.as_dict(),
        default=AppliedProfile(**profiles.DEFAULTS[kind].as_dict()),
        suggestion=ProfileSuggestion(**suggestion.as_dict()),
    )


async def _audit_profile(
    session: SessionDep,
    access: ProjectAccess,
    kind: AgentKind,
    before: dict,
    after: dict,  # type: ignore[type-arg]
) -> None:
    await audit.record(
        session,
        access.project_id,
        access.principal,
        audit.AuditAction.project_update,
        target_type="project",
        target_id=access.project_id,
        summary=f"Profil de contexte « {kind.value} » modifié",
        details={"context_profile": kind.value, "before": before, "after": after},
    )


@router.get(
    "/requests", response_model=Page[ContextRequestSummary], summary="Historique des requêtes de contexte"
)
async def list_context_requests(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    agent_id: uuid.UUID | None = Query(default=None),
) -> Page[ContextRequestSummary]:
    return await persistence.list_requests(session, access.project_id, params, agent_id=agent_id)


@router.get(
    "/requests/{request_id}", response_model=ContextRequestDetail, summary="Requête de contexte reconstituée"
)
async def get_context_request(
    request_id: uuid.UUID, access: ViewerAccess, session: SessionDep
) -> ContextRequestDetail:
    request = await persistence.get_request(session, access.project_id, request_id)
    return await persistence.reconstitute(session, request, Viewer.from_access(access))


@router.post("/requests/{request_id}/feedback", response_model=IdOut, summary="Évaluer un contexte servi")
async def send_feedback(
    request_id: uuid.UUID, body: FeedbackIn, access: AgentViewerAccess, session: SessionDep
) -> IdOut:
    principal = access.principal
    request = await persistence.get_request(session, access.project_id, request_id)
    served_to_caller = principal.id in (request.agent_id, request.requested_by_id)
    if principal.is_agent and not served_to_caller:
        # An agent may only rate the contexts it was served (non-leak: same answer as an unknown id).
        raise not_found("Requête de contexte introuvable")
    feedback = await persistence.record_feedback(
        session,
        request,
        body,
        actor=principal,
        actor_kind=PrincipalKind.agent if principal.is_agent else PrincipalKind.user,
    )
    flags = [f"{f.citation}:{f.flag.value}" for f in body.item_flags or []]
    await audit.record(
        session,
        access.project_id,
        principal,
        audit.AuditAction.context_feedback,
        target_type="context_request",
        target_id=request.id,
        summary=(
            f"Évaluation {body.rating}/5 du contexte « {_preview(request.task)} »"
            + (f" ({len(flags)} signalement{'s' if len(flags) > 1 else ''})" if flags else "")
        ),
        details={"feedback_id": feedback.id, "rating": body.rating, "item_flags": flags},
    )
    await session.commit()
    return IdOut(id=feedback.id)


def _preview(task: str, limit: int = 80) -> str:
    task = " ".join((task or "").split())
    return task if len(task) <= limit else task[: limit - 1] + "…"

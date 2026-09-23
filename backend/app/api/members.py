"""Project members (owners manage them; the last owner cannot be removed or demoted)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.deps import OwnerAccess, SessionDep, ViewerAccess
from app.enums import ROLE_LABELS, Role
from app.errors import conflict, not_found
from app.models import ProjectMember, User
from app.schemas import Member, MemberAddIn, MemberUpdateIn
from app.schemas import User as UserOut
from app.services import audit
from app.services import projects as project_service
from app.services import users as user_service
from app.services.audit import AuditAction

router = APIRouter(prefix="/projects/{slug}/members", tags=["members"])

LAST_OWNER_MESSAGE = "Impossible de retirer le dernier propriétaire du projet"


def _member_out(member: ProjectMember, user: User) -> Member:
    return Member(user=UserOut.model_validate(user), role=member.role, created_at=member.created_at)


async def _load(session: SessionDep, project_id: uuid.UUID, user_id: uuid.UUID) -> tuple[ProjectMember, User]:
    member = await project_service.get_member(session, project_id, user_id)
    user = await session.get(User, user_id) if member else None
    if member is None or user is None:
        raise not_found("Membre introuvable")
    return member, user


@router.get("", response_model=list[Member], summary="Membres du projet")
async def list_members(access: ViewerAccess, session: SessionDep) -> list[Member]:
    return [_member_out(m, u) for m, u in await project_service.list_members(session, access.project_id)]


@router.post("", response_model=Member, status_code=status.HTTP_201_CREATED, summary="Ajouter un membre")
async def add_member(body: MemberAddIn, access: OwnerAccess, session: SessionDep) -> Member:
    user = await user_service.get_by_email(session, body.email)
    if user is None:
        raise not_found("Aucun utilisateur ne correspond à cette adresse e-mail")
    if await project_service.get_member(session, access.project_id, user.id):
        raise conflict("Cet utilisateur est déjà membre du projet")
    member = ProjectMember(project_id=access.project_id, user_id=user.id, role=body.role)
    session.add(member)
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.member_add,
        "user",
        user.id,
        summary=f"Ajout de {user.full_name} comme {ROLE_LABELS[body.role].lower()}",
        details={"role": body.role, "email": user.email},
    )
    await session.commit()
    return _member_out(member, user)


@router.patch("/{user_id}", response_model=Member, summary="Changer le rôle d'un membre")
async def update_member(
    user_id: uuid.UUID, body: MemberUpdateIn, access: OwnerAccess, session: SessionDep
) -> Member:
    member, user = await _load(session, access.project_id, user_id)
    if member.role == body.role:
        return _member_out(member, user)
    if member.role == Role.owner and await project_service.count_owners(session, access.project_id) <= 1:
        raise conflict(LAST_OWNER_MESSAGE)
    previous = member.role
    member.role = body.role
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.member_update,
        "user",
        user.id,
        summary=(
            f"Rôle de {user.full_name} : {ROLE_LABELS[previous].lower()} → {ROLE_LABELS[body.role].lower()}"
        ),
        details={"from": previous, "to": body.role},
    )
    await session.commit()
    return _member_out(member, user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Retirer un membre")
async def remove_member(user_id: uuid.UUID, access: OwnerAccess, session: SessionDep) -> Response:
    member, user = await _load(session, access.project_id, user_id)
    if member.role == Role.owner and await project_service.count_owners(session, access.project_id) <= 1:
        raise conflict(LAST_OWNER_MESSAGE)
    await session.delete(member)
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.member_remove,
        "user",
        user.id,
        summary=f"Retrait de {user.full_name} du projet",
        details={"role": member.role},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

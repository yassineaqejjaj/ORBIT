"""Platform user administration (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import or_, select

from app.deps import AdminUser, SessionDep
from app.errors import conflict, not_found
from app.models import User
from app.schemas import User as UserOut
from app.schemas import UserCreateIn, UserUpdateIn
from app.security import hash_password
from app.services import audit
from app.services import users as user_service
from app.services.audit import AuditAction

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut], summary="Lister les utilisateurs")
async def list_users(
    admin: AdminUser,
    session: SessionDep,
    q: str | None = Query(default=None, max_length=200, description="Filtre sur l'e-mail ou le nom"),
) -> list[UserOut]:
    stmt = select(User).order_by(User.full_name, User.email).limit(500)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
    rows = await session.scalars(stmt)
    return [UserOut.model_validate(u) for u in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Créer un utilisateur")
async def create_user(body: UserCreateIn, admin: AdminUser, session: SessionDep) -> UserOut:
    if await user_service.get_by_email(session, body.email):
        raise conflict("Un utilisateur existe déjà avec cette adresse e-mail")
    user = await user_service.create_user(
        session,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
        clearance=body.clearance,
        is_admin=body.is_admin,
    )
    await audit.record(
        session,
        None,
        admin,
        AuditAction.user_create,
        "user",
        user.id,
        summary=f"Création de l'utilisateur {user.full_name} ({user.email})",
        details={"clearance": user.clearance, "is_admin": user.is_admin},
    )
    await session.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut, summary="Modifier un utilisateur")
async def update_user(
    user_id: uuid.UUID, body: UserUpdateIn, admin: AdminUser, session: SessionDep
) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("Utilisateur introuvable")
    changes: dict[str, object] = {}
    if body.full_name is not None and body.full_name != user.full_name:
        user.full_name = body.full_name
        changes["full_name"] = body.full_name
    if body.clearance is not None and body.clearance != user.clearance:
        changes["clearance"] = {"from": user.clearance, "to": body.clearance}
        user.clearance = body.clearance
    if body.is_admin is not None and body.is_admin != user.is_admin:
        if not body.is_admin and await user_service.count_admins(session) <= 1:
            raise conflict("Impossible de retirer le dernier administrateur de la plateforme")
        changes["is_admin"] = body.is_admin
        user.is_admin = body.is_admin
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        changes["password"] = "modifié"
    if changes:
        await audit.record(
            session,
            None,
            admin,
            AuditAction.user_update,
            "user",
            user.id,
            summary=f"Modification de l'utilisateur {user.full_name}",
            details={"changes": changes},
        )
        await session.commit()
    return UserOut.model_validate(user)

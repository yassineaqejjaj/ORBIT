"""FastAPI dependencies: sessions, authenticated principal, project access control.

Two kinds of callers exist (ARCHITECTURE §3):

* **users** — session cookie ``orbit_session`` or ``Authorization: Bearer <jwt>``; the JWT ``sid`` must
  reference a live server-side session (``user_sessions``: not revoked, absolute and idle expiry);
* **agents** — API key ``orb_…`` via ``Authorization: Bearer orb_…`` or ``X-Orbit-Key``.

Every authenticated request counts against a per-principal sliding window (``ORBIT_RATE_LIMIT_API`` for
users, ``ORBIT_RATE_LIMIT_AGENT`` for agents); failed agent-key authentications are limited per client IP.

Every router and the context engine reason about a :class:`Principal`. Project-scoped endpoints use
:func:`require_project` (or the ``*Access`` aliases) which resolve ``{slug}`` into a
:class:`ProjectAccess` carrying the caller's effective role:

* members get their membership role, platform admins are ``owner`` everywhere;
* agents get ``editor`` on **their own project only** and are only accepted on endpoints declared
  with ``agents=True`` (the endpoints marked *(agent)* in docs/API.md).

Non-members receive ``404`` (the project's existence is not revealed); insufficient roles ``403``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import Depends, Path, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.config import settings
from app.db import get_session, utcnow
from app.enums import ActorType, Role, role_at_least
from app.errors import ApiError, forbidden, not_found, unauthorized
from app.identity import ratelimit
from app.identity import sessions as session_service
from app.identity.netutil import client_ip
from app.models import Agent, Project, User
from app.security import (
    API_KEY_HEADER,
    SESSION_COOKIE_NAME,
    TokenError,
    decode_access_token,
    hash_api_key,
    looks_like_api_key,
    parse_api_key,
    password_fingerprint,
    verify_api_key,
)
from app.services import projects as project_service
from app.services.audit import Actor

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: ``last_used_at`` is written at most once per interval per agent (avoids a write on every call).
AGENT_LAST_USED_RESOLUTION = timedelta(seconds=30)
#: Failed agent-key authentications allowed per client IP: ``ORBIT_RATE_LIMIT_LOGIN`` × this factor.
AGENT_AUTH_FAILURE_FACTOR = 4


@dataclass(slots=True)
class Principal:
    """Authenticated caller (human user or AI agent)."""

    kind: Literal["user", "agent"]
    user: User | None
    agent: Agent | None
    is_admin: bool
    clearance: int
    label: str

    @classmethod
    def for_user(cls, user: User) -> Principal:
        return cls(
            kind="user",
            user=user,
            agent=None,
            is_admin=bool(user.is_admin),
            clearance=int(user.clearance),
            label=user.full_name or user.email,
        )

    @classmethod
    def for_agent(cls, agent: Agent) -> Principal:
        return cls(
            kind="agent",
            user=None,
            agent=agent,
            is_admin=False,
            clearance=int(agent.clearance),
            label=agent.name,
        )

    @property
    def is_user(self) -> bool:
        return self.kind == "user"

    @property
    def is_agent(self) -> bool:
        return self.kind == "agent"

    @property
    def id(self) -> uuid.UUID:
        if self.user is not None:
            return self.user.id
        assert self.agent is not None
        return self.agent.id

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user is not None else None

    @property
    def agent_id(self) -> uuid.UUID | None:
        return self.agent.id if self.agent is not None else None

    @property
    def actor_type(self) -> ActorType:
        return ActorType.user if self.is_user else ActorType.agent

    @property
    def actor(self) -> Actor:
        """Audit actor for this principal."""
        return Actor(self.actor_type, self.id, self.label)


@dataclass(slots=True)
class ProjectAccess:
    """Resolved access of a principal to a project."""

    project: Project
    principal: Principal
    role: Role

    @property
    def project_id(self) -> uuid.UUID:
        return self.project.id

    @property
    def is_owner(self) -> bool:
        return self.role == Role.owner

    @property
    def can_edit(self) -> bool:
        return role_at_least(self.role, Role.editor)

    @property
    def is_admin(self) -> bool:
        return self.principal.is_admin

    @property
    def can_see_restricted_details(self) -> bool:
        """Owners and platform admins see redacted governance details (non-leak principle, §3)."""
        return self.is_owner or self.principal.is_admin

    def has_role(self, minimum: Role) -> bool:
        return role_at_least(self.role, minimum)

    def require(self, minimum: Role) -> None:
        if not self.has_role(minimum):
            raise forbidden(_ROLE_MESSAGES[minimum])


_ROLE_MESSAGES: dict[Role, str] = {
    Role.viewer: "Accès réservé aux membres du projet",
    Role.editor: "Action réservée aux éditeurs et propriétaires du projet",
    Role.owner: "Action réservée aux propriétaires du projet",
}


# --- Credential extraction ------------------------------------------------------------------------


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _agent_key(request: Request) -> str | None:
    header_key = request.headers.get(API_KEY_HEADER)
    if header_key and header_key.strip():
        return header_key.strip()
    token = _bearer_token(request)
    if token and looks_like_api_key(token):
        return token
    return None


def _session_token(request: Request) -> str | None:
    token = _bearer_token(request)
    if token and not looks_like_api_key(token):
        return token
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    return cookie or None


def _reauthenticate(detail: str, code: str = "unauthorized") -> ApiError:
    return ApiError(
        401, f"{detail} — veuillez vous reconnecter", code=code, headers={"WWW-Authenticate": "Bearer"}
    )


async def _user_from_token(conn: HTTPConnection, session: AsyncSession, token: str) -> User:
    """Validate the JWT, its server-side session and the account state; stores the session row on
    ``conn.state.user_session``."""
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise _reauthenticate(str(exc)) from exc
    if claims.session_id is None:
        raise _reauthenticate("Session invalide")
    user = await session.get(User, claims.user_id)
    if user is None:
        raise _reauthenticate("Session invalide")
    if not user.is_active:
        raise ApiError(401, "Compte désactivé — contactez un administrateur", code="account_disabled")
    if claims.password_fingerprint != password_fingerprint(user.password_hash):
        raise _reauthenticate("Session révoquée (mot de passe modifié)")
    if user.must_change_password:
        raise _reauthenticate("Changement de mot de passe requis", code="password_change_required")
    try:
        row = await session_service.validate_session(session, claims.session_id, user.id)
    except session_service.SessionInvalid as exc:
        raise _reauthenticate(str(exc)) from exc
    conn.state.user_session = row
    return user


async def _throttle(conn: HTTPConnection, bucket: str, identity: str, spec: str) -> None:
    """Per-principal API limit, counted once per request."""
    if getattr(conn.state, "principal_throttled", False):
        return
    conn.state.principal_throttled = True
    await ratelimit.enforce(bucket, identity, spec)


def _agent_failure_spec() -> str:
    return ratelimit.scaled(settings.rate_limit_login, AGENT_AUTH_FAILURE_FACTOR)


async def authenticate_agent_key(
    session: AsyncSession,
    key: str,
    *,
    touch: bool = True,
    conn: HTTPConnection | None = None,
    throttle: bool = True,
) -> Agent:
    """Validate an ``orb_…`` key and return the active agent. Also used by the MCP server.

    With ``throttle`` (once per HTTP request), failed attempts are rate limited per client IP and
    successful calls count against the agent's own ``ORBIT_RATE_LIMIT_AGENT`` window.
    """
    if not throttle:
        return await _lookup_agent_key(session, key)
    ip = (client_ip(conn) if conn is not None else None) or "unknown"
    failure_spec = _agent_failure_spec()
    retry_after = await ratelimit.check("agent-auth-fail", ip, failure_spec)
    if retry_after > 0:
        raise ratelimit.RateLimited(
            retry_after, "Trop d'échecs d'authentification par clé d'agent : réessayez plus tard."
        )
    try:
        agent_obj = await _lookup_agent_key(session, key)
    except ApiError:
        await ratelimit.hit("agent-auth-fail", ip, failure_spec)
        raise
    await ratelimit.enforce("agent", str(agent_obj.id), settings.rate_limit_agent)
    if touch:
        now = utcnow()
        if agent_obj.last_used_at is None or now - agent_obj.last_used_at >= AGENT_LAST_USED_RESOLUTION:
            await session.execute(update(Agent).where(Agent.id == agent_obj.id).values(last_used_at=now))
            agent_obj.last_used_at = now
            await session.commit()
    return agent_obj


async def _lookup_agent_key(session: AsyncSession, key: str) -> Agent:
    parsed = parse_api_key(key)
    if parsed is None:
        raise unauthorized("Clé d'agent invalide")
    prefix, _secret = parsed
    agent_obj = await session.scalar(select(Agent).where(Agent.api_key_prefix == prefix))
    if agent_obj is None:
        # Equalise timing with the success path.
        verify_api_key(key, hash_api_key("orb_invalid"))
        raise unauthorized("Clé d'agent invalide")
    if not verify_api_key(key, agent_obj.api_key_hash):
        raise unauthorized("Clé d'agent invalide")
    if not agent_obj.active:
        raise unauthorized("Clé d'agent révoquée")
    return agent_obj


# --- Dependencies ---------------------------------------------------------------------------------


async def get_current_user(request: Request, session: SessionDep) -> User:
    """Authenticated human user (cookie or Bearer JWT). Agent keys are rejected here."""
    token = _session_token(request)
    if token is None:
        if _agent_key(request):
            raise forbidden("Cette opération n'est pas accessible avec une clé d'agent")
        raise unauthorized("Authentification requise")
    user = await _user_from_token(request, session, token)
    await _throttle(request, "api", f"user:{user.id}", settings.rate_limit_api)
    return user


async def get_optional_user(request: Request, session: SessionDep) -> User | None:
    token = _session_token(request)
    if token is None:
        return None
    try:
        return await _user_from_token(request, session, token)
    except ApiError:
        return None


async def get_principal(request: Request, session: SessionDep) -> Principal:
    """User **or** agent principal. Agent keys take precedence when both are present."""
    key = _agent_key(request)
    if key:
        agent = await authenticate_agent_key(session, key, conn=request)
        return Principal.for_agent(agent)
    token = _session_token(request)
    if token is None:
        raise unauthorized("Authentification requise (session ou clé d'agent)")
    user = await _user_from_token(request, session, token)
    await _throttle(request, "api", f"user:{user.id}", settings.rate_limit_api)
    return Principal.for_user(user)


async def get_user_principal(user: Annotated[User, Depends(get_current_user)]) -> Principal:
    return Principal.for_user(user)


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise forbidden("Action réservée aux administrateurs de la plateforme")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
AdminUser = Annotated[User, Depends(require_admin)]


async def get_project_access(
    session: AsyncSession,
    principal: Principal,
    slug: str,
    min_role: Role = Role.viewer,
) -> ProjectAccess:
    """Resolve ``slug`` for ``principal`` and enforce ``min_role`` (404 non-member, 403 insufficient role)."""
    project = await project_service.get_by_slug(session, slug)
    if project is None:
        raise not_found("Projet introuvable")

    if principal.is_agent:
        assert principal.agent is not None
        if principal.agent.project_id != project.id:
            raise not_found("Projet introuvable")
        role = Role.editor
    elif principal.is_admin:
        role = Role.owner
    else:
        assert principal.user is not None
        member_role = await project_service.get_member_role(session, project.id, principal.user.id)
        if member_role is None:
            raise not_found("Projet introuvable")
        role = member_role

    access = ProjectAccess(project=project, principal=principal, role=role)
    if not access.has_role(min_role):
        if principal.is_agent:
            raise forbidden("Cette opération n'est pas autorisée pour une clé d'agent")
        access.require(min_role)
    return access


def require_project(
    min_role: Role = Role.viewer, *, agents: bool = False
) -> Callable[..., Awaitable[ProjectAccess]]:
    """Dependency factory for ``/projects/{slug}/…`` routes.

    ``agents=True`` accepts agent API keys in addition to user sessions (endpoints marked *(agent)*).
    """
    if agents:

        async def _dependency_any(
            session: SessionDep,
            principal: CurrentPrincipal,
            slug: Annotated[str, Path(description="Slug du projet")],
        ) -> ProjectAccess:
            return await get_project_access(session, principal, slug, min_role)

        return _dependency_any

    async def _dependency_user(
        session: SessionDep,
        principal: Annotated[Principal, Depends(get_user_principal)],
        slug: Annotated[str, Path(description="Slug du projet")],
    ) -> ProjectAccess:
        return await get_project_access(session, principal, slug, min_role)

    return _dependency_user


ViewerAccess = Annotated[ProjectAccess, Depends(require_project(Role.viewer))]
EditorAccess = Annotated[ProjectAccess, Depends(require_project(Role.editor))]
OwnerAccess = Annotated[ProjectAccess, Depends(require_project(Role.owner))]
AgentViewerAccess = Annotated[ProjectAccess, Depends(require_project(Role.viewer, agents=True))]
AgentEditorAccess = Annotated[ProjectAccess, Depends(require_project(Role.editor, agents=True))]

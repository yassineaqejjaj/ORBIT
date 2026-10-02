"""Microsoft Teams integration (F4): outgoing-webhook endpoint and owner configuration."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response

from app.deps import OwnerAccess, SessionDep
from app.errors import validation_error
from app.features.teams import service
from app.features.teams.schemas import TeamsIntegrationIn, TeamsIntegrationOut, TeamsUserLinkOut
from app.models.features_ask import Integration
from app.services import audit
from app.services import projects as project_service

router = APIRouter(tags=["teams"])

MAX_BODY = 256 * 1024


def _webhook_path(slug: str) -> str:
    return f"/api/v1/integrations/teams/{slug}"


@router.post("/integrations/teams/{project_slug}", summary="Webhook sortant Microsoft Teams (HMAC)")
async def teams_webhook(project_slug: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """Authenticated by ``Authorization: HMAC <base64>`` (no ORBIT session). Replies in Teams format."""
    body = await request.body()
    if len(body) > MAX_BODY:
        raise validation_error("Message Teams trop volumineux")
    return await service.handle_activity(session, project_slug, body, request.headers.get("authorization"))


async def _out(
    session: SessionDep, access: OwnerAccess, integration: Integration | None
) -> TeamsIntegrationOut:
    members = {
        user.id: user for _member, user in await project_service.list_members(session, access.project_id)
    }
    links = []
    for teams_id, user_id in service.mapping_of(integration).items():
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            continue
        user = members.get(uid)
        links.append(
            TeamsUserLinkOut(
                teams_id=teams_id,
                user_id=uid,
                user_label=(user.full_name or user.email) if user else "",
                is_member=user is not None,
            )
        )
    return TeamsIntegrationOut(
        configured=integration is not None,
        enabled=bool(integration and integration.enabled),
        encryption_available=service.encryption_available(),
        webhook_path=_webhook_path(access.project.slug),
        app_url=str(((integration.config or {}) if integration else {}).get("app_url") or ""),
        user_mapping=links,
        updated_at=integration.updated_at if integration else None,
    )


@router.get(
    "/projects/{slug}/integrations/teams", response_model=TeamsIntegrationOut, summary="Intégration Teams"
)
async def get_teams_integration(access: OwnerAccess, session: SessionDep) -> TeamsIntegrationOut:
    return await _out(session, access, await service.get_integration(session, access.project_id))


@router.put(
    "/projects/{slug}/integrations/teams",
    response_model=TeamsIntegrationOut,
    summary="Connecter Microsoft Teams",
)
async def put_teams_integration(
    body: TeamsIntegrationIn, access: OwnerAccess, session: SessionDep
) -> TeamsIntegrationOut:
    integration = await service.get_integration(session, access.project_id)
    if body.secret is None and integration is None:
        raise validation_error("Le jeton de sécurité fourni par Teams est requis pour la première connexion")
    encrypted = None
    if body.secret is not None:
        service.validate_secret(body.secret)
        encrypted = service.encrypt_secret(body.secret.strip())  # 409 when ORBIT_ENCRYPTION_KEY is missing
    members = {user.id for _member, user in await project_service.list_members(session, access.project_id)}
    mapping: dict[str, str] = {}
    for link in body.user_mapping:
        if link.user_id not in members:
            raise validation_error("Chaque compte Teams doit être relié à un membre du projet")
        mapping[service.normalize_teams_id(link.teams_id)] = str(link.user_id)
    app_url = (body.app_url or "").strip().rstrip("/")
    if app_url and not app_url.startswith(("https://", "http://")):
        raise validation_error("L'URL de l'application doit commencer par https://")
    config = {"user_mapping": mapping, "app_url": app_url}
    created = integration is None
    if integration is None:
        assert encrypted is not None
        integration = Integration(
            project_id=access.project_id,
            kind=service.KIND,
            secret_encrypted=encrypted,
            enabled=body.enabled,
            config=config,
            created_by_id=access.principal.user_id,
        )
        session.add(integration)
    else:
        if encrypted is not None:
            integration.secret_encrypted = encrypted
        integration.enabled = body.enabled
        integration.config = config
    await session.flush()
    await audit.record(
        session,
        access.project_id,
        access.principal,
        "integration.configure",
        target_type="integration",
        target_id=integration.id,
        summary=(
            f"{'Connexion' if created else 'Mise à jour'} de Microsoft Teams "
            f"({len(mapping)} compte(s) relié(s){', secret renouvelé' if encrypted and not created else ''})"
        ),
        details={"kind": service.KIND, "enabled": body.enabled, "linked_accounts": len(mapping)},
    )
    await session.commit()
    await session.refresh(integration)
    return await _out(session, access, integration)


@router.delete("/projects/{slug}/integrations/teams", status_code=204, summary="Déconnecter Microsoft Teams")
async def delete_teams_integration(access: OwnerAccess, session: SessionDep) -> Response:
    integration = await service.get_integration(session, access.project_id)
    if integration is not None:
        await session.delete(integration)
        await audit.record(
            session,
            access.project_id,
            access.principal,
            "integration.delete",
            target_type="integration",
            target_id=integration.id,
            summary="Déconnexion de Microsoft Teams",
            details={"kind": service.KIND},
        )
        await session.commit()
    return Response(status_code=204)

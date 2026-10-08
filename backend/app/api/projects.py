"""Projects: list (with stats), create, read, update (partial settings merge)."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from app.deps import CurrentUser, OwnerAccess, SessionDep, ViewerAccess
from app.enums import Role
from app.errors import conflict
from app.models import Project, ProjectMember
from app.schemas import Project as ProjectOut
from app.schemas import ProjectCreateIn, ProjectSummary, ProjectUpdateIn
from app.services import audit
from app.services import projects as project_service
from app.services.audit import AuditAction

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummary], summary="Projets de l'appelant (tous pour un admin)")
async def list_projects(user: CurrentUser, session: SessionDep) -> list[ProjectSummary]:
    memberships = {
        m.project_id: m.role
        for m in await session.scalars(select(ProjectMember).where(ProjectMember.user_id == user.id))
    }
    stmt = select(Project).order_by(Project.name)
    if not user.is_admin:
        if not memberships:
            return []
        stmt = stmt.where(Project.id.in_(list(memberships)))
    projects = list(await session.scalars(stmt))
    stats = await project_service.project_stats(session, [p.id for p in projects])
    return [
        project_service.to_summary(p, Role.owner if user.is_admin else memberships[p.id], stats[p.id])
        for p in projects
    ]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, summary="Créer un projet")
async def create_project(body: ProjectCreateIn, user: CurrentUser, session: SessionDep) -> ProjectOut:
    slug = body.slug
    if slug is not None:
        if slug in project_service.RESERVED_SLUGS:
            raise conflict(f"Le slug « {slug} » est réservé")
        if await project_service.slug_exists(session, slug):
            raise conflict(f"Le slug « {slug} » est déjà utilisé par un autre projet")
    project = await project_service.create_project(
        session, name=body.name, slug=slug, description=body.description, owner=user
    )
    await audit.record(
        session,
        project.id,
        user,
        AuditAction.project_create,
        "project",
        project.id,
        summary=f"Création du projet « {project.name} »",
        details={"slug": project.slug},
    )
    await session.commit()
    return project_service.to_schema(project, Role.owner)


@router.get("/{slug}", response_model=ProjectOut, summary="Détail d'un projet")
async def get_project(access: ViewerAccess) -> ProjectOut:
    return project_service.to_schema(access.project, access.role)


@router.patch(
    "/{slug}", response_model=ProjectOut, summary="Modifier un projet (merge partiel des paramètres)"
)
async def update_project(body: ProjectUpdateIn, access: OwnerAccess, session: SessionDep) -> ProjectOut:
    project = access.project
    changes: dict[str, object] = {}
    if body.name is not None and body.name != project.name:
        changes["name"] = {"from": project.name, "to": body.name}
        project.name = body.name
    if body.description is not None and body.description != project.description:
        changes["description"] = "modifiée"
        project.description = body.description
    if body.settings is not None:
        before = project_service.normalize_settings(project.settings)
        after = project_service.merge_settings(before, body.settings)
        if after != before:
            changes["settings"] = {
                key: {"from": before.get(key), "to": value}
                for key, value in after.items()
                if before.get(key) != value
            }
            # Keys managed elsewhere (e.g. §C3 ``context_profiles``) are preserved.
            project.settings = {**(project.settings or {}), **after}
    if changes:
        await audit.record(
            session,
            project.id,
            access.principal,
            AuditAction.project_update,
            "project",
            project.id,
            summary=f"Modification du projet « {project.name} »",
            details={"changes": changes},
        )
        await session.commit()
        await session.refresh(project)
    return project_service.to_schema(project, access.role)

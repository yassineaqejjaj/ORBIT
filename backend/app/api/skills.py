"""Procedural memory served as Agent Skills (docs/AI_CONTEXT_ENGINEERING.md §D1).

Procedures are memory items of kind ``procedure`` (created / edited through ``/memory``); this router
serves them as skills: list, ``SKILL.md`` detail and a zip download (``<name>/SKILL.md``). Same
visibility as memory (items the caller cannot see answer ``404``).
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.config import settings
from app.deps import SessionDep, ViewerAccess
from app.errors import not_found
from app.memory import skills
from app.memory.visibility import MemoryViewer
from app.schemas.memory import Skill, SkillDetail
from app.services import skills as skill_service

router = APIRouter(prefix="/projects/{slug}/skills", tags=["memory"])

SKILL_NOT_FOUND = "Skill introuvable"


def _enabled() -> None:
    if not settings.memory_skills:
        raise not_found("La mémoire procédurale (skills) est désactivée")


@router.get("", response_model=list[Skill], summary="Skills du projet (procédures)")
async def list_skills(access: ViewerAccess, session: SessionDep) -> list[Skill]:
    _enabled()
    items = await skill_service.list_procedures(session, MemoryViewer.from_access(access))
    return [Skill(**skill_service.summary(item)) for item in items]


@router.get("/{name}", response_model=SkillDetail, summary="Détail d'un skill (SKILL.md)")
async def get_skill(name: str, access: ViewerAccess, session: SessionDep) -> SkillDetail:
    _enabled()
    item = await skill_service.find_skill(session, MemoryViewer.from_access(access), name)
    if item is None:
        raise not_found(SKILL_NOT_FOUND)
    return SkillDetail(
        **skill_service.summary(item), skill_md=skills.render_skill_md(item, project_slug=access.project.slug)
    )


@router.get("/{name}/download", summary="Télécharger un skill (zip SKILL.md)")
async def download_skill(name: str, access: ViewerAccess, session: SessionDep) -> Response:
    _enabled()
    item = await skill_service.find_skill(session, MemoryViewer.from_access(access), name)
    if item is None:
        raise not_found(SKILL_NOT_FOUND)
    filename = f"{skills.meta_of(item)['name']}.zip"
    return Response(
        content=skills.skill_zip(item, project_slug=access.project.slug),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

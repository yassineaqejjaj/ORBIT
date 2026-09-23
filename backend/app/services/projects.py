"""Project helpers: slugs, default settings (ARCHITECTURE §5), lookups, membership and statistics."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import DocumentStatus, MemoryStatus, Role, SourceKind
from app.models import ContextRequest, Document, MemoryItem, Project, ProjectMember, Source, User
from app.schemas.projects import Project as ProjectOut
from app.schemas.projects import ProjectSettings, ProjectSettingsPatch, ProjectStats, ProjectSummary

DEFAULT_PROJECT_SETTINGS: dict[str, Any] = {
    "freshness_days": {
        "document": 365,
        "note": 120,
        "ticket": 90,
        "crm": 180,
        "feedback": 180,
        "agent_trace": 30,
        "url": 180,
    },
    "default_token_budget": 4000,
    "min_relevance": 0.35,
    "short_term_ttl_hours": 72,
}

SLUG_MAX_LENGTH = 48
#: Slugs that would collide with UI or API routes.
RESERVED_SLUGS: frozenset[str] = frozenset({"new", "nouveau", "admin", "settings", "api", "login", "logout"})


# --- Settings -------------------------------------------------------------------------------------


def default_settings() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_PROJECT_SETTINGS)


def normalize_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Complete stored settings with defaults (older rows, partial imports) and drop unknown keys."""
    result = default_settings()
    if not raw:
        return result
    freshness = raw.get("freshness_days")
    if isinstance(freshness, Mapping):
        for kind in SourceKind:
            value = freshness.get(kind.value)
            if isinstance(value, int | float) and value > 0:
                result["freshness_days"][kind.value] = int(value)
    for key in ("default_token_budget", "short_term_ttl_hours"):
        if isinstance(raw.get(key), int | float):
            result[key] = int(raw[key])
    if isinstance(raw.get("min_relevance"), int | float):
        result["min_relevance"] = float(raw["min_relevance"])
    return result


def merge_settings(
    current: Mapping[str, Any] | None, patch: ProjectSettingsPatch | Mapping[str, Any]
) -> dict[str, Any]:
    """Partial merge (``freshness_days`` merged key by key), validated against :class:`ProjectSettings`."""
    merged = normalize_settings(current)
    data = (
        patch.model_dump(exclude_unset=True, exclude_none=True)
        if isinstance(patch, ProjectSettingsPatch)
        else dict(patch)
    )
    for key, value in data.items():
        if key == "freshness_days" and isinstance(value, Mapping):
            for kind, days in value.items():
                merged["freshness_days"][str(getattr(kind, "value", kind))] = int(days)
        elif key in DEFAULT_PROJECT_SETTINGS:
            merged[key] = value
    return ProjectSettings.model_validate(merged).model_dump(mode="json")


def settings_model(project: Project) -> ProjectSettings:
    return ProjectSettings.model_validate(normalize_settings(project.settings))


# --- Slugs ----------------------------------------------------------------------------------------


def slug_candidate(name: str) -> str:
    base = slugify(name, max_length=SLUG_MAX_LENGTH, word_boundary=True, lowercase=True) or "projet"
    if len(base) < 2:
        base = f"projet-{base}"
    return base


async def slug_exists(session: AsyncSession, slug: str) -> bool:
    return bool(await session.scalar(select(func.count()).select_from(Project).where(Project.slug == slug)))


async def generate_unique_slug(session: AsyncSession, name: str) -> str:
    base = slug_candidate(name)
    if base not in RESERVED_SLUGS and not await slug_exists(session, base):
        return base
    for index in range(2, 1000):
        suffix = f"-{index}"
        candidate = f"{base[: SLUG_MAX_LENGTH - len(suffix)].rstrip('-')}{suffix}"
        if not await slug_exists(session, candidate):
            return candidate
    return f"{base[: SLUG_MAX_LENGTH - 9]}-{uuid.uuid4().hex[:8]}"


# --- Lookups --------------------------------------------------------------------------------------


async def get_by_slug(session: AsyncSession, slug: str) -> Project | None:
    return await session.scalar(select(Project).where(Project.slug == slug.strip().lower()))


async def get_member(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectMember | None:
    return await session.get(ProjectMember, (project_id, user_id))


async def get_member_role(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> Role | None:
    member = await get_member(session, project_id, user_id)
    return member.role if member else None


async def count_owners(session: AsyncSession, project_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.role == Role.owner)
        )
        or 0
    )


async def list_members(session: AsyncSession, project_id: uuid.UUID) -> list[tuple[ProjectMember, User]]:
    rows = await session.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at, User.full_name)
    )
    return [(member, user) for member, user in rows.tuples()]


# --- Creation -------------------------------------------------------------------------------------


async def create_project(
    session: AsyncSession,
    *,
    name: str,
    owner: User,
    slug: str | None = None,
    description: str = "",
    settings: Mapping[str, Any] | None = None,
) -> Project:
    """Create a project with default settings and ``owner`` as its first owner (flushed, not committed).

    ``slug`` must already be validated as free by the caller when provided.
    """
    project = Project(
        slug=slug or await generate_unique_slug(session, name),
        name=name.strip(),
        description=(description or "").strip(),
        settings=normalize_settings(settings),
        created_by=owner.id,
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=owner.id, role=Role.owner))
    await session.flush()
    return project


# --- Serialisation & statistics -------------------------------------------------------------------


def to_schema(project: Project, role: Role) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        description=project.description,
        settings=settings_model(project),
        role=role,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


async def project_stats(
    session: AsyncSession, project_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, ProjectStats]:
    ids = list(project_ids)
    stats = {pid: ProjectStats() for pid in ids}
    if not ids:
        return stats

    async def _count_by(column: Any, *conditions: Any) -> dict[uuid.UUID, int]:
        rows = await session.execute(
            select(column, func.count()).where(column.in_(ids), *conditions).group_by(column)
        )
        return {pid: int(count) for pid, count in rows.tuples()}

    sources = await _count_by(Source.project_id)
    documents = await _count_by(Document.project_id, Document.status != DocumentStatus.forgotten)
    memory = await _count_by(
        MemoryItem.project_id,
        MemoryItem.is_current.is_(True),
        MemoryItem.status.not_in([MemoryStatus.forgotten]),
    )
    since = utcnow() - timedelta(days=7)
    requests = await _count_by(ContextRequest.project_id, ContextRequest.created_at >= since)
    for pid in ids:
        stats[pid] = ProjectStats(
            sources=sources.get(pid, 0),
            documents=documents.get(pid, 0),
            memory_items=memory.get(pid, 0),
            context_requests_7d=requests.get(pid, 0),
        )
    return stats


def to_summary(project: Project, role: Role, stats: ProjectStats) -> ProjectSummary:
    return ProjectSummary(**to_schema(project, role).model_dump(), stats=stats)

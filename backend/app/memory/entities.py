"""Entity resolution (docs/AI_CONTEXT_ENGINEERING.md §D2): entities, aliases, assisted merges.

* an :class:`~app.models.Entity` has surface forms (:class:`~app.models.EntityAlias`, its name included);
* :func:`suggestions` proposes merges between active entities (same normalised form, acronym of the
  other, containment or high lexical similarity) — shown in the Revue mémoire, never applied
  automatically;
* :func:`merge` moves the source's aliases to the target (remembering where they came from) and
  :func:`unmerge` restores them exactly — both audited;
* :func:`alias_query` expands a retrieval query with the other surface forms of the entities it
  mentions (« SSO » → « authentification unique »), used by the context engine.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import conflict, validation_error
from app.memory.conflicts import STOPWORDS, lexical_similarity, normalize_text, tokens
from app.models import Entity, EntityAlias
from app.services import audit
from app.services.audit import ActorLike, AuditAction

SIMILARITY_THRESHOLD = 0.6
MAX_SUGGESTIONS = 50
MAX_ALIAS_TERMS = 8


def normalize(alias: str) -> str:
    return normalize_text(alias)


def acronym(text: str) -> str:
    """Initials of the significant words (« Single Sign-On » → ``sso``)."""
    words = [t for t in tokens(text) if t not in STOPWORDS]
    return "".join(w[0] for w in words) if len(words) >= 2 else ""


@dataclass(slots=True)
class Suggestion:
    a: Entity
    b: Entity
    score: float
    reason: str


async def aliases_of(
    session: AsyncSession, entity_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[EntityAlias]]:
    ids = list(set(entity_ids))
    out: dict[uuid.UUID, list[EntityAlias]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = await session.scalars(
        select(EntityAlias)
        .where(EntityAlias.entity_id.in_(ids))
        .order_by(EntityAlias.created_at, EntityAlias.alias)
    )
    for row in rows:
        out[row.entity_id].append(row)
    return out


async def active_entities(session: AsyncSession, project_id: uuid.UUID) -> list[Entity]:
    rows = await session.scalars(
        select(Entity)
        .where(Entity.project_id == project_id, Entity.merged_into_id.is_(None))
        .order_by(Entity.name)
    )
    return list(rows)


async def create_entity(
    session: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    *,
    kind: str = "concept",
    aliases: Sequence[str] = (),
    actor: ActorLike = None,
) -> Entity:
    clean = " ".join(name.split())
    if not clean:
        raise validation_error("Le nom de l'entité est requis")
    forms = list(dict.fromkeys([clean, *(" ".join(a.split()) for a in aliases if a.strip())]))
    taken = await session.scalar(
        select(EntityAlias.alias)
        .join(Entity, Entity.id == EntityAlias.entity_id)
        .where(
            EntityAlias.project_id == project_id,
            Entity.merged_into_id.is_(None),
            EntityAlias.normalized.in_([normalize(f) for f in forms]),
        )
        .limit(1)
    )
    if taken is not None:
        raise conflict(f"« {taken} » désigne déjà une entité du projet")
    entity = Entity(project_id=project_id, name=clean, kind=kind or "concept")
    session.add(entity)
    await session.flush()
    for form in forms:
        session.add(
            EntityAlias(project_id=project_id, entity_id=entity.id, alias=form, normalized=normalize(form))
        )
    await audit.record(
        session,
        project_id,
        actor,
        AuditAction.entity_create,
        "entity",
        entity.id,
        summary=f"Entité « {clean} » créée",
        details={"aliases": forms},
    )
    await session.flush()
    return entity


def _pair_reason(forms_a: Sequence[str], forms_b: Sequence[str]) -> tuple[float, str] | None:
    best: tuple[float, str] | None = None
    for fa in forms_a:
        for fb in forms_b:
            na, nb = normalize(fa), normalize(fb)
            if not na or not nb:
                continue
            if na == nb:
                return 1.0, f"même forme « {fa} » / « {fb} »"
            if acronym(fa) == nb.replace(" ", "") or acronym(fb) == na.replace(" ", ""):
                candidate = (0.9, f"« {fb if len(fb) < len(fa) else fa} » est le sigle de l'autre forme")
            elif (f" {na} " in f" {nb} " or f" {nb} " in f" {na} ") and min(len(na), len(nb)) >= 4:
                candidate = (0.75, f"« {fa} » et « {fb} » : l'une contient l'autre")
            else:
                similarity = lexical_similarity(fa, fb)
                if similarity < SIMILARITY_THRESHOLD:
                    continue
                candidate = (round(similarity, 3), f"formes proches « {fa} » / « {fb} »")
            if best is None or candidate[0] > best[0]:
                best = candidate
    return best


async def suggestions(session: AsyncSession, project_id: uuid.UUID) -> list[Suggestion]:
    """Suggested merges between active entities, best first."""
    entities = await active_entities(session, project_id)
    by_id = await aliases_of(session, [e.id for e in entities])
    forms = {e.id: [a.alias for a in by_id.get(e.id, [])] or [e.name] for e in entities}
    out: list[Suggestion] = []
    for index, a in enumerate(entities):
        for b in entities[index + 1 :]:
            found = _pair_reason(forms[a.id], forms[b.id])
            if found is not None:
                out.append(Suggestion(a=a, b=b, score=found[0], reason=found[1]))
    out.sort(key=lambda s: s.score, reverse=True)
    return out[:MAX_SUGGESTIONS]


async def merge(
    session: AsyncSession, target: Entity, source: Entity, actor: ActorLike, reason: str | None
) -> Entity:
    if target.id == source.id or target.project_id != source.project_id:
        raise validation_error("Fusion impossible : choisissez deux entités distinctes du même projet")
    if target.merged_into_id is not None or source.merged_into_id is not None:
        raise conflict("Une des entités est déjà fusionnée")
    moved = list(await session.scalars(select(EntityAlias).where(EntityAlias.entity_id == source.id)))
    for alias in moved:
        alias.entity_id = target.id
        if alias.merged_from_id is None:
            alias.merged_from_id = source.id
    source.merged_into_id = target.id
    await audit.record(
        session,
        target.project_id,
        actor,
        AuditAction.entity_merge,
        "entity",
        target.id,
        summary=f"Entité « {source.name} » fusionnée dans « {target.name} »",
        details={
            "source_id": source.id,
            "target_id": target.id,
            "aliases": [a.alias for a in moved],
            "reason": reason,
        },
    )
    await session.flush()
    return target


async def unmerge(session: AsyncSession, source: Entity, actor: ActorLike, reason: str | None) -> Entity:
    """Undo :func:`merge` of ``source`` (its aliases come back, including those merged into it before)."""
    if source.merged_into_id is None:
        raise conflict("Cette entité n'est pas fusionnée")
    target_id = source.merged_into_id
    moved = list(
        await session.scalars(
            select(EntityAlias).where(
                EntityAlias.entity_id == target_id, EntityAlias.merged_from_id == source.id
            )
        )
    )
    for alias in moved:
        alias.entity_id = source.id
        alias.merged_from_id = None
    # Aliases that had been merged into ``source`` earlier keep their own origin.
    nested = list(await session.scalars(select(Entity).where(Entity.merged_into_id == source.id)))
    nested_ids = {e.id for e in nested}
    if nested_ids:
        rows = await session.scalars(
            select(EntityAlias).where(
                EntityAlias.entity_id == target_id, EntityAlias.merged_from_id.in_(nested_ids)
            )
        )
        for alias in rows:
            alias.entity_id = source.id
    source.merged_into_id = None
    await audit.record(
        session,
        source.project_id,
        actor,
        AuditAction.entity_unmerge,
        "entity",
        source.id,
        summary=f"Fusion de l'entité « {source.name} » annulée",
        details={
            "source_id": source.id,
            "target_id": target_id,
            "aliases": [a.alias for a in moved],
            "reason": reason,
        },
    )
    await session.flush()
    return source


_WORD_EDGE = r"(?<![a-z0-9]){}(?![a-z0-9])"


async def alias_query(session: AsyncSession, project_id: uuid.UUID, text: str) -> str | None:
    """``text`` + the other surface forms of every entity it mentions (``None`` when none matches)."""
    folded = normalize(text)
    if not folded:
        return None
    rows = list(
        await session.execute(
            select(EntityAlias.entity_id, EntityAlias.alias, EntityAlias.normalized)
            .join(Entity, Entity.id == EntityAlias.entity_id)
            .where(EntityAlias.project_id == project_id, Entity.merged_into_id.is_(None))
        )
    )
    forms: dict[uuid.UUID, list[tuple[str, str]]] = {}
    for entity_id, alias, normalized in rows:
        forms.setdefault(entity_id, []).append((alias, normalized))
    extra: list[str] = []
    for entity_forms in forms.values():
        if len(entity_forms) < 2:
            continue
        mentioned = [n for _, n in entity_forms if n and re.search(_WORD_EDGE.format(re.escape(n)), folded)]
        if not mentioned:
            continue
        extra.extend(alias for alias, n in entity_forms if n not in mentioned)
    extra = list(dict.fromkeys(extra))[:MAX_ALIAS_TERMS]
    return f"{text} {' '.join(extra)}" if extra else None


__all__ = [
    "Suggestion",
    "acronym",
    "active_entities",
    "alias_query",
    "aliases_of",
    "create_entity",
    "merge",
    "normalize",
    "suggestions",
    "unmerge",
]

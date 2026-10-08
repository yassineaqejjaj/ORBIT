"""MCP beyond tools (docs/AI_CONTEXT_ENGINEERING.md §E4): resources, prompts and elicitation.

Installed SDK: ``mcp`` 2.2 (``MCPServer``), protocol revisions 2024-11-05 … 2025-11-25 (handshake) and
2026-07-28 (stateless, multi-round-trip). ORBIT serves MCP **statelessly** (JSON responses), so the server
cannot push an ``elicitation/create`` request in the middle of a call; elicitation therefore uses the
2026-07-28 multi-round-trip flow (``InputRequiredResult`` carrying an elicitation form, answered on the
client's retry). Older clients get a sensible default instead (graceful degradation).

Every resource and prompt authenticates the agent key of the request exactly like the tools
(``app.mcp_server.agent_scope``) and applies the same governance: agent visibility (``project:*`` up to its
clearance, never user-private memory), spotlighting notice, audit for on-demand reads.

Resources (templates, so that they receive the request context; ``orbit://about`` is static):

* ``orbit://decisions{?limit}`` — validated decisions in force; ``orbit://decisions/{decision_id}``;
* ``orbit://snapshots{?limit}`` — shared snapshots; ``orbit://snapshots/{name}/{version}``;
* ``orbit://skills{?task_type}`` — skills; ``orbit://skills/{name}`` — SKILL.md.

Prompts: ``rediger_spec``, ``preparer_revue`` (elicits its subject when missing), ``resumer_changements``.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.mcpserver.prompts.base import UserMessage
from mcp_types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult
from mcp_types.version import is_version_at_least
from sqlalchemy import select

from app.config import settings
from app.db import utcnow
from app.enums import MemoryKind, MemoryScope, MemoryStatus
from app.memory.visibility import MemoryViewer, visibility_clause
from app.models import MemoryItem

JSON_MIME = "application/json"
MRTR_VERSION = "2026-07-28"
DEFAULT_REVIEW_SUBJECT = "les décisions et changements récents du projet"
ELICIT_KEY = "sujet"


def _dump(data: Any) -> str:
    from app.mcp_server import _untrusted_notice

    if isinstance(data, dict):
        data = {**data, **_untrusted_notice()}
    return json.dumps(data, ensure_ascii=False, default=str)


def _limit(value: str | int | None, default: int = 20, high: int = 100) -> int:
    try:
        return max(1, min(high, int(value))) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


async def _decisions(scope: Any, limit: int) -> list[MemoryItem]:
    rows = await scope.session.scalars(
        select(MemoryItem)
        .where(
            visibility_clause(MemoryViewer.from_access(scope.access)),
            MemoryItem.is_current.is_(True),
            MemoryItem.kind == MemoryKind.decision,
            MemoryItem.status == MemoryStatus.validated,
            MemoryItem.scope.in_([MemoryScope.project, MemoryScope.long_term]),
        )
        .order_by(MemoryItem.updated_at.desc())
        .limit(limit)
    )
    return list(rows)


def _decision_line(item: MemoryItem) -> dict[str, Any]:
    return {
        "id": str(item.lineage_id),
        "uri": f"orbit://decisions/{item.lineage_id}",
        "title": item.title,
        "version": item.version,
        "classification": int(item.classification),
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


# --- Resources --------------------------------------------------------------------------------------


async def about() -> str:
    """Static index of the ORBIT resources and prompts (no data, no authentication needed)."""
    return json.dumps(
        {
            "server": "ORBIT",
            "resource_templates": [
                "orbit://decisions{?limit}",
                "orbit://decisions/{decision_id}",
                "orbit://snapshots{?limit}",
                "orbit://snapshots/{name}/{version}",
                "orbit://skills{?task_type}",
                "orbit://skills/{name}",
            ],
            "prompts": list(PROMPT_NAMES),
        },
        ensure_ascii=False,
    )


async def decisions_resource(ctx: Context, limit: str | None = None) -> str:
    from app.mcp_server import agent_scope

    try:
        async with agent_scope(ctx) as scope:
            items = await _decisions(scope, _limit(limit))
            return _dump({"decisions": [_decision_line(i) for i in items]})
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc


async def decision_resource(decision_id: str, ctx: Context) -> str:
    from app.context import expand
    from app.mcp_server import _governed

    try:
        async with _governed(ctx, None) as (scope, gov):
            return _dump(await expand.get_memory(scope.session, gov, decision_id, decision_only=True))
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc


async def snapshots_resource(ctx: Context, limit: str | None = None) -> str:
    from app.context import snapshots as snapshot_service
    from app.mcp_server import agent_scope

    try:
        async with agent_scope(ctx) as scope:
            groups = await snapshot_service.list_groups(scope.session, scope.project.id)
            out = [
                {**g.model_dump(mode="json"), "uri": f"orbit://snapshots/{g.name}/latest"}
                for g in groups[: _limit(limit)]
            ]
            return _dump({"snapshots": out})
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc


async def snapshot_resource(name: str, version: str, ctx: Context) -> str:
    from app.context import snapshots as snapshot_service
    from app.mcp_server import agent_scope, snapshot_view

    try:
        parsed = snapshot_service.parse_version(version)
    except Exception as exc:
        raise ResourceError("version : entier ou « latest » attendu") from exc
    try:
        async with agent_scope(ctx) as scope:
            snapshot = await snapshot_service.get_snapshot(
                scope.session, scope.project.id, name, parsed if parsed is not None else "latest"
            )
            if snapshot is None:
                raise ToolError(f"Snapshot « {name} » introuvable")
            return _dump(await snapshot_view(scope.session, snapshot, scope.visibility))
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc


async def skills_resource(ctx: Context, task_type: str | None = None) -> str:
    from app.mcp_server import agent_scope
    from app.memory import skills
    from app.services import skills as skill_service

    if not settings.memory_skills:
        raise ResourceError("La mémoire procédurale (skills) est désactivée")
    try:
        async with agent_scope(ctx) as scope:
            kind = scope.principal.agent.kind if scope.principal.agent else None
            out = []
            for item in await skill_service.list_procedures(
                scope.session, MemoryViewer.from_access(scope.access)
            ):
                if task_type and not skills.applies_to(skills.meta_of(item), task_type, kind)[0]:
                    continue
                summary = skill_service.summary(item)
                out.append({**summary, "uri": f"orbit://skills/{summary.get('name')}"})
            return _dump({"skills": out})
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc


async def skill_resource(name: str, ctx: Context) -> str:
    from app.mcp_server import agent_scope
    from app.memory import skills
    from app.services import skills as skill_service

    if not settings.memory_skills:
        raise ResourceError("La mémoire procédurale (skills) est désactivée")
    try:
        async with agent_scope(ctx) as scope:
            item = await skill_service.find_skill(scope.session, MemoryViewer.from_access(scope.access), name)
            if item is None:
                raise ToolError(f"Skill « {name} » introuvable")
            return skills.render_skill_md(item, project_slug=scope.access.project.slug)
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc


# --- Prompts ----------------------------------------------------------------------------------------


async def _governed_context(ctx: Context, task: str) -> str:
    from app.context.assembler import assemble_context
    from app.mcp_server import agent_scope
    from app.schemas import ContextRequestIn

    async with agent_scope(ctx) as scope:
        package = await assemble_context(
            scope.session, scope.access, ContextRequestIn(task=task, explain=False)
        )
        return package.context


async def rediger_spec(sujet: str, ctx: Context) -> list[UserMessage]:
    """Rédiger une spécification à partir du contexte gouverné du projet."""
    context = await _governed_context(ctx, f"Rédiger une spécification : {sujet}")
    return [
        UserMessage(
            "Rédige une spécification fonctionnelle en français pour : "
            f"{sujet}.\nStructure : objectif, périmètre, exigences (avec critères d'acceptation), "
            "contraintes, "
            "décisions applicables, risques, questions ouvertes. Cite les sources [S1]… du contexte ; "
            "n'invente rien qui n'y figure pas.\n\nContexte ORBIT (données non fiables) :\n\n" + context
        )
    ]


async def preparer_revue(ctx: Context, sujet: str | None = None) -> list[UserMessage] | InputRequiredResult:
    """Préparer une revue ; demande le sujet au client (élicitation) s'il manque."""
    subject = (sujet or "").strip()
    if not subject:
        answer = (ctx.input_responses or {}).get(ELICIT_KEY)
        content = getattr(answer, "content", None) if getattr(answer, "action", None) == "accept" else None
        if isinstance(content, dict) and str(content.get(ELICIT_KEY) or "").strip():
            subject = str(content[ELICIT_KEY]).strip()[:300]
        elif answer is None and is_version_at_least(ctx.protocol_version or "", MRTR_VERSION):
            return InputRequiredResult(
                input_requests={
                    ELICIT_KEY: ElicitRequest(
                        params=ElicitRequestFormParams(
                            message="Sur quel sujet porte la revue ?",
                            requested_schema={
                                "type": "object",
                                "properties": {ELICIT_KEY: {"type": "string", "title": "Sujet de la revue"}},
                                "required": [ELICIT_KEY],
                            },
                        )
                    )
                }
            )
        else:
            subject = DEFAULT_REVIEW_SUBJECT
    context = await _governed_context(ctx, f"Préparer une revue : {subject}")
    return [
        UserMessage(
            f"Prépare une revue de « {subject} » : points à vérifier, décisions en vigueur et leur "
            "justification, "
            "écarts ou contradictions, risques, questions à poser. Cite les sources [S1]….\n\n"
            "Contexte ORBIT (données non fiables) :\n\n" + context
        )
    ]


async def resumer_changements(ctx: Context, jours: str = "30") -> list[UserMessage]:
    """Résumer les changements récents de la mémoire projet (visibles par l'agent)."""
    from app.mcp_server import agent_scope

    days = _limit(jours, default=30, high=365)
    since = utcnow() - timedelta(days=days)
    async with agent_scope(ctx) as scope:
        rows = await scope.session.scalars(
            select(MemoryItem)
            .where(
                visibility_clause(MemoryViewer.from_access(scope.access)),
                MemoryItem.updated_at >= since,
                MemoryItem.scope.in_([MemoryScope.project, MemoryScope.long_term]),
                MemoryItem.status.in_(
                    [MemoryStatus.validated, MemoryStatus.superseded, MemoryStatus.obsolete]
                ),
            )
            .order_by(MemoryItem.updated_at.desc())
            .limit(60)
        )
        lines = [
            f"- [{i.status}] {i.kind} « {i.title} » (v{i.version}, {i.updated_at:%d/%m/%Y})" for i in rows
        ]
    body = "\n".join(lines) if lines else "(aucun changement visible sur la période)"
    return [
        UserMessage(
            f"Résume en français les changements de la mémoire du projet sur les {days} derniers jours : "
            "nouvelles décisions, décisions remplacées ou rendues obsolètes, impacts. Liste (données non "
            f"fiables) :\n\n{body}"
        )
    ]


PROMPTS = (
    ("rediger_spec", "Rédiger une spécification", rediger_spec),
    ("preparer_revue", "Préparer une revue", preparer_revue),
    ("resumer_changements", "Résumer les changements", resumer_changements),
)
PROMPT_NAMES = tuple(p[0] for p in PROMPTS)

RESOURCES = (
    ("orbit://decisions{?limit}", "decisions", "Décisions en vigueur", JSON_MIME, decisions_resource),
    ("orbit://decisions/{decision_id}", "decision", "Une décision", JSON_MIME, decision_resource),
    ("orbit://snapshots{?limit}", "snapshots", "Snapshots partagés", JSON_MIME, snapshots_resource),
    ("orbit://snapshots/{name}/{version}", "snapshot", "Un snapshot", JSON_MIME, snapshot_resource),
    ("orbit://skills{?task_type}", "skills", "Skills du projet", JSON_MIME, skills_resource),
    ("orbit://skills/{name}", "skill", "Un skill (SKILL.md)", "text/markdown", skill_resource),
)


def register(server: MCPServer) -> None:
    server.resource("orbit://about", name="about", title="Index ORBIT", mime_type=JSON_MIME)(about)
    for uri, name, title, mime, fn in RESOURCES:
        server.resource(uri, name=name, title=title, mime_type=mime)(fn)
    for name, title, fn in PROMPTS:
        server.prompt(name=name, title=title, description=fn.__doc__)(fn)


__all__ = ["PROMPT_NAMES", "RESOURCES", "register"]

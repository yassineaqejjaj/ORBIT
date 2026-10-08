"""Procedural memory served as Agent Skills (docs/AI_CONTEXT_ENGINEERING.md §D1).

A memory item of kind ``procedure`` (template, definition of done, convention, checklist) is exposed as a
*skill* in the Agent Skills format: a folder ``<name>/SKILL.md`` whose YAML front matter carries ``name``
and ``description`` (plus ORBIT metadata), followed by the Markdown instructions. ``skill_meta`` stores
``name`` (kebab-case, ≤ 64 chars), ``description`` (≤ 1024 chars), ``task_types`` (intents) and
``agent_kinds`` the procedure applies to — empty lists mean « toutes ».

Everything here is pure (no I/O): normalisation, rendering, zipping and matching.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Mapping
from typing import Any

from app.context.textutils import fold
from app.enums import AgentKind, Intent

NAME_MAX = 64
DESCRIPTION_MAX = 1024
_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """``« Définition de terminé d'une user story »`` → ``definition-de-termine-d-une-user-story``."""
    slug = _SLUG.sub("-", fold(text or "")).strip("-")
    return (slug[:NAME_MAX].rstrip("-")) or "procedure"


def _values(raw: Any, enum_cls: type[Intent] | type[AgentKind]) -> list[str]:
    out: list[str] = []
    for value in raw or []:
        text = str(getattr(value, "value", value))
        if text in enum_cls.__members__ and text not in out:
            out.append(text)
    return out


def normalize_meta(meta: Any, title: str, content: str = "") -> dict[str, Any]:
    """Stored ``skill_meta`` from user input (pydantic model, mapping or ``None``)."""
    data: Mapping[str, Any]
    if meta is None:
        data = {}
    elif isinstance(meta, Mapping):
        data = meta
    else:
        data = meta.model_dump()
    name = slugify(str(data.get("name") or title))
    description = " ".join(str(data.get("description") or "").split())
    if not description:
        description = " ".join((content or title).split())
    return {
        "name": name,
        "description": description[:DESCRIPTION_MAX],
        "task_types": _values(data.get("task_types"), Intent),
        "agent_kinds": _values(data.get("agent_kinds"), AgentKind),
    }


def meta_of(item: Any) -> dict[str, Any]:
    """Normalised metadata of a procedure item (fills defaults for items edited without metadata)."""
    return normalize_meta(item.skill_meta, item.title, item.content)


def applies_to(
    meta: Mapping[str, Any] | None, intent: str | None, agent_kind: str | None
) -> tuple[bool, str]:
    """Whether a procedure applies to a request; ``(False, reason)`` explains a mismatch (French)."""
    meta = meta or {}
    task_types = list(meta.get("task_types") or [])
    agent_kinds = list(meta.get("agent_kinds") or [])
    if task_types and intent and intent not in task_types and Intent.general.value not in task_types:
        return False, f"procédure réservée aux tâches {', '.join(task_types)} (tâche : {intent})"
    if agent_kinds and agent_kind and agent_kind not in agent_kinds:
        return False, f"procédure réservée aux agents {', '.join(agent_kinds)} (agent : {agent_kind})"
    return True, ""


def _yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _yaml_list(values: Iterable[str]) -> str:
    return "[" + ", ".join(values) + "]"


def render_skill_md(item: Any, *, project_slug: str) -> str:
    """``SKILL.md`` (Agent Skills format) of a procedure item."""
    meta = meta_of(item)
    status = str(getattr(item.status, "value", item.status))
    front = [
        "---",
        f"name: {meta['name']}",
        f"description: {_yaml_str(meta['description'])}",
        "metadata:",
        "  source: orbit",
        f"  project: {project_slug}",
        f"  memory_id: {item.id}",
        f"  lineage_id: {item.lineage_id}",
        f"  version: {item.version}",
        f"  status: {status}",
        f"  classification: C{int(item.classification)}",
        f"  task_types: {_yaml_list(meta['task_types'])}",
        f"  agent_kinds: {_yaml_list(meta['agent_kinds'])}",
        f"  updated_at: {item.updated_at.isoformat() if item.updated_at else ''}",
        "---",
        "",
        f"# {' '.join(item.title.split())}",
        "",
        (item.content or "").strip(),
        "",
    ]
    return "\n".join(front)


def skill_zip(item: Any, *, project_slug: str) -> bytes:
    """Zip archive ``<name>/SKILL.md`` ready to drop in an agent's skills folder."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{meta_of(item)['name']}/SKILL.md", render_skill_md(item, project_slug=project_slug)
        )
    return buffer.getvalue()


__all__ = ["applies_to", "meta_of", "normalize_meta", "render_skill_md", "skill_zip", "slugify"]

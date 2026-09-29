"""``package`` stage (ARCHITECTURE §9.8): structured Markdown with stable citations.

Sections (only non-empty ones, in this order): ``## Décisions en vigueur``, ``## Besoins
utilisateurs``, ``## Contraintes & risques``, ``## Faits & connaissances``, ``## Préférences
utilisateur``, ``## Extraits de sources``, ``## Session en cours``, then ``## Sources`` listing every
citation: ``[S1] Titre — type · v2 · 12/09/2026 · uri``. Every bullet ends with its ``[Sx]`` marker;
citations are numbered in presentation order.

The per-item overhead helpers give an upper bound of the tokens a bullet and its source line cost,
used by the budget filler so that the final Markdown never exceeds the token budget.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.context.textutils import fold, one_line
from app.enums import (
    MEMORY_KIND_LABELS,
    RESTRICTED_CLASSIFICATION_MIN,
    SOURCE_KIND_LABELS,
    CandidateType,
    Intent,
    MemoryKind,
    MemoryStatus,
    classification_warning,
)
from app.governance.policy import MEMORY_SCOPE_LABELS, Candidate, format_date_fr, memory_status_label
from app.search.tokens import estimate_tokens

if TYPE_CHECKING:
    from app.context.selection import Decision

SECTIONS: tuple[tuple[str, str], ...] = (
    ("decisions", "Décisions en vigueur"),
    ("requirements", "Besoins utilisateurs"),
    ("constraints", "Contraintes & risques"),
    ("facts", "Faits & connaissances"),
    ("preferences", "Préférences utilisateur"),
    ("sources", "Extraits de sources"),
    ("session", "Session en cours"),
)
SECTION_TITLES = dict(SECTIONS)
SOURCES_HEADING = "Sources"
EMPTY_CONTEXT = "_Aucun élément pertinent et autorisé n'a été retenu pour cette tâche._"
TASK_PREVIEW_CHARS = 200
#: Placeholder citation used to estimate the cost of a bullet before numbering.
_CITATION_PLACEHOLDER = "S999"

INTENT_LABELS: dict[Intent, str] = {
    Intent.general: "générale",
    Intent.specification: "spécification",
    Intent.design: "design",
    Intent.engineering: "ingénierie",
    Intent.research: "recherche",
    Intent.analysis: "analyse",
    Intent.validation: "validation",
}

_ROLE_LABELS = {"user": "Utilisateur", "agent": "Agent", "tool": "Outil"}


def section_for(c: Candidate) -> str:
    if c.candidate_type == CandidateType.chunk:
        return "sources"
    if c.candidate_type == CandidateType.session:
        return "session"
    kind = c.memory_kind
    if kind == MemoryKind.decision:
        return "decisions"
    if kind == MemoryKind.requirement:
        return "requirements"
    if kind in (MemoryKind.constraint, MemoryKind.risk):
        return "constraints"
    if kind == MemoryKind.preference:
        return "preferences"
    return "facts"


# --- Line builders ------------------------------------------------------------------------------------


def sanitize(value: str) -> str:
    """Single-line text that can never forge a citation marker (``[S`` is defused)."""
    return one_line(value).replace("[S", "[ S")


def _starts_with_title(title: str, excerpt: str) -> bool:
    t = fold(one_line(title)).rstrip(" .:")
    return bool(t) and fold(one_line(excerpt)).startswith(t)


def bullet_prefix(c: Candidate, excerpt: str | None = None) -> str:
    """Everything of a bullet before the excerpt (``excerpt=None`` = worst case, used for estimates)."""
    title = sanitize(c.title)
    if c.candidate_type == CandidateType.chunk:
        details = []
        if c.section and fold(c.section) != fold(c.title):
            details.append(sanitize(c.section))
        if c.version is not None and c.version > 1:
            details.append(f"v{c.version}")
        suffix = f" ({' · '.join(details)})" if details else ""
        return f"- **{title}**{suffix} — "
    if c.candidate_type == CandidateType.session:
        role = _ROLE_LABELS.get(str(c.extra.get("role", "")), "Tour")
        return f"- **{role}** — "
    tags: list[str] = []
    if section_for(c) == "constraints" and c.memory_kind is not None:
        tags.append(f"_{MEMORY_KIND_LABELS[c.memory_kind]}_ · ")
    marker = ""
    if c.status == MemoryStatus.proposed.value:
        marker += f" ({memory_status_label(c.memory_kind, c.status)})"
    if c.is_org_memory:
        marker += " (organisation)"
    if excerpt is not None and not marker and _starts_with_title(c.title, excerpt):
        return f"- {''.join(tags)}"
    return f"- {''.join(tags)}**{title}**{marker} — "


def bullet(c: Candidate, excerpt: str, citation: str) -> str:
    return f"{bullet_prefix(c, excerpt)}{sanitize(excerpt)} [{citation}]"


def source_type_label(c: Candidate) -> str:
    if c.candidate_type == CandidateType.chunk:
        return SOURCE_KIND_LABELS.get(c.source_kind, "Source") if c.source_kind else "Source"
    if c.candidate_type == CandidateType.session:
        return "Session"
    scope = MEMORY_SCOPE_LABELS.get(c.memory_scope, "projet") if c.memory_scope else "projet"
    kind = MEMORY_KIND_LABELS.get(c.memory_kind, "Mémoire") if c.memory_kind else "Mémoire"
    return f"Mémoire {scope} · {kind}"


def source_line(c: Candidate, citation: str) -> str:
    """``[S1] Titre — type · v2 · 12/09/2026 · uri``."""
    parts = [source_type_label(c)]
    if c.version is not None and c.candidate_type != CandidateType.session:
        parts.append(f"v{c.version}")
    if c.date is not None:
        parts.append(format_date_fr(c.date))
    if c.uri:
        parts.append(one_line(c.uri))
    return f"[{citation}] {sanitize(c.title)} — {' · '.join(parts)}"


def preamble(task: str, intent: Intent) -> str:
    task_line = one_line(task)
    if len(task_line) > TASK_PREVIEW_CHARS:
        task_line = task_line[: TASK_PREVIEW_CHARS - 1].rstrip() + "…"
    return (
        f"# Contexte ORBIT — {task_line}\n\n"
        f"_Intention : {INTENT_LABELS.get(intent, intent.value)}. "
        f"Chaque élément cite sa source [Sx] (liste en fin de document)._\n"
    )


# --- Token estimates (upper bounds) -------------------------------------------------------------------


def item_overhead_tokens(c: Candidate) -> int:
    """Tokens of a bullet without its excerpt, plus its source line (upper bound)."""
    return (
        estimate_tokens(bullet_prefix(c))
        + estimate_tokens(f" [{_CITATION_PLACEHOLDER}]\n")
        + estimate_tokens(source_line(c, _CITATION_PLACEHOLDER) + "\n")
        + 1
    )


def section_header_tokens(section: str) -> int:
    return estimate_tokens(f"\n## {SECTION_TITLES.get(section, section)}\n\n") + 1


def base_overhead_tokens(task: str = "", intent: Intent = Intent.general) -> int:
    return (
        estimate_tokens(preamble(task or "x" * TASK_PREVIEW_CHARS, intent))
        + estimate_tokens(f"\n## {SOURCES_HEADING}\n\n")
        + 2
    )


# --- Rendering ----------------------------------------------------------------------------------------


@dataclass(slots=True)
class Packaged:
    markdown: str
    tokens_used: int
    ordered: list[Decision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def assign_citations(included: Sequence[Decision]) -> list[Decision]:
    """Order included decisions by section then selection order, and number them S1..Sn."""
    position = {id(d): index for index, d in enumerate(included)}
    section_rank = {name: index for index, (name, _title) in enumerate(SECTIONS)}
    ordered = sorted(included, key=lambda d: (section_rank[section_for(d.candidate)], position[id(d)]))
    for index, decision in enumerate(ordered, start=1):
        decision.citation = f"S{index}"
        decision.order = index
    return ordered


def classification_warnings(included: Sequence[Decision]) -> list[str]:
    levels = sorted(
        {
            int(d.candidate.classification)
            for d in included
            if int(d.candidate.classification) >= RESTRICTED_CLASSIFICATION_MIN
        },
        reverse=True,
    )
    return [w for w in (classification_warning(level) for level in levels) if w]


def render(task: str, intent: Intent, included: Sequence[Decision]) -> Packaged:
    """Assemble the Markdown context. ``included`` must carry their excerpts (compression done)."""
    ordered = assign_citations(included)
    lines: list[str] = [preamble(task, intent)]
    if not ordered:
        lines.append(EMPTY_CONTEXT)
    for name, title in SECTIONS:
        members = [d for d in ordered if section_for(d.candidate) == name]
        if not members:
            continue
        lines.append(f"\n## {title}\n")
        for d in members:
            lines.append(bullet(d.candidate, d.excerpt, d.citation or ""))
    if ordered:
        lines.append(f"\n## {SOURCES_HEADING}\n")
        for d in ordered:
            lines.append(source_line(d.candidate, d.citation or ""))
    markdown = "\n".join(lines).rstrip() + "\n"
    return Packaged(
        markdown=markdown,
        tokens_used=estimate_tokens(markdown),
        ordered=ordered,
        warnings=classification_warnings(ordered),
    )

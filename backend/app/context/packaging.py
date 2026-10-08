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

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.config import settings
from app.context import spotlight
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
INDEX_HEADING = "Index des sources et décisions"
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
    return spotlight.neutralize(one_line(value).replace("[S", "[ S"))


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


def spotlight_overhead_tokens() -> int:
    if not spotlight.enabled():
        return 0
    return estimate_tokens(f"{spotlight.NOTICE}\n{spotlight.OPEN}\n{spotlight.CLOSE}\n") + 2


def base_overhead_tokens(task: str = "", intent: Intent = Intent.general) -> int:
    return (
        max(
            estimate_tokens(preamble(task or "x" * TASK_PREVIEW_CHARS, intent)),
            estimate_tokens(CACHE_HEADER)
            + estimate_tokens(task_block(task or "x" * TASK_PREVIEW_CHARS, intent)),
        )
        + estimate_tokens(f"\n## {SOURCES_HEADING}\n\n")
        + spotlight_overhead_tokens()
        + 2
    )


# --- Rendering ----------------------------------------------------------------------------------------


@dataclass(slots=True)
class Packaged:
    markdown: str
    tokens_used: int
    ordered: list[Decision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: §C1: the request-independent beginning of ``markdown`` (empty when the layout is disabled).
    prefix: str = ""

    @property
    def prefix_hash(self) -> str | None:
        return hashlib.sha256(self.prefix.encode("utf-8")).hexdigest() if self.prefix else None

    @property
    def prefix_tokens(self) -> int:
        return estimate_tokens(self.prefix) if self.prefix else 0


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


def render(
    task: str,
    intent: Intent,
    included: Sequence[Decision],
    *,
    progressive: bool = False,
    section_order: Sequence[str] | None = None,
) -> Packaged:
    """Assemble the Markdown context. ``included`` must carry their excerpts (compression done)."""
    if settings.context_cache_ordering or progressive or section_order:
        return render_cache_aware(
            task, intent, included, progressive=progressive, section_order=section_order
        )
    ordered = assign_citations(included)
    lines: list[str] = [preamble(task, intent)]
    if not ordered:
        lines.append(EMPTY_CONTEXT)
    spotlighted = bool(ordered) and spotlight.enabled()
    if spotlighted:
        # §A2: everything below comes from the sources — untrusted data, never instructions.
        lines.append(spotlight.NOTICE)
        lines.append(spotlight.OPEN)
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
    if spotlighted:
        lines.append(spotlight.CLOSE)
    markdown = "\n".join(lines).rstrip() + "\n"
    return Packaged(
        markdown=markdown,
        tokens_used=estimate_tokens(markdown),
        ordered=ordered,
        warnings=classification_warnings(ordered),
    )


# --- §C1 prompt-cache-aware layout -------------------------------------------------------------------

#: Sections whose items belong to the stable prefix (snapshot items are stable whatever their section).
STABLE_SECTIONS = frozenset({"decisions", "constraints"})
CACHE_HEADER = (
    "# Contexte ORBIT\n\n"
    "_Chaque élément cite sa source [Sx] (liste en fin de document). "
    "La tâche et son intention figurent en fin de document._\n"
)


def is_stable(c: Candidate) -> bool:
    """Items of the stable prefix: decisions in force, constraints & risks, snapshot (pinned) items."""
    return bool(c.pinned) or section_for(c) in STABLE_SECTIONS


def task_block(task: str, intent: Intent) -> str:
    task_line = one_line(task)
    if len(task_line) > TASK_PREVIEW_CHARS:
        task_line = task_line[: TASK_PREVIEW_CHARS - 1].rstrip() + "…"
    return f"\n## Tâche\n\n{task_line}\n\n_Intention : {INTENT_LABELS.get(intent, intent.value)}._"


def _ordered_sections(section_order: Sequence[str] | None) -> list[tuple[str, str]]:
    """Profile order first (§C3), then any remaining section in the default order."""
    names = [n for n in (section_order or ()) if n in SECTION_TITLES]
    names += [n for n, _ in SECTIONS if n not in names]
    return [(n, SECTION_TITLES[n]) for n in names]


def _render_sections(
    lines: list[str], members: Sequence[Decision], section_order: Sequence[str] | None = None
) -> None:
    for name, title in _ordered_sections(section_order):
        group = [d for d in members if section_for(d.candidate) == name]
        if not group:
            continue
        lines.append(f"\n## {title}\n")
        for d in group:
            lines.append(bullet(d.candidate, d.excerpt, d.citation or ""))


def index_ref(c: Candidate) -> str | None:
    """Identifier an agent passes to the §C2 tools (chunk id, memory item id)."""
    if c.candidate_type == CandidateType.chunk:
        return c.id
    if c.candidate_type == CandidateType.memory and c.memory_item_id is not None:
        return str(c.memory_item_id)
    return None


def expand_tool(c: Candidate) -> str | None:
    if c.candidate_type == CandidateType.chunk:
        return "expand_source"
    if c.candidate_type == CandidateType.memory:
        return "get_decision" if c.memory_kind == MemoryKind.decision else "get_memory_item"
    return None


def index_line(c: Candidate, citation: str) -> str:
    """Progressive mode: the source line plus the identifier and the tool that expands it."""
    ref, tool = index_ref(c), expand_tool(c)
    suffix = f" · id={ref} → {tool}" if ref and tool else ""
    return source_line(c, citation) + suffix


def progressive_summary(ordered: Sequence[Decision]) -> str:
    counts = []
    for name, title in SECTIONS:
        n = sum(1 for d in ordered if section_for(d.candidate) == name)
        if n:
            counts.append(f"{title.lower()} : {n}")
    return (
        "\n## Résumé (contexte progressif)\n\n"
        f"{len(ordered)} élément{'s' if len(ordered) > 1 else ''} retenu{'s' if len(ordered) > 1 else ''}"
        f"{' — ' + ' · '.join(counts) if counts else ''}. Chaque élément n'est servi qu'en aperçu : l'index "
        "ci-dessous donne son identifiant et l'outil MCP qui renvoie le détail (expand_source, "
        "get_decision, get_memory_item) ; search_more lance une recherche complémentaire."
    )


def render_cache_aware(
    task: str,
    intent: Intent,
    included: Sequence[Decision],
    *,
    progressive: bool = False,
    section_order: Sequence[str] | None = None,
) -> Packaged:
    """Stable prefix (header, untrusted-data notice, stable items in a request-independent order) then
    variable items, the source list and the task: two requests serving the same stable items share a
    byte-identical prefix, which a prompt cache (e.g. Anthropic ``cache_control``) can reuse."""
    position = {id(d): index for index, d in enumerate(included)}
    section_rank = {name: index for index, (name, _title) in enumerate(_ordered_sections(section_order))}
    stable = sorted(
        (d for d in included if is_stable(d.candidate)),
        key=lambda d: (section_rank[section_for(d.candidate)], d.candidate.key),
    )
    variable = sorted(
        (d for d in included if not is_stable(d.candidate)),
        key=lambda d: (section_rank[section_for(d.candidate)], position[id(d)]),
    )
    ordered = [*stable, *variable]
    for index, decision in enumerate(ordered, start=1):
        decision.citation = f"S{index}"
        decision.order = index
    lines: list[str] = [CACHE_HEADER]
    spotlighted = spotlight.enabled()
    if spotlighted:
        lines.append(spotlight.NOTICE)
        lines.append(spotlight.OPEN)
    _render_sections(lines, stable, section_order)
    prefix = "\n".join(lines) + "\n"
    rest: list[str] = []
    if not ordered:
        rest.append(EMPTY_CONTEXT)
    elif progressive:
        rest.append(progressive_summary(ordered))
    _render_sections(rest, variable, section_order)
    if ordered:
        rest.append(f"\n## {INDEX_HEADING if progressive else SOURCES_HEADING}\n")
        line = index_line if progressive else source_line
        rest.extend(line(d.candidate, d.citation or "") for d in ordered)
    if spotlighted:
        rest.append(spotlight.CLOSE)
    rest.append(task_block(task, intent))
    markdown = prefix + "\n".join(rest).rstrip() + "\n"
    return Packaged(
        markdown=markdown,
        tokens_used=estimate_tokens(markdown),
        ordered=ordered,
        warnings=classification_warnings(ordered),
        prefix=prefix if settings.context_cache_ordering else "",
    )

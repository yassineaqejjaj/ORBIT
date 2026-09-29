"""``select`` stage (ARCHITECTURE §9.6): conflicts, duplicates, MMR and greedy budget filling.

1. **Conflicts** — ``contradicts`` relations between candidates: the most reliable side wins
   (validated > proposed, then more recent, then confidence); the other ⇒ ``EXCLUDED_CONFLICT``.
   The source extracts a defeated memory item was extracted from (its provenance chunks) are
   excluded with it, unless they also back the winner: the contradicted statement is not re-served.
2. **Duplicates** — cosine > 0.92 between embeddings when both are known, otherwise Jaccard of word
   shingles > 0.8 ⇒ ``EXCLUDED_DUPLICATE`` (``related_citation`` points to the kept item).
3. **MMR** (λ = 0.7) orders the remaining candidates to balance relevance and diversity.
4. **Priority** — pinned snapshot items, then validated decisions and constraints, requirements,
   risks, facts, preferences, then source extracts and session turns.
5. **Greedy budget fill** — each item gets a token allowance (its compressed excerpt must fit);
   items that no longer fit ⇒ ``EXCLUDED_BUDGET`` (« 380 tokens, budget restant 120 »).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import packaging
from app.context.textutils import cosine, jaccard, shingles, terms
from app.enums import CandidateType, MemoryKind, MemoryStatus, ReasonCode, RelationType
from app.governance.freshness import as_aware
from app.governance.policy import Candidate, Verdict, format_date_iso, format_score, included_verdict
from app.models import MemoryItem, Relation

DUPLICATE_COSINE = 0.92
DUPLICATE_JACCARD = 0.8
#: Above this shingle Jaccard two near-duplicates are copies of one text: the earliest one is kept.
IDENTICAL_JACCARD = 0.98
MMR_LAMBDA = 0.7
#: An item is only worth including with at least this many tokens of excerpt (or its full text).
MIN_ITEM_TOKENS = 30


@dataclass(slots=True)
class Decision:
    """Outcome for one candidate: governance/selection verdict plus the served excerpt."""

    candidate: Candidate
    verdict: Verdict
    #: Winner of a conflict / kept item of a duplicate pair.
    related: Candidate | None = None
    allowance: int = 0
    excerpt: str = ""
    tokens: int = 0
    citation: str | None = None
    related_citation: str | None = None
    rank: int | None = None
    order: int = 0

    @property
    def included(self) -> bool:
        return self.verdict.included


@dataclass(slots=True)
class SelectionResult:
    included: list[Decision] = field(default_factory=list)
    excluded: list[Decision] = field(default_factory=list)


# --- Priority tiers -----------------------------------------------------------------------------------


def priority_tier(c: Candidate) -> int:
    """Lower is served first (see module docstring)."""
    if c.pinned:
        return 0
    if c.candidate_type == CandidateType.chunk:
        return 6
    if c.candidate_type == CandidateType.session:
        return 7
    kind = c.memory_kind
    validated = c.status == MemoryStatus.validated.value
    if kind in (MemoryKind.decision, MemoryKind.constraint):
        return 1 if validated else 2
    if kind == MemoryKind.requirement:
        return 2
    if kind == MemoryKind.risk:
        return 3
    if kind in (MemoryKind.fact, MemoryKind.summary):
        return 4
    return 5  # preferences


# --- Conflicts ----------------------------------------------------------------------------------------


async def load_contradictions(
    session: AsyncSession, project_id: uuid.UUID, candidates: Sequence[Candidate]
) -> list[tuple[str, str]]:
    """``contradicts`` relations between candidates, as pairs of candidate keys.

    Relation endpoints may reference any version of a memory item (resolved through its lineage),
    a chunk, or a whole document (applies to every chunk candidate of that document).
    """
    node_to_keys: dict[uuid.UUID, set[str]] = {}
    lineages: dict[uuid.UUID, str] = {}
    for c in candidates:
        if c.candidate_type == CandidateType.chunk:
            node_to_keys.setdefault(uuid.UUID(c.id), set()).add(c.key)
            if c.document_id is not None:
                node_to_keys.setdefault(c.document_id, set()).add(c.key)
        elif c.candidate_type == CandidateType.memory and c.lineage_id is not None:
            lineages[c.lineage_id] = c.key
    if lineages:
        rows = await session.execute(
            select(MemoryItem.id, MemoryItem.lineage_id).where(MemoryItem.lineage_id.in_(list(lineages)))
        )
        for item_id, lineage_id in rows.tuples():
            node_to_keys.setdefault(item_id, set()).add(lineages[lineage_id])
    if not node_to_keys:
        return []
    ids = list(node_to_keys)
    relations = await session.execute(
        select(Relation.src_id, Relation.dst_id).where(
            Relation.project_id == project_id,
            Relation.rel_type == RelationType.contradicts,
            or_(Relation.src_id.in_(ids), Relation.dst_id.in_(ids)),
        )
    )
    pairs: set[tuple[str, str]] = set()
    for src, dst in relations.tuples():
        for a in node_to_keys.get(src, ()):
            for b in node_to_keys.get(dst, ()):
                if a != b:
                    pairs.add((min(a, b), max(a, b)))
    return sorted(pairs)


def _authority(c: Candidate) -> int:
    if c.candidate_type == CandidateType.memory:
        return 2 if c.status == MemoryStatus.validated.value else 1
    if c.candidate_type == CandidateType.chunk:
        return 1
    return 0


def _timestamp(c: Candidate) -> float:
    return as_aware(c.date).timestamp() if c.date else 0.0


def _strength(c: Candidate) -> tuple[int, float, float, float]:
    return (_authority(c), _timestamp(c), c.confidence, c.score)


def conflict_detail(winner: Candidate, loser: Candidate) -> str:
    title = f"“{winner.title}”"
    if _authority(winner) != _authority(loser):
        return f"contredit par une source validée : {title}"
    if _timestamp(winner) != _timestamp(loser):
        date = format_date_iso(winner.date)
        return f"contredit par une source plus récente : {title}" + (f" ({date})" if date else "")
    if winner.confidence != loser.confidence:
        return f"contredit par une source plus fiable (confiance {format_score(winner.confidence)}) : {title}"
    return f"contredit par une source plus pertinente : {title}"


def resolve_conflicts(
    candidates: Sequence[Candidate], pairs: Iterable[tuple[str, str]]
) -> dict[str, tuple[Candidate, str]]:
    """Losers of contradiction pairs: ``key -> (winner, detail)``. The strongest side is processed
    first so an already-defeated item never excludes another one."""
    by_key = {c.key: c for c in candidates}
    partners: dict[str, set[str]] = {}
    for a, b in pairs:
        if a in by_key and b in by_key:
            partners.setdefault(a, set()).add(b)
            partners.setdefault(b, set()).add(a)
    losers: dict[str, tuple[Candidate, str]] = {}
    for key in sorted(partners, key=lambda k: _strength(by_key[k]), reverse=True):
        if key in losers:
            continue
        winner = by_key[key]
        for other_key in sorted(partners[key]):
            if other_key in losers:
                continue
            other = by_key[other_key]
            if _strength(other) < _strength(winner):
                losers[other_key] = (winner, conflict_detail(winner, other))
    return losers


def propagate_to_sources(
    candidates: Sequence[Candidate], losers: dict[str, tuple[Candidate, str]]
) -> dict[str, tuple[Candidate, str]]:
    """Provenance chunks of defeated memory items (``key -> (winner, detail)``), see module docstring."""
    by_key = {c.key: c for c in candidates}
    chunks = {c.id: c for c in candidates if c.candidate_type == CandidateType.chunk}
    extra: dict[str, tuple[Candidate, str]] = {}
    for key, (winner, detail) in losers.items():
        loser = by_key.get(key)
        if loser is None or loser.candidate_type != CandidateType.memory:
            continue
        for chunk_id in sorted(loser.provenance_chunk_ids):
            chunk = chunks.get(chunk_id)
            if chunk is None or chunk.key in losers or chunk.key in extra or chunk.key == winner.key:
                continue
            if chunk_id in winner.provenance_chunk_ids:
                continue
            extra[chunk.key] = (winner, detail)
    return extra


# --- Similarity ---------------------------------------------------------------------------------------


class SimilarityCache:
    """Lazily computed shingles / term sets per candidate."""

    def __init__(self) -> None:
        self._shingles: dict[str, set[tuple[str, ...]]] = {}
        self._terms: dict[str, set[str]] = {}

    def shingles(self, c: Candidate) -> set[tuple[str, ...]]:
        if c.key not in self._shingles:
            self._shingles[c.key] = shingles(c.text or c.title)
        return self._shingles[c.key]

    def terms(self, c: Candidate) -> set[str]:
        if c.key not in self._terms:
            self._terms[c.key] = set(terms(f"{c.title} {c.text}"))
        return self._terms[c.key]

    def is_duplicate(self, a: Candidate, b: Candidate) -> bool:
        """cosine > 0.92 **or** shingle Jaccard > 0.8 (§9.6): embeddings include the title, so the same
        passage forwarded under another title (e.g. an e-mail "TR:") can fall below the cosine threshold."""
        sim = cosine(a.embedding, b.embedding)
        if sim is not None and sim > DUPLICATE_COSINE:
            return True
        return jaccard(self.shingles(a), self.shingles(b)) > DUPLICATE_JACCARD

    def diversity_similarity(self, a: Candidate, b: Candidate) -> float:
        sim = cosine(a.embedding, b.embedding)
        if sim is not None:
            return max(0.0, sim)
        return jaccard(self.terms(a), self.terms(b))


def find_duplicates(
    ordered: Sequence[Candidate], cache: SimilarityCache | None = None
) -> dict[str, Candidate]:
    """Near-duplicates: ``key -> kept candidate`` (the first one in ``ordered`` is kept)."""
    cache = cache or SimilarityCache()
    kept: list[Candidate] = []
    duplicates: dict[str, Candidate] = {}
    for c in ordered:
        original = next((k for k in kept if cache.is_duplicate(c, k)), None)
        if original is None:
            kept.append(c)
        elif _is_earlier_copy(c, original, cache):
            # Same text published earlier (e.g. the document an e-mail "TR:" forwards): keep the original.
            kept[kept.index(original)] = c
            for key, target in list(duplicates.items()):
                if target is original:
                    duplicates[key] = c
            duplicates[original.key] = c
        else:
            duplicates[c.key] = original
    return duplicates


def _is_earlier_copy(c: Candidate, kept: Candidate, cache: SimilarityCache) -> bool:
    """``c`` carries the same text as ``kept`` (not merely a similar one) and was published before it."""
    if c.candidate_type != kept.candidate_type or c.date is None or kept.date is None:
        return False
    if _timestamp(c) >= _timestamp(kept):
        return False
    return jaccard(cache.shingles(c), cache.shingles(kept)) >= IDENTICAL_JACCARD


def mmr_order(
    candidates: Sequence[Candidate], lam: float = MMR_LAMBDA, cache: SimilarityCache | None = None
) -> list[Candidate]:
    """Maximal Marginal Relevance ordering (λ·relevance − (1−λ)·max similarity to already picked)."""
    cache = cache or SimilarityCache()
    remaining = sorted(candidates, key=lambda c: c.score, reverse=True)
    picked: list[Candidate] = []
    max_sim: dict[str, float] = {c.key: 0.0 for c in remaining}
    while remaining:
        best_index = 0
        best_value = float("-inf")
        for index, c in enumerate(remaining):
            value = lam * c.score - (1 - lam) * max_sim[c.key]
            if value > best_value:
                best_value = value
                best_index = index
        chosen = remaining.pop(best_index)
        picked.append(chosen)
        for c in remaining:
            sim = cache.diversity_similarity(c, chosen)
            if sim > max_sim[c.key]:
                max_sim[c.key] = sim
    return picked


# --- Budget -------------------------------------------------------------------------------------------


def _clamp(value: float, low: int, high: int) -> int:
    return int(max(low, min(high, value)))


def item_cap(c: Candidate, token_budget: int) -> int:
    """Maximum excerpt size per item, proportional to the budget."""
    if c.candidate_type == CandidateType.chunk:
        return _clamp(token_budget * 0.06, 100, 350)
    if c.candidate_type == CandidateType.session:
        return _clamp(token_budget * 0.03, 50, 150)
    return _clamp(token_budget * 0.04, 60, 200)


def fill_budget(
    ordered: Sequence[Candidate],
    token_budget: int,
    *,
    now: datetime,
    overhead: Callable[[Candidate], int] = packaging.item_overhead_tokens,
    base_overhead: int | None = None,
) -> tuple[list[Decision], list[Decision]]:
    """Greedy fill in the given order. Returns ``(included, excluded_for_budget)``."""
    remaining = token_budget - (packaging.base_overhead_tokens() if base_overhead is None else base_overhead)
    sections_open: set[str] = set()
    included: list[Decision] = []
    excluded: list[Decision] = []
    for c in ordered:
        section = packaging.section_for(c)
        header = 0 if section in sections_open else packaging.section_header_tokens(section)
        cost_overhead = header + overhead(c)
        wanted = min(max(c.tokens, 1), item_cap(c, token_budget))
        room = remaining - cost_overhead
        minimum = min(wanted, MIN_ITEM_TOKENS)
        if room >= minimum and room > 0:
            allowance = min(wanted, room)
            included.append(Decision(candidate=c, verdict=included_verdict(c, now), allowance=allowance))
            remaining -= cost_overhead + allowance
            sections_open.add(section)
        else:
            detail = f"{cost_overhead + wanted} tokens, budget restant {max(remaining, 0)}"
            excluded.append(Decision(candidate=c, verdict=Verdict(ReasonCode.EXCLUDED_BUDGET, detail)))
    return included, excluded


# --- Orchestration --------------------------------------------------------------------------------------


def select_candidates(
    eligible: Sequence[Candidate],
    *,
    token_budget: int,
    now: datetime,
    contradictions: Iterable[tuple[str, str]] = (),
    base_overhead: int | None = None,
) -> SelectionResult:
    """Run conflicts → duplicates → MMR → priority → budget on governance-approved candidates."""
    result = SelectionResult()
    cache = SimilarityCache()

    losers = resolve_conflicts(eligible, contradictions)
    losers.update(propagate_to_sources(eligible, losers))
    survivors: list[Candidate] = []
    for c in eligible:
        if c.key in losers:
            winner, detail = losers[c.key]
            result.excluded.append(
                Decision(candidate=c, verdict=Verdict(ReasonCode.EXCLUDED_CONFLICT, detail), related=winner)
            )
        else:
            survivors.append(c)

    # Pinned items first, then by score: the first occurrence of a near-duplicate is kept.
    by_priority = sorted(survivors, key=lambda c: (not c.pinned, -c.score))
    duplicates = find_duplicates(by_priority, cache)
    unique: list[Candidate] = []
    for c in by_priority:
        if c.key in duplicates:
            kept = duplicates[c.key]
            result.excluded.append(
                Decision(
                    candidate=c,
                    verdict=Verdict(ReasonCode.EXCLUDED_DUPLICATE, f"quasi-identique à “{kept.title}”"),
                    related=kept,
                )
            )
        else:
            unique.append(c)

    ordered = mmr_order(unique, cache=cache)
    position = {c.key: index for index, c in enumerate(ordered)}
    ordered.sort(key=lambda c: (priority_tier(c), position[c.key]))

    included, over_budget = fill_budget(ordered, token_budget, now=now, base_overhead=base_overhead)
    result.included.extend(included)
    result.excluded.extend(over_budget)
    return result

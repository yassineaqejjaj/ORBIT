"""Context assembler (ARCHITECTURE §9): the orchestrator of the context engine.

``assemble_context`` runs the timed stages understand → retrieve → fuse → rerank → govern → select →
compress → package → persist and returns the :class:`ContextPackage` of docs/API.md:

* identity: principals = ``effective_principals`` of the ``on_behalf_of`` member (or of the calling
  human); effective clearance = min(user, agent, human caller, ``max_classification``);
* retrieval pre-filters on the project only; governance (``app.governance.policy``) explains every
  exclusion with a ``ReasonCode``; the served text of chunks is always ``text_redacted``;
* ``explain`` defaults to ``True`` for humans and ``False`` for agents (agents only get
  ``exclusion_summary`` counters); exclusions are shown according to the non-leak rules of
  ``app.context.visibility`` for the **caller** (never the ``on_behalf_of`` user);
* persists ``context_requests`` + every ``context_decisions`` row (+ snapshot when ``save_snapshot``),
  an audit entry, OTel spans per stage and Prometheus metrics; ``trace_id`` = OTel trace id;
* ``warnings`` include ``classification_warning`` for C2/C3 content served.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.context import (
    compression,
    packaging,
    persistence,
    profiles,
    query_rewrite,
    rerank,
    retrieval,
    selection,
    sufficiency,
)
from app.context import snapshots as snapshot_service
from app.context.selection import Decision
from app.context.understanding import Understanding, embed_query, understand
from app.context.visibility import Viewer
from app.db import utcnow
from app.deps import ProjectAccess
from app.enums import (
    GOVERNANCE_ORDER,
    AgentKind,
    ContextRequestStatus,
    Intent,
    MemoryKind,
    MemoryScope,
    PrincipalKind,
    ReasonCode,
    Role,
    SourceKind,
)
from app.errors import ApiError, forbidden, not_found, validation_error
from app.governance.acl import effective_clearance, effective_principals
from app.governance.policy import Candidate, GovernanceContext, Verdict, evaluate, format_date_fr
from app.llm import client as llm_client
from app.memory import skills
from app.models import Agent, ContextRequest, ContextSnapshot, User
from app.observability.metrics import observe_cache_prefix, observe_context_request
from app.observability.tracing import current_trace_id, get_tracer
from app.schemas.context import (
    AppliedProfile,
    CacheControl,
    CacheHintBlock,
    ContextConfig,
    ContextIndexEntry,
    ContextPackage,
    ContextRequestIn,
    ContextSnapshotInfo,
    ContextTimings,
)
from app.search.tokens import estimate_tokens, truncate_to_tokens
from app.services import audit
from app.services import projects as project_service
from app.services.audit import AuditAction

logger = logging.getLogger("orbit.context.assembler")
tracer = get_tracer("orbit.context")

MIN_TOKEN_BUDGET = 500
MAX_TOKEN_BUDGET = 32_000
ALL_SCOPES: frozenset[MemoryScope] = frozenset(MemoryScope)
RETRIEVAL_LABEL = "hybrid-bm25-knn-rrf-v1"
#: Fused-score factor of hits found by query rewrites (round 1) and by targeted rounds (§B3/§B4).
REWRITE_DISCOUNT = 0.9
ROUND_DISCOUNT = 0.85
STAGES = ("understand", "rewrite", "retrieve", "fuse", "rerank", "govern", "select", "compress", "package")
FAILURE_MESSAGE = "Échec de l'assemblage du contexte"

_EXCLUSION_ORDER = {code: index for index, code in enumerate(GOVERNANCE_ORDER)}


@dataclass(slots=True)
class ResolvedRequest:
    """Validated request parameters and the effective identity used by governance."""

    access: ProjectAccess
    body: ContextRequestIn
    agent: Agent | None
    on_behalf_of: User | None
    principals: set[str]
    clearance: int
    scopes: set[MemoryScope]
    source_kinds: set[SourceKind] | None
    token_budget: int
    min_relevance: float
    freshness_days: dict[str, int]
    explain: bool
    base_snapshot: ContextSnapshot | None
    save_name: str | None
    viewer: Viewer
    #: §C3 profile of the requesting agent's kind (``None`` for humans or when disabled).
    profile: profiles.Profile | None = None

    @property
    def project_id(self) -> uuid.UUID:
        return self.access.project_id


@dataclass(slots=True)
class _Timer:
    timings: dict[str, float] = field(default_factory=dict)
    #: Iterative retrieval rounds (§B4), serialised in ``timings["rounds"]``.
    rounds: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str, **attributes: Any) -> Iterator[Any]:
        with tracer.start_as_current_span(f"context.{name}") as span:
            for key, value in attributes.items():
                span.set_attribute(f"orbit.{key}", value)
            begin = time.perf_counter()
            try:
                yield span
            finally:
                self.timings[name] = round((time.perf_counter() - begin) * 1000, 1)

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 1)


# --- Request resolution (validation errors happen before any work) -------------------------------------


def clamp_budget(value: int | None, default: int) -> int:
    budget = value if value is not None else default
    return max(MIN_TOKEN_BUDGET, min(MAX_TOKEN_BUDGET, int(budget)))


async def resolve_request(
    session: AsyncSession, access: ProjectAccess, body: ContextRequestIn
) -> ResolvedRequest:
    principal = access.principal
    project = access.project
    project_settings = project_service.normalize_settings(project.settings)

    agent: Agent | None
    if principal.is_agent:
        agent = principal.agent
        if body.agent_id is not None and agent is not None and body.agent_id != agent.id:
            raise validation_error("agent_id ne correspond pas à la clé d'agent utilisée")
    elif body.agent_id is not None:
        agent = await session.get(Agent, body.agent_id)
        if agent is None or agent.project_id != project.id:
            raise validation_error("Agent inconnu pour ce projet")
        if not agent.active:
            raise validation_error("Cet agent est révoqué : impossible de simuler ses requêtes")
    else:
        agent = None

    on_behalf_of: User | None = None
    member_role: Role | None = None
    if body.on_behalf_of is not None and not (principal.is_user and body.on_behalf_of == principal.user_id):
        if principal.is_user and not access.can_see_restricted_details:
            raise forbidden(
                "Seuls les propriétaires du projet peuvent assembler un contexte "
                "pour le compte d'un autre membre"
            )
        on_behalf_of = await session.get(User, body.on_behalf_of)
        if on_behalf_of is not None:
            member_role = await project_service.get_member_role(session, project.id, on_behalf_of.id)
            if member_role is None and on_behalf_of.is_admin:
                member_role = Role.owner
        if on_behalf_of is None or member_role is None:
            raise validation_error("on_behalf_of doit désigner un membre du projet")
        principals = effective_principals(access, on_behalf_of, member_role)
    else:
        on_behalf_of = principal.user if principal.is_user else None
        principals = effective_principals(access)

    clearance = effective_clearance(on_behalf_of, agent, body.max_classification)
    if principal.is_user:
        clearance = min(clearance, int(principal.clearance))
    if on_behalf_of is None and agent is None:
        clearance = min(
            int(principal.clearance), body.max_classification if body.max_classification is not None else 3
        )

    base_snapshot: ContextSnapshot | None = None
    if body.base_snapshot is not None:
        base_name = body.base_snapshot.name.strip().lower()
        base_snapshot = await snapshot_service.get_snapshot(
            session, project.id, base_name, body.base_snapshot.version or "latest"
        )
        if base_snapshot is None:
            version = f" v{body.base_snapshot.version}" if body.base_snapshot.version else ""
            raise not_found(f"Snapshot « {base_name} »{version} introuvable dans ce projet")
    save_name = snapshot_service.normalize_name(body.save_snapshot.name) if body.save_snapshot else None
    profile = (
        profiles.profile_for(project, agent.kind) if agent is not None and settings.context_profiles else None
    )
    default_budget = (profile.token_budget if profile else None) or int(
        project_settings["default_token_budget"]
    )
    default_relevance = (
        profile.min_relevance
        if profile and profile.min_relevance is not None
        else float(project_settings["min_relevance"])
    )

    return ResolvedRequest(
        access=access,
        body=body,
        agent=agent,
        on_behalf_of=on_behalf_of,
        principals=principals,
        clearance=clearance,
        scopes=set(body.scopes) if body.scopes is not None else set(ALL_SCOPES),
        source_kinds=set(body.source_kinds) if body.source_kinds is not None else None,
        token_budget=clamp_budget(body.token_budget, default_budget),
        min_relevance=float(body.min_relevance if body.min_relevance is not None else default_relevance),
        freshness_days=dict(project_settings["freshness_days"]),
        explain=body.explain if body.explain is not None else principal.is_user,
        base_snapshot=base_snapshot,
        save_name=save_name,
        viewer=Viewer.from_access(access),
        profile=profile,
    )


# --- Pipeline -----------------------------------------------------------------------------------------


def _governance_context(resolved: ResolvedRequest, now: Any) -> GovernanceContext:
    body = resolved.body
    return GovernanceContext(
        project_id=resolved.project_id,
        principals=resolved.principals,
        clearance=resolved.clearance,
        requester_user_id=resolved.on_behalf_of.id if resolved.on_behalf_of else None,
        session_id=body.session_id,
        scopes=resolved.scopes,
        source_kinds=resolved.source_kinds,
        freshness_days=resolved.freshness_days,
        freshness_override_days=body.freshness_days,
        min_relevance=resolved.min_relevance,
        now=now,
        include_sources=body.include_sources,
    )


def _enforce_budget(
    task: str,
    intent: Intent,
    included: list[Decision],
    excluded: list[Decision],
    budget: int,
    *,
    progressive: bool = False,
    section_order: list[str] | None = None,
) -> packaging.Packaged:
    """Render, and in the rare case the estimate is exceeded drop the lowest-priority items."""
    packaged = packaging.render(task, intent, included, progressive=progressive, section_order=section_order)
    while packaged.tokens_used > budget and included:
        dropped = included.pop()
        remaining = budget - (packaged.tokens_used - dropped.tokens)
        dropped.verdict = dropped.verdict.__class__(
            ReasonCode.EXCLUDED_BUDGET,
            f"{dropped.tokens + packaging.item_overhead_tokens(dropped.candidate)} tokens, "
            f"budget restant {max(remaining, 0)}",
        )
        dropped.citation = None
        dropped.excerpt = ""
        dropped.tokens = 0
        excluded.append(dropped)
        packaged = packaging.render(
            task, intent, included, progressive=progressive, section_order=section_order
        )
    return packaged


def _apply_profile_sections(
    profile: profiles.Profile, eligible: list[Candidate], excluded: list[Decision]
) -> list[Candidate]:
    """§C3: sections absent from the agent kind's profile are not served (explained exclusion)."""
    kept: list[Candidate] = []
    for candidate in eligible:
        section = packaging.section_for(candidate)
        if section in profile.sections or candidate.pinned:
            kept.append(candidate)
        else:
            detail = f"section « {packaging.SECTION_TITLES[section]} » hors du profil {profile.kind.value}"
            excluded.append(Decision(candidate=candidate, verdict=Verdict(ReasonCode.EXCLUDED_SCOPE, detail)))
    return kept


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _apply_procedure_scope(
    intent: str, agent_kind: str | None, eligible: list[Candidate], excluded: list[Decision]
) -> list[Candidate]:
    """§D1: a procedure restricted to other task types / agent kinds is not served (explained)."""
    kept: list[Candidate] = []
    for candidate in eligible:
        ok, detail = (
            skills.applies_to(candidate.skill_meta, intent, agent_kind)
            if candidate.memory_kind == MemoryKind.procedure and not candidate.pinned
            else (True, "")
        )
        if ok:
            kept.append(candidate)
        else:
            excluded.append(Decision(candidate=candidate, verdict=Verdict(ReasonCode.EXCLUDED_SCOPE, detail)))
    return kept


def progressive_index(included: list[Decision]) -> list[ContextIndexEntry]:
    entries = []
    for d in included:
        c = d.candidate
        ref, tool = packaging.index_ref(c), packaging.expand_tool(c)
        if not ref or not tool:
            continue
        entries.append(
            ContextIndexEntry(
                citation=d.citation or "",
                id=ref,
                candidate_type=c.candidate_type,
                title=c.title,
                memory_kind=c.memory_kind,
                tool=tool,
                tokens_full=estimate_tokens(c.text),
            )
        )
    return entries


def cache_hint_blocks(markdown: str, prefix: str) -> list[CacheHintBlock]:
    """§C1: the context as Anthropic text blocks, a ``cache_control`` breakpoint closing the prefix."""
    blocks = [CacheHintBlock(text=prefix, cache_control=CacheControl())]
    rest = markdown[len(prefix) :] if markdown.startswith(prefix) else ""
    if rest.strip():
        blocks.append(CacheHintBlock(text=rest))
    return blocks


async def _prefix_reused(
    session: AsyncSession, project_id: uuid.UUID, prefix_hash: str | None, now: Any
) -> bool:
    """A request of the project served the same stable prefix within the cache window (§C1)."""
    if not prefix_hash:
        return False
    since = now - timedelta(seconds=settings.context_cache_ttl_seconds)
    scalar = getattr(session, "scalar", None)  # unit tests drive the pipeline with a fake session
    if scalar is None:
        return False
    found = await scalar(
        select(ContextRequest.id)
        .where(
            ContextRequest.project_id == project_id,
            ContextRequest.created_at >= since,
            ContextRequest.params["cache"]["prefix_hash"].astext == prefix_hash,
        )
        .limit(1)
    )
    return found is not None


def _link_related(included: list[Decision], excluded: list[Decision]) -> None:
    citations = {d.candidate.key: d.citation for d in included if d.citation}
    for d in excluded:
        if d.related is None:
            continue
        citation = citations.get(d.related.key)
        d.related_citation = citation
        if citation and d.verdict.reason_code == ReasonCode.EXCLUDED_DUPLICATE:
            d.verdict = d.verdict.__class__(ReasonCode.EXCLUDED_DUPLICATE, f"quasi-identique à [{citation}]")


def _assign_ranks(decisions: list[Decision]) -> None:
    for rank, d in enumerate(sorted(decisions, key=lambda d: d.candidate.score, reverse=True), start=1):
        d.rank = rank


def _sorted_exclusions(excluded: list[Decision]) -> list[Decision]:
    def key(d: Decision) -> tuple[int, float]:
        code = d.verdict.reason_code
        return (_EXCLUSION_ORDER.get(code, len(_EXCLUSION_ORDER)), -d.candidate.score)

    return sorted(excluded, key=key)


def _params(resolved: ResolvedRequest, understanding: Understanding) -> dict[str, Any]:
    body = resolved.body
    return {
        "request": body.model_dump(mode="json", exclude_none=True),
        "explain": resolved.explain,
        "intent_inferred": understanding.intent_inferred,
        "terms": understanding.terms,
        "effective": {
            "on_behalf_of": str(resolved.on_behalf_of.id) if resolved.on_behalf_of else None,
            "agent_id": str(resolved.agent.id) if resolved.agent else None,
            "clearance": resolved.clearance,
            "principals": sorted(resolved.principals),
            "scopes": sorted(s.value for s in resolved.scopes),
            "source_kinds": sorted(k.value for k in resolved.source_kinds) if resolved.source_kinds else None,
            "min_relevance": resolved.min_relevance,
            "token_budget": resolved.token_budget,
            "freshness_override_days": body.freshness_days,
        },
        "base_snapshot": {
            "id": str(resolved.base_snapshot.id),
            "name": resolved.base_snapshot.name,
            "version": resolved.base_snapshot.version,
        }
        if resolved.base_snapshot
        else None,
    }


async def _embedded(queries: list[query_rewrite.RewrittenQuery]) -> list[tuple[str, list[float] | None]]:
    vectors = await asyncio.gather(*(embed_query(q.text) for q in queries))
    return [(q.text, vector) for q, (vector, _model) in zip(queries, vectors, strict=True)]


async def _iterative_retrieve(
    session: AsyncSession,
    resolved: ResolvedRequest,
    understanding: Understanding,
    rewritten: query_rewrite.Rewrite,
    timer: _Timer,
    *,
    pinned: list[retrieval.PinnedRef],
    base: Any,
) -> retrieval.RawRetrieval:
    """Round 1: the task and its rewrites (§B3). Rounds 2..``ORBIT_RETRIEVAL_MAX_ROUNDS`` (≤ 3): targeted
    searches of the sub-topics no retrieved item covers yet (§B4); stops early when everything is
    covered or a round finds nothing new. Every round is traced in ``timings.rounds``."""
    body = resolved.body
    scope = {
        "project_id": resolved.project_id,
        "include_chunks": body.include_sources,
        "include_memory": bool(resolved.scopes),
        "include_org_memory": MemoryScope.long_term in resolved.scopes,
    }
    begin = time.perf_counter()
    raw = await retrieval.retrieve(
        session,
        task=understanding.task,
        query_vector=understanding.query_vector,
        session_id=body.session_id if MemoryScope.short_term in resolved.scopes else None,
        pinned=pinned,
        pinned_label=f"{base.name}@v{base.version}" if base is not None else None,
        **scope,
    )
    found = len({h.id for h in raw.chunk_hits}) + len({h.id for h in raw.memory_hits})
    extra = rewritten.queries[: settings.query_rewrite_max_queries]
    if extra:
        found += await retrieval.search_more(
            session, raw, await _embedded(extra), discount=REWRITE_DISCOUNT, **scope
        )
    missing = query_rewrite.uncovered(rewritten.subtopics, retrieval.coverage_texts(raw))
    timer.rounds.append(
        _round(1, [query_rewrite.RewrittenQuery(understanding.task, "task"), *extra], found, missing, begin)
    )
    for number in range(2, settings.retrieval_max_rounds + 1):
        if not missing:
            break
        begin = time.perf_counter()
        targeted = [query_rewrite.RewrittenQuery(t, query_rewrite.KIND_SUBTOPIC) for t in missing]
        new = await retrieval.search_more(
            session, raw, await _embedded(targeted), discount=ROUND_DISCOUNT, **scope
        )
        missing = query_rewrite.uncovered(missing, retrieval.coverage_texts(raw))
        timer.rounds.append(_round(number, targeted, new, missing, begin))
        if new == 0:
            break
    return raw


def _round(
    number: int, queries: list[query_rewrite.RewrittenQuery], new: int, missing: list[str], begin: float
) -> dict[str, Any]:
    return {
        "round": number,
        "queries": [q.as_dict() for q in queries],
        "new_items": new,
        "uncovered": list(missing),
        "ms": round((time.perf_counter() - begin) * 1000, 1),
    }


async def _run(
    session: AsyncSession, resolved: ResolvedRequest, timer: _Timer, request_id: uuid.UUID, trace_id: str
) -> ContextPackage:
    body = resolved.body
    access = resolved.access
    principal = access.principal
    now = utcnow()

    with timer.stage("understand") as span:
        understanding = await understand(
            body.task, body.intent, resolved.agent.kind if resolved.agent else None
        )
        span.set_attribute("orbit.intent", understanding.intent.value)
        span.set_attribute("orbit.dense", understanding.query_vector is not None)

    with timer.stage("rewrite") as span:
        rewritten = await query_rewrite.rewrite(session, resolved.project_id, understanding.task)
        span.set_attribute("orbit.rewrite", rewritten.method)
        span.set_attribute("orbit.rewrite_queries", len(rewritten.queries))

    base = resolved.base_snapshot
    pinned = retrieval.pinned_refs(base.items or []) if base is not None else []
    with timer.stage("retrieve") as span:
        raw = await _iterative_retrieve(
            session, resolved, understanding, rewritten, timer, pinned=pinned, base=base
        )
        span.set_attribute("orbit.rounds", len(timer.rounds))
        span.set_attribute("orbit.chunk_hits", len(raw.chunk_hits))
        span.set_attribute("orbit.memory_hits", len(raw.memory_hits))
        agent_kind = AgentKind(resolved.agent.kind).value if resolved.agent is not None else None
        if settings.memory_skills and resolved.scopes:
            await retrieval.add_procedures(
                session,
                raw,
                resolved.project_id,
                intent=understanding.intent.value,
                agent_kind=agent_kind,
                limit=settings.skills_context_max,
            )
        as_of = _aware(body.as_of)
        if as_of is not None:
            await retrieval.apply_as_of(session, raw, as_of)
            raw.warnings.append(
                f"Mémoire telle que connue au {format_date_fr(as_of)} "
                "(les extraits de sources reflètent leur état actuel)"
            )

    with timer.stage("fuse") as span:
        candidates: list[Candidate] = retrieval.fuse(raw, session_id=body.session_id)
        span.set_attribute("orbit.candidates", len(candidates))

    with timer.stage("rerank") as span:
        reranker_used = await rerank.rerank(
            candidates,
            query=understanding.task,
            query_terms=understanding.terms,
            query_vector=understanding.query_vector,
            now=now,
        )
        span.set_attribute("orbit.reranker", reranker_used)

    with timer.stage("govern") as span:
        ctx = _governance_context(resolved, as_of or now)
        eligible: list[Candidate] = []
        excluded: list[Decision] = []
        for candidate in candidates:
            verdict = evaluate(candidate, ctx)
            if verdict is None:
                eligible.append(candidate)
            else:
                excluded.append(Decision(candidate=candidate, verdict=verdict))
        eligible = _apply_procedure_scope(understanding.intent.value, agent_kind, eligible, excluded)
        if resolved.profile is not None:
            eligible = _apply_profile_sections(resolved.profile, eligible, excluded)
        span.set_attribute("orbit.eligible", len(eligible))

    with timer.stage("select") as span:
        contradictions = await selection.load_contradictions(session, resolved.project_id, eligible)
        selected = selection.select_candidates(
            eligible,
            token_budget=resolved.token_budget,
            now=now,
            contradictions=contradictions,
            base_overhead=packaging.base_overhead_tokens(understanding.task, understanding.intent),
        )
        included = selected.included
        excluded.extend(selected.excluded)
        span.set_attribute("orbit.included", len(included))

    with timer.stage("compress"):
        await compression.compress(
            included,
            query_terms=understanding.terms,
            query_vector=understanding.query_vector,
            query=understanding.task,
        )

    progressive = body.mode == "progressive"
    if progressive:
        teaser = settings.context_progressive_excerpt_tokens
        for d in included:
            d.excerpt = truncate_to_tokens(d.excerpt, teaser)
            d.tokens = estimate_tokens(d.excerpt)
    with timer.stage("package") as span:
        packaged = _enforce_budget(
            understanding.task,
            understanding.intent,
            included,
            excluded,
            resolved.token_budget,
            progressive=progressive,
            section_order=resolved.profile.sections if resolved.profile else None,
        )
        included = packaged.ordered
        _link_related(included, excluded)
        _assign_ranks([*included, *excluded])
        excluded = _sorted_exclusions(excluded)
        summary = persistence.exclusion_summary(excluded)
        warnings = [*packaged.warnings, *raw.warnings]
        config = ContextConfig(
            retrieval=RETRIEVAL_LABEL
            if all(v == "hybrid" for v in raw.sources_used.values())
            else f"{RETRIEVAL_LABEL} (repli plein texte)",
            reranker=reranker_used,
            embedding_model=understanding.embedding_model or settings.embedding_model,
            llm=llm_client.model_label(),
            compression=compression.label(),
        )
        package = ContextPackage(
            request_id=request_id,
            trace_id=trace_id,
            task=understanding.task,
            intent=understanding.intent,
            created_at=now,
            context=packaged.markdown,
            items=[persistence.item_from_decision(d) for d in included],
            excluded=[persistence.excluded_from_decision(resolved.viewer, d) for d in excluded]
            if resolved.explain
            else [],
            exclusion_summary=summary,
            tokens_used=packaged.tokens_used,
            token_budget=resolved.token_budget,
            candidates_count=len(candidates),
            timings=ContextTimings(),
            snapshot=None,
            config=config,
            warnings=warnings,
        )
        if settings.context_sufficiency:
            package.sufficiency = sufficiency.assess(
                understanding.task,
                rewritten.subtopics,
                included,
                sufficient_threshold=resolved.profile.sufficient_threshold if resolved.profile else None,
            )
            span.set_attribute("orbit.sufficiency", package.sufficiency.verdict)
        if resolved.profile is not None:
            package.profile = AppliedProfile(**resolved.profile.as_dict())
        if progressive:
            package.mode = "progressive"
            package.index = progressive_index(included)
        if packaged.prefix:
            package.cache_prefix_hash = packaged.prefix_hash
            package.cache_prefix_tokens = packaged.prefix_tokens
            package.cache_prefix_reused = await _prefix_reused(
                session, resolved.project_id, packaged.prefix_hash, now
            )
            if body.cache_hints:
                package.cache_hints = cache_hint_blocks(packaged.markdown, packaged.prefix)
        span.set_attribute("orbit.tokens_used", packaged.tokens_used)

    # --- persist ---------------------------------------------------------------------------------
    with tracer.start_as_current_span("context.persist"):
        params = _params(resolved, understanding)
        params.update(
            {
                "rewrite": rewritten.as_dict(),
                "config": config.model_dump(mode="json"),
                "warnings": warnings,
                "exclusion_summary": {code.value: n for code, n in summary.items()},
                "retrieval_sources": raw.sources_used,
                "profile": resolved.profile.as_dict() if resolved.profile else None,
                "sufficiency": package.sufficiency.model_dump(mode="json") if package.sufficiency else None,
                "cache": {
                    "prefix_hash": package.cache_prefix_hash,
                    "prefix_tokens": package.cache_prefix_tokens,
                    "reused": package.cache_prefix_reused,
                },
            }
        )
        row = persistence.request_row(
            request_id=request_id,
            project_id=resolved.project_id,
            trace_id=trace_id,
            agent_id=resolved.agent.id if resolved.agent else None,
            user_id=resolved.on_behalf_of.id if resolved.on_behalf_of else None,
            requested_by_type=PrincipalKind.agent if principal.is_agent else PrincipalKind.user,
            requested_by_id=principal.id,
            task=understanding.task,
            intent=understanding.intent,
            params=params,
            token_budget=resolved.token_budget,
        )
        row.created_at = now
        row.candidates_count = len(candidates)
        row.included_count = len(included)
        row.excluded_count = len(excluded)
        row.tokens_used = packaged.tokens_used
        row.cost_estimate = persistence.cost_estimate(packaged.tokens_used)
        row.context_text = packaged.markdown
        session.add(row)
        await session.flush()
        session.add_all([persistence.decision_row(request_id, d) for d in [*included, *excluded]])

        if resolved.save_name:
            snapshot = await snapshot_service.create_snapshot(
                session,
                project_id=resolved.project_id,
                name=resolved.save_name,
                request=row,
                package=package,
                actor=principal,
            )
            row.snapshot_id = snapshot.id
            package.snapshot = ContextSnapshotInfo(
                id=snapshot.id, name=snapshot.name, version=snapshot.version
            )
            await audit.record(
                session,
                resolved.project_id,
                principal,
                AuditAction.snapshot_create,
                target_type="snapshot",
                target_id=f"{snapshot.name}@v{snapshot.version}",
                summary=(
                    f"Snapshot « {snapshot.name} » v{snapshot.version} enregistré "
                    f"({len(package.items)} éléments)"
                ),
                details={
                    "snapshot_id": snapshot.id,
                    "request_id": request_id,
                    "parent_id": snapshot.parent_id,
                    "content_hash": snapshot.content_hash,
                },
            )

        restricted_titles = [
            d.candidate.title for d in excluded if d.verdict.redact and not d.candidate.is_forgotten
        ]
        task_preview = (
            understanding.task if len(understanding.task) <= 120 else understanding.task[:119] + "…"
        )
        await audit.record(
            session,
            resolved.project_id,
            principal,
            AuditAction.context_request,
            target_type="context_request",
            target_id=request_id,
            summary=(
                f"Contexte assemblé pour « {task_preview} » : {len(included)} retenus, "
                f"{len(excluded)} exclus, {packaged.tokens_used} tokens"
            ),
            details={
                "intent": understanding.intent,
                "agent_id": resolved.agent.id if resolved.agent else None,
                "on_behalf_of": resolved.on_behalf_of.id if resolved.on_behalf_of else None,
                "tokens_used": packaged.tokens_used,
                "token_budget": resolved.token_budget,
                "included": len(included),
                "excluded": len(excluded),
                "exclusion_summary": {code.value: n for code, n in summary.items()},
                "snapshot": package.snapshot.model_dump(mode="json") if package.snapshot else None,
                "base_snapshot": params["base_snapshot"],
                audit.RESTRICTED_KEY: {"excluded_titles": restricted_titles} if restricted_titles else {},
            },
        )
        await session.flush()

    total = timer.elapsed_ms()
    timings = {stage: timer.timings.get(stage, 0.0) for stage in STAGES}
    timings["total"] = total
    timings["rounds"] = timer.rounds  # type: ignore[assignment]
    row.latency_ms = round(total)
    row.timings = timings
    package.timings = ContextTimings(**timings)
    await session.commit()
    return package


async def _record_failure(
    session: AsyncSession,
    resolved: ResolvedRequest,
    request_id: uuid.UUID,
    trace_id: str,
    exc: Exception,
    elapsed: float,
) -> None:
    principal = resolved.access.principal
    try:
        await session.rollback()
        row = ContextRequest(
            id=request_id,
            project_id=resolved.project_id,
            trace_id=trace_id,
            agent_id=resolved.agent.id if resolved.agent else None,
            user_id=resolved.on_behalf_of.id if resolved.on_behalf_of else None,
            requested_by_type=PrincipalKind.agent if principal.is_agent else PrincipalKind.user,
            requested_by_id=principal.id,
            task=resolved.body.task.strip(),
            intent=resolved.body.intent or Intent.general,
            params={"request": resolved.body.model_dump(mode="json", exclude_none=True)},
            status=ContextRequestStatus.failed,
            error=f"{FAILURE_MESSAGE} ({type(exc).__name__})",
            latency_ms=round(elapsed),
            token_budget=resolved.token_budget,
        )
        session.add(row)
        await session.commit()
    except Exception:  # the original error matters more than the failure record
        logger.exception("Unable to record the failed context request %s", request_id)
        await session.rollback()


async def assemble_context(
    session: AsyncSession, access: ProjectAccess, request: ContextRequestIn
) -> ContextPackage:
    """Assemble, persist and return a governed context package (commits its own records)."""
    resolved = await resolve_request(session, access, request)
    timer = _Timer()
    request_id = uuid.uuid4()
    caller = "agent" if access.principal.is_agent else "user"
    with tracer.start_as_current_span("context.assemble") as span:
        span.set_attribute("orbit.project", access.project.slug)
        span.set_attribute("orbit.caller", caller)
        span.set_attribute("orbit.token_budget", resolved.token_budget)
        span.set_attribute("orbit.request_id", str(request_id))
        trace_id = current_trace_id()
        try:
            package = await _run(session, resolved, timer, request_id, trace_id)
        except ApiError:
            await session.rollback()
            raise
        except Exception as exc:
            elapsed = timer.elapsed_ms()
            logger.exception("Context assembly failed for project %s", access.project.slug)
            span.record_exception(exc)
            await _record_failure(session, resolved, request_id, trace_id, exc, elapsed)
            observe_context_request(
                latency_seconds=elapsed / 1000, tokens_used=0, status="failed", caller=caller
            )
            raise
    if package.cache_prefix_hash:
        observe_cache_prefix(reused=package.cache_prefix_reused, tokens=package.cache_prefix_tokens)
    observe_context_request(
        latency_seconds=package.timings.total / 1000,
        tokens_used=package.tokens_used,
        exclusions={code.value: n for code, n in package.exclusion_summary.items()},
        status="succeeded",
        caller=caller,
    )
    return package

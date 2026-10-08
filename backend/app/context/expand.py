"""Context on demand (docs/AI_CONTEXT_ENGINEERING.md §C2): governed lookups behind the MCP tools
``expand_source``, ``get_decision``, ``get_memory_item`` and ``search_more``.

Identity and governance are exactly those of the context engine: the request is resolved by
:func:`app.context.assembler.resolve_request` (principals of ``on_behalf_of``, effective clearance,
agent rights) and every item goes through :func:`app.governance.policy.evaluate` with the same
:class:`GovernanceContext` (ACL, classification, scope incl. private user memory, forgotten,
quarantine, expiry, freshness). Relevance is not a criterion for an explicit lookup. Denials caused by
ACL / classification / private scope answer exactly like an unknown id (non-leak) and every lookup is
audited (``context.expand``) with its outcome and reason code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import retrieval, spotlight
from app.context.understanding import embed_query
from app.db import utcnow
from app.deps import ProjectAccess
from app.enums import CandidateType, MemoryKind, ReasonCode
from app.governance.policy import Candidate, Verdict, evaluate
from app.models import Chunk, Document
from app.schemas.context import ContextRequestIn
from app.search.tokens import estimate_tokens, truncate_to_tokens
from app.services import audit
from app.services.audit import AuditAction

NOT_FOUND = "Élément introuvable ou non accessible avec vos droits"
#: Denials that must not reveal that the item exists.
SILENT_REASONS = frozenset(
    {ReasonCode.EXCLUDED_ACL, ReasonCode.EXCLUDED_CLASSIFICATION, ReasonCode.EXCLUDED_SCOPE}
)
DEFAULT_MAX_TOKENS = 2000
#: Which tool expands an index entry (progressive mode).
TOOL_FOR_SOURCE = "expand_source"
TOOL_FOR_DECISION = "get_decision"
TOOL_FOR_MEMORY = "get_memory_item"


class LookupDenied(Exception):
    """Unknown or refused item; ``message`` is safe to show to the caller."""

    def __init__(self, message: str, reason: ReasonCode | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


@dataclass(slots=True)
class Governed:
    access: ProjectAccess
    ctx: Any
    on_behalf_of: uuid.UUID | None
    denials: list[tuple[str, ReasonCode]] = field(default_factory=list)


def tool_for(candidate_type: CandidateType | str, memory_kind: MemoryKind | str | None) -> str | None:
    if str(candidate_type) == CandidateType.chunk.value:
        return TOOL_FOR_SOURCE
    if str(candidate_type) == CandidateType.memory.value:
        return TOOL_FOR_DECISION if str(memory_kind) == MemoryKind.decision.value else TOOL_FOR_MEMORY
    return None


async def governed(
    session: AsyncSession, access: ProjectAccess, on_behalf_of: uuid.UUID | None = None
) -> Governed:
    """Same identity resolution and governance context as ``POST /context``."""
    from app.context.assembler import _governance_context, resolve_request

    body = ContextRequestIn(task="lookup", on_behalf_of=on_behalf_of, explain=False, min_relevance=0)
    resolved = await resolve_request(session, access, body)
    return Governed(access=access, ctx=_governance_context(resolved, utcnow()), on_behalf_of=on_behalf_of)


def _check(gov: Governed, candidate: Candidate) -> Verdict | None:
    candidate.score = max(candidate.score, 1.0)  # explicit lookup: relevance is not a criterion
    return evaluate(candidate, gov.ctx)


def _refuse(verdict: Verdict) -> LookupDenied:
    code = verdict.reason_code
    if code in SILENT_REASONS:
        return LookupDenied(NOT_FOUND, code)
    return LookupDenied(f"Élément non servi : {code.label.lower()} ({verdict.reason_detail})", code)


async def _audit(
    session: AsyncSession,
    gov: Governed,
    tool: str,
    target_type: str,
    target_id: str,
    *,
    allowed: bool,
    reason: ReasonCode | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    await audit.record(
        session,
        gov.access.project_id,
        gov.access.principal,
        AuditAction.context_expand,
        target_type=target_type,
        target_id=target_id,
        summary=f"{tool} : {'servi' if allowed else 'refusé'} ({target_type} {target_id[:8]})",
        details={
            "tool": tool,
            "allowed": allowed,
            "reason_code": reason.value if reason else None,
            "on_behalf_of": gov.on_behalf_of,
            **(extra or {}),
        },
    )


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value).strip())
    except ValueError:
        return None


async def expand_source(
    session: AsyncSession, gov: Governed, source_id: str, *, max_tokens: int = DEFAULT_MAX_TOKENS
) -> dict[str, Any]:
    """Full served text of a chunk, or of a document's chunks (in order) up to ``max_tokens``."""
    ident = _uuid(source_id)
    project_id = gov.access.project_id
    chunk_ids: list[str] = []
    if ident is not None:
        chunk = await session.get(Chunk, ident)
        if chunk is not None and chunk.project_id == project_id:
            chunk_ids = [str(chunk.id)]
        else:
            document = await session.get(Document, ident)
            if document is not None and document.project_id == project_id:
                chunk_ids = [
                    str(cid)
                    for cid in (
                        await session.scalars(
                            select(Chunk.id)
                            .where(Chunk.document_id == document.id, Chunk.version == document.version)
                            .order_by(Chunk.ordinal)
                        )
                    ).all()
                ]
    rows = await retrieval.hydrate_chunks(session, project_id, chunk_ids)
    served: list[Candidate] = []
    refusal: Verdict | None = None
    for cid in chunk_ids:
        row = rows.get(cid)
        if row is None:
            continue
        candidate = retrieval.chunk_candidate(row)
        verdict = _check(gov, candidate)
        if verdict is None:
            served.append(candidate)
        elif refusal is None:
            refusal = verdict
    if not served:
        error = _refuse(refusal) if refusal is not None else LookupDenied(NOT_FOUND)
        await _audit(
            session, gov, TOOL_FOR_SOURCE, "source", str(source_id), allowed=False, reason=error.reason
        )
        raise error
    parts: list[str] = []
    used = 0
    truncated = False
    for candidate in served:
        text = candidate.text
        cost = estimate_tokens(text)
        if used + cost > max_tokens:
            text = truncate_to_tokens(text, max(max_tokens - used, 0))
            truncated = True
        if text:
            parts.append(text)
            used += estimate_tokens(text)
        if truncated:
            break
    first = served[0]
    await _audit(
        session,
        gov,
        TOOL_FOR_SOURCE,
        "source",
        str(source_id),
        allowed=True,
        extra={"chunks": len(served), "withheld": len(chunk_ids) - len(served), "tokens": used},
    )
    return {
        "id": str(source_id),
        "document_id": str(first.document_id) if first.document_id else None,
        "title": first.title,
        "source_kind": first.source_kind.value if first.source_kind else None,
        "uri": first.uri,
        "version": first.version,
        "classification": max(int(c.classification) for c in served),
        "text": spotlight.wrap("\n\n".join(parts)),
        "tokens": used,
        "truncated": truncated,
        "chunks": len(served),
        "withheld_chunks": len(chunk_ids) - len(served),
    }


async def get_memory(
    session: AsyncSession, gov: Governed, item_id: str, *, decision_only: bool = False
) -> dict[str, Any]:
    """Current version of a memory item (or of its lineage) when governance allows it."""
    tool = TOOL_FOR_DECISION if decision_only else TOOL_FOR_MEMORY
    ident = _uuid(item_id)
    requested, _ = (
        await retrieval.hydrate_memory(session, gov.access.project_id, [str(ident)], [str(ident)])
        if ident is not None
        else ({}, {})
    )
    row = requested.get(str(ident)) if ident is not None else None
    error: LookupDenied | None = None
    candidate: Candidate | None = None
    if row is None:
        error = LookupDenied(NOT_FOUND)
    else:
        candidate = retrieval.memory_candidate(row)
        verdict = _check(gov, candidate)
        if verdict is not None:
            error = _refuse(verdict)
        elif decision_only and candidate.memory_kind != MemoryKind.decision:
            error = LookupDenied("Cet élément n'est pas une décision : utilisez get_memory_item")
    if error is not None or candidate is None:
        error = error or LookupDenied(NOT_FOUND)
        await _audit(session, gov, tool, "memory_item", str(item_id), allowed=False, reason=error.reason)
        raise error
    item = row.item
    await _audit(session, gov, tool, "memory_item", str(item.id), allowed=True)
    return {
        "id": str(item.id),
        "lineage_id": str(item.lineage_id),
        "version": item.version,
        "kind": item.kind.value,
        "scope": item.scope.value,
        "status": item.status.value,
        "title": candidate.title,
        "content": spotlight.wrap(candidate.text),
        "classification": int(item.classification),
        "confidence": item.confidence,
        "valid_from": item.valid_from.isoformat() if getattr(item, "valid_from", None) else None,
        "updated_at": item.updated_at.isoformat() if getattr(item, "updated_at", None) else None,
        "requested_id": str(item_id),
    }


async def search_more(
    session: AsyncSession,
    gov: Governed,
    query: str,
    *,
    limit: int = 8,
    exclude_ids: set[str] | None = None,
    teaser_tokens: int = 60,
) -> list[dict[str, Any]]:
    """Additional governed retrieval (chunks + memory) for a follow-up question."""
    vector, _model = await embed_query(query)
    raw = await retrieval.retrieve(
        session,
        task=query,
        query_vector=vector,
        project_id=gov.access.project_id,
        include_chunks=True,
        include_memory=True,
        include_org_memory=True,
        session_id=None,
    )
    candidates = sorted(retrieval.fuse(raw, session_id=None), key=lambda c: c.score, reverse=True)
    excluded = exclude_ids or set()
    results: list[dict[str, Any]] = []
    withheld = 0
    for candidate in candidates:
        ref = str(candidate.memory_item_id or candidate.id)
        if candidate.id in excluded or ref in excluded:
            continue
        score = candidate.score
        if evaluate(_with_score(candidate), gov.ctx) is not None:
            withheld += 1
            continue
        results.append(
            {
                "id": ref,
                "type": candidate.candidate_type.value,
                "title": candidate.title,
                "memory_kind": candidate.memory_kind.value if candidate.memory_kind else None,
                "source_kind": candidate.source_kind.value if candidate.source_kind else None,
                "document_id": str(candidate.document_id) if candidate.document_id else None,
                "score": round(score, 4),
                "teaser": spotlight.wrap(truncate_to_tokens(candidate.text, teaser_tokens)),
                "expand_with": tool_for(candidate.candidate_type, candidate.memory_kind),
            }
        )
        if len(results) >= limit:
            break
    await _audit(
        session,
        gov,
        "search_more",
        "context_search",
        query[:80],
        allowed=True,
        extra={"results": len(results), "withheld": withheld},
    )
    return results


def _with_score(candidate: Candidate) -> Candidate:
    candidate.score = max(candidate.score, 1.0)
    return candidate

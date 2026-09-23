"""Context assembler (interface — implemented by the context teammate). ARCHITECTURE §9.

``assemble_context`` runs the timed stages understand → retrieve → fuse → rerank → govern → select →
compress → package → persist and returns the :class:`ContextPackage` of docs/API.md:

* retrieval pre-filters on the project only; governance (``app.governance.policy``) then explains
  every exclusion with a ``ReasonCode``;
* principals: ``app.governance.acl.effective_principals(access, on_behalf_of_user, role)``;
  clearance: ``effective_clearance(user, agent, request.max_classification)``;
* the served text always uses ``text_redacted`` (``pii_redacted: true``);
* ``explain`` defaults to ``True`` for humans and ``False`` for agents (agents only get
  ``exclusion_summary`` counters); ACL/classification exclusions are redacted for callers without
  access;
* persists ``ContextRequest`` + ``ContextDecision`` rows (+ snapshot when ``save_snapshot``),
  records an audit entry, OTel spans (``app.observability.tracing``) and Prometheus metrics
  (``app.observability.metrics.observe_context_request``); ``trace_id`` = current OTel trace id;
* ``warnings`` include ``app.enums.classification_warning(level)`` for C2/C3 content.

Budget: ``token_budget`` default ``settings.default_token_budget`` (500 ≤ budget ≤ 32000).
Performance target: p95 < 1500 ms on the demo dataset (CPU).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import ProjectAccess
from app.schemas.context import ContextPackage, ContextRequestIn


async def assemble_context(
    session: AsyncSession, access: ProjectAccess, request: ContextRequestIn
) -> ContextPackage:
    """Assemble, persist and return a governed context package (commits its own records)."""
    raise NotImplementedError("Assemblage de contexte non implémenté")

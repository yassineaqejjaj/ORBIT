# ruff: noqa: E501  (printable HTML template lines)
"""AI Act traceability report (docs/AI_CONTEXT_ENGINEERING.md §A4).

For each context request in scope: *which context* (task, intent, tokens, hash of the served text),
*which sources* (included items with citation, type, classification, version), *which decision*
(governance verdicts: included / excluded with reason codes) and *which model* (embedding model,
reranker, compression / answer LLM and the guardrail in force). Scope: one request, a period, or one
memory decision (every request that served it). Exported as JSON or as a printable HTML page.

Governance applies to the report itself: owners only, and items classified above the caller's
clearance are listed without title or excerpt (non-leak principle).
"""

from __future__ import annotations

import hashlib
import html
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.enums import CLASSIFICATION_CODES, REASON_CODE_LABELS, ReasonCode
from app.models import ContextDecision, ContextRequest, MemoryItem
from app.models.features_ask import AskMessage
from app.services.metrics import actor_labels

REPORT_LIMIT = 500
RESTRICTED_TITLE = "[élément restreint — habilitation insuffisante]"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def security_settings() -> dict[str, Any]:
    return {
        "injection_detection": settings.injection_detection,
        "injection_threshold": settings.injection_threshold,
        "injection_classifier": settings.injection_classifier,
        "spotlighting": settings.spotlighting,
        "trust_ranking_penalty": settings.trust_ranking_penalty,
        "poisoning_alert_threshold": settings.poisoning_alert_threshold,
        "poisoning_window_hours": settings.poisoning_window_hours,
        "llm_max_classification": settings.llm_max_classification,
        "llm_local": settings.llm_local,
        "llm_redact_pii": settings.llm_redact_pii,
    }


def _decision_view(d: ContextDecision, clearance: int) -> dict[str, Any]:
    restricted = int(d.classification) > clearance
    code = ReasonCode(d.reason_code)
    return {
        "citation": d.citation,
        "candidate_type": str(d.candidate_type),
        "candidate_id": d.candidate_id,
        "document_id": str(d.document_id) if d.document_id else None,
        "memory_item_id": str(d.memory_item_id) if d.memory_item_id else None,
        "title": RESTRICTED_TITLE if restricted else d.title,
        "source_kind": d.source_kind,
        "classification": CLASSIFICATION_CODES.get(int(d.classification), str(d.classification)),
        "included": bool(d.included),
        "reason_code": code.value,
        "reason_label": REASON_CODE_LABELS[code],
        "reason_detail": "" if restricted else d.reason_detail,
        "tokens": int(d.tokens or 0),
        "rank": d.rank,
    }


async def build_report(
    session: AsyncSession,
    project: Any,
    *,
    clearance: int,
    request_id: uuid.UUID | None = None,
    memory_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    stmt = select(ContextRequest).where(ContextRequest.project_id == project.id)
    scope: dict[str, Any] = {}
    if request_id is not None:
        stmt = stmt.where(ContextRequest.id == request_id)
        scope["request_id"] = str(request_id)
    if memory_id is not None:
        item = await session.get(MemoryItem, memory_id)
        lineage = item.lineage_id if item is not None and item.project_id == project.id else None
        ids = select(MemoryItem.id).where(MemoryItem.lineage_id == lineage)
        served = select(ContextDecision.request_id).where(ContextDecision.memory_item_id.in_(ids))
        stmt = stmt.where(ContextRequest.id.in_(served))
        scope["memory_id"] = str(memory_id)
        scope["decision_title"] = item.title if item is not None and lineage is not None else None
    if since is not None:
        stmt = stmt.where(ContextRequest.created_at >= since)
        scope["from"] = since.isoformat()
    if until is not None:
        stmt = stmt.where(ContextRequest.created_at <= until)
        scope["to"] = until.isoformat()
    requests = list(
        await session.scalars(stmt.order_by(ContextRequest.created_at.desc()).limit(REPORT_LIMIT))
    )
    ids = [r.id for r in requests]

    decisions: dict[uuid.UUID, list[ContextDecision]] = defaultdict(list)
    answers: dict[uuid.UUID, AskMessage] = {}
    if ids:
        for d in await session.scalars(
            select(ContextDecision)
            .where(ContextDecision.request_id.in_(ids))
            .order_by(
                ContextDecision.included.desc(), ContextDecision.rank.asc().nulls_last(), ContextDecision.id
            )
        ):
            decisions[d.request_id].append(d)
        for message in await session.scalars(select(AskMessage).where(AskMessage.request_id.in_(ids))):
            if message.request_id is not None:
                answers[message.request_id] = message
    labels = await actor_labels(session, [(str(r.requested_by_type), r.requested_by_id) for r in requests])
    labels.update(await actor_labels(session, [("user", r.user_id) for r in requests if r.user_id]))

    rows: list[dict[str, Any]] = []
    reasons_total: Counter[str] = Counter()
    for r in requests:
        views = [_decision_view(d, clearance) for d in decisions.get(r.id, [])]
        excluded = Counter(v["reason_code"] for v in views if not v["included"])
        reasons_total.update(excluded)
        config = dict((r.params or {}).get("config") or {})
        answer = answers.get(r.id)
        rows.append(
            {
                "request_id": str(r.id),
                "trace_id": r.trace_id,
                "created_at": _iso(r.created_at),
                "requested_by": {
                    "type": str(r.requested_by_type),
                    "id": str(r.requested_by_id) if r.requested_by_id else None,
                    "label": labels.get(r.requested_by_id, "") if r.requested_by_id else "",
                },
                "on_behalf_of": labels.get(r.user_id) if r.user_id else None,
                "context": {
                    "task": r.task,
                    "intent": str(r.intent),
                    "status": str(r.status),
                    "tokens_used": r.tokens_used,
                    "token_budget": r.token_budget,
                    "latency_ms": r.latency_ms,
                    "sha256": hashlib.sha256((r.context_text or "").encode()).hexdigest(),
                },
                "sources": [v for v in views if v["included"]],
                "decision": {
                    "candidates": r.candidates_count,
                    "included": r.included_count,
                    "excluded": r.excluded_count,
                    "excluded_by_reason": dict(excluded),
                    "excluded_items": [v for v in views if not v["included"]],
                },
                "model": {
                    "embedding_model": config.get("embedding_model"),
                    "reranker": config.get("reranker"),
                    "llm": config.get("llm"),
                    "answer_mode": answer.mode if answer is not None else None,
                    "answer_llm_tokens": answer.llm_tokens if answer is not None else None,
                },
            }
        )
    return {
        "report": "ai_act_traceability",
        "version": 1,
        "generated_at": utcnow().isoformat(),
        "project": {"id": str(project.id), "slug": project.slug, "name": project.name},
        "scope": scope,
        "clearance": CLASSIFICATION_CODES.get(clearance, str(clearance)),
        "safeguards": security_settings(),
        "totals": {
            "requests": len(rows),
            "truncated": len(rows) >= REPORT_LIMIT,
            "excluded_by_reason": dict(reasons_total),
        },
        "requests": rows,
    }


# --- Printable HTML -------------------------------------------------------------------------------------

_CSS = """
body{font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:#111;background:#fff;margin:24px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:24px 0 6px;border-top:1px solid #ccc;padding-top:12px}
.meta{color:#555}table{border-collapse:collapse;width:100%;margin:6px 0}
th,td{border:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top}th{background:#f3f3f3}
code{font-size:12px}@media print{body{margin:0}h2{break-before:auto}section{break-inside:avoid}}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def render_html(report: dict[str, Any]) -> str:
    project = report["project"]
    out = [
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>",
        f"<title>Rapport de traçabilité IA — {_e(project['name'])}</title><style>{_CSS}</style></head><body>",
        f"<h1>Rapport de traçabilité IA (AI Act) — {_e(project['name'])}</h1>",
        f"<p class='meta'>Généré le {_e(report['generated_at'])} · habilitation {_e(report['clearance'])} · "
        f"{report['totals']['requests']} requête(s) · périmètre : {_e(report['scope'] or 'toutes les requêtes')}</p>",
        "<h2>Garde-fous en vigueur</h2><table><tbody>",
        *(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in report["safeguards"].items()),
        "</tbody></table>",
    ]
    for row in report["requests"]:
        ctx, model, decision = row["context"], row["model"], row["decision"]
        out += [
            f"<section><h2>Requête {_e(row['request_id'])}</h2>",
            f"<p class='meta'>{_e(row['created_at'])} · {_e(row['requested_by']['type'])} "
            f"{_e(row['requested_by']['label'])}"
            + (f" pour {_e(row['on_behalf_of'])}" if row["on_behalf_of"] else "")
            + f" · trace <code>{_e(row['trace_id'])}</code></p>",
            f"<p><strong>Contexte</strong> : {_e(ctx['task'])} — intention {_e(ctx['intent'])}, "
            f"{_e(ctx['tokens_used'])}/{_e(ctx['token_budget'])} tokens, empreinte <code>{_e(ctx['sha256'][:16])}</code></p>",
            f"<p><strong>Modèle</strong> : embeddings {_e(model['embedding_model'])}, reranker {_e(model['reranker'])}, "
            f"LLM {_e(model['llm'] or 'aucun')}"
            + (f", réponse {_e(model['answer_mode'])}" if model["answer_mode"] else "")
            + "</p>",
            "<table><thead><tr><th>Cit.</th><th>Source</th><th>Type</th><th>Classif.</th><th>Décision</th></tr></thead><tbody>",
        ]
        for item in row["sources"] + decision["excluded_items"]:
            out.append(
                f"<tr><td>{_e(item['citation'] or '')}</td><td>{_e(item['title'])}</td>"
                f"<td>{_e(item['source_kind'] or item['candidate_type'])}</td><td>{_e(item['classification'])}</td>"
                f"<td>{_e(item['reason_label'])}{(' — ' + _e(item['reason_detail'])) if item['reason_detail'] else ''}</td></tr>"
            )
        out.append("</tbody></table></section>")
    out.append("</body></html>")
    return "\n".join(out)

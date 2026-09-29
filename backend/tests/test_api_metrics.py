"""Overview, metrics and trace export: pure helpers + aggregation on synthetic rows."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    ActorType,
    AlertLevel,
    CandidateType,
    ChunkStatus,
    ContextRequestStatus,
    DocumentStatus,
    Intent,
    JobKind,
    JobStatus,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    PrincipalKind,
    ReasonCode,
    RelationNodeType,
    RelationType,
    SourceKind,
)
from app.models import (
    AuditLog,
    Chunk,
    ContextDecision,
    ContextFeedback,
    ContextRequest,
    ContextSnapshot,
    Document,
    IngestionJob,
    MemoryItem,
    Relation,
    Source,
)
from app.schemas import MetricsPoint
from app.services.metrics import (
    REDACTED_CONTEXT,
    AlertSignals,
    build_alerts,
    inclusion_key,
    order_stages,
    trace_record,
    window_days,
    window_start,
    zero_fill_series,
)
from tests.conftest import UserInfo

# --- Pure helpers ---------------------------------------------------------------------------------------


def test_window_start_is_utc_midnight() -> None:
    now = datetime(2026, 9, 23, 15, 42, tzinfo=UTC)
    assert window_start(14, now=now) == datetime(2026, 9, 10, tzinfo=UTC)
    assert window_start(1, now=now) == datetime(2026, 9, 23, tzinfo=UTC)
    days = window_days(3, now=now)
    assert days == [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]


def test_zero_fill_series_keeps_order_and_fills_gaps() -> None:
    days = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
    point = MetricsPoint(date=days[1], requests=4, p50_latency_ms=120.0, p95_latency_ms=300.0, tokens=900)
    series = zero_fill_series({days[1]: point}, days)
    assert [p.date for p in series] == days
    assert [p.requests for p in series] == [0, 4, 0]
    assert series[0].tokens == 0 and series[0].cost_estimate == 0


def test_order_stages_follows_pipeline_order() -> None:
    ordered = order_stages(
        {"total": 900.0, "select": 3.0, "understand": 10.0, "custom": 1.0, "retrieve": 50.0}
    )
    assert list(ordered) == ["understand", "retrieve", "select", "custom", "total"]


def test_inclusion_key() -> None:
    assert inclusion_key(CandidateType.chunk, None) == "chunk"
    assert inclusion_key(CandidateType.memory, MemoryKind.decision) == "memory:decision"
    assert inclusion_key("memory", None) == "memory"
    assert inclusion_key(CandidateType.session, None) == "session"


def test_build_alerts_messages_and_severity_order() -> None:
    alerts = build_alerts(
        AlertSignals(
            sources=3,
            failed_jobs=2,
            open_conflicts=1,
            pending_proposals=4,
            c2_documents=5,
            c3_documents=1,
            queued_jobs=3,
            running_jobs=1,
        )
    )
    levels = [a.level for a in alerts]
    assert levels == sorted(levels, key=[AlertLevel.critical, AlertLevel.warning, AlertLevel.info].index)
    messages = [a.message for a in alerts]
    assert messages[0].startswith("2 jobs d'ingestion en échec")
    assert "1 contradiction non résolue dans la mémoire du projet — arbitrage recommandé." in messages
    assert any(m.startswith("1 document classifié C3 (Secret)") for m in messages)
    assert any(m.startswith("5 documents classifiés C2 (Confidentiel)") for m in messages)
    assert "4 propositions de mémoire en attente de validation." in messages
    assert any(
        m.startswith("Ingestion en cours : 3 jobs en file d'attente, 1 en traitement") for m in messages
    )


def test_build_alerts_quiet_project_and_backlog_threshold() -> None:
    assert build_alerts(AlertSignals(sources=2)) == []
    empty = build_alerts(AlertSignals())
    assert len(empty) == 1 and empty[0].message.startswith("Aucune source configurée")
    backlog = build_alerts(AlertSignals(sources=1, pending_proposals=12))
    assert backlog[0].level == AlertLevel.warning


def test_trace_record_redacts_content_above_clearance() -> None:
    request = ContextRequest(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="abc",
        requested_by_type=PrincipalKind.agent,
        task="Préparer la note budgétaire",
        intent=Intent.analysis,
        params={},
        status=ContextRequestStatus.succeeded,
        latency_ms=420,
        timings={"retrieve": 40.0, "total": 420.0},
        candidates_count=2,
        included_count=1,
        excluded_count=1,
        tokens_used=300,
        token_budget=4000,
        cost_estimate=Decimal("0.0006"),
        context_text="## Décisions en vigueur\nMontant du contrat : secret",
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    secret = ContextDecision(
        id=uuid.uuid4(),
        request_id=request.id,
        candidate_type=CandidateType.chunk,
        candidate_id=str(uuid.uuid4()),
        document_id=uuid.uuid4(),
        title="Budget et négociation contrat Atlas",
        excerpt="Montant plafond 480 k€",
        source_kind="document",
        classification=3,
        scores={"final": 0.8},
        included=True,
        reason_code=ReasonCode.INCLUDED_RELEVANT,
        reason_detail="score 0,80",
        tokens=120,
        rank=1,
        citation="S1",
    )
    public = ContextDecision(
        id=uuid.uuid4(),
        request_id=request.id,
        candidate_type=CandidateType.chunk,
        candidate_id=str(uuid.uuid4()),
        title="Benchmark flex office",
        excerpt="…",
        classification=0,
        scores={"final": 0.1},
        included=False,
        reason_code=ReasonCode.EXCLUDED_STALE,
        reason_detail="400 j > 180 j",
        tokens=0,
    )
    record = trace_record(request, [secret, public], [], clearance=2)
    assert record["schema"] == "orbit.trace.v1"
    assert record["context"] == REDACTED_CONTEXT
    hidden, visible = record["decisions"]
    assert hidden["redacted"] is True and hidden["title"] is None and hidden["excerpt"] is None
    assert hidden["document_id"] is None and hidden["reason_code"] == "INCLUDED_RELEVANT"
    assert visible["redacted"] is False and visible["title"] == "Benchmark flex office"
    assert record["request"]["cost_estimate"] == pytest.approx(0.0006)
    full = trace_record(request, [secret, public], [], clearance=3)
    assert full["context"].startswith("## Décisions en vigueur")
    assert full["decisions"][0]["excerpt"] == "Montant plafond 480 k€"


# --- Integration on synthetic rows --------------------------------------------------------------------


@dataclass
class Dataset:
    slug: str
    project_id: uuid.UUID
    agent_id: uuid.UUID
    doc_public: uuid.UUID
    doc_secret: uuid.UUID
    viewer: UserInfo


async def _seed_rows(
    session: AsyncSession, project_id: uuid.UUID, agent_id: uuid.UUID, viewer_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    now = datetime.now(UTC)
    notes = Source(project_id=project_id, name="Comptes rendus", kind=SourceKind.note)
    crm = Source(project_id=project_id, name="CRM", kind=SourceKind.crm, default_classification=2)
    session.add_all([notes, crm])
    await session.flush()

    doc_public = Document(project_id=project_id, source_id=notes.id, title="CR kick-off", classification=1)
    doc_secret = Document(
        project_id=project_id,
        source_id=notes.id,
        title="Budget et négociation contrat Atlas",
        classification=3,
        acl_principals=["role:owner"],
    )
    doc_crm = Document(
        project_id=project_id, source_id=crm.id, title="Fiche contact", classification=2, pii_count=2
    )
    doc_forgotten = Document(
        project_id=project_id,
        source_id=notes.id,
        title="Document oublié",
        status=DocumentStatus.forgotten,
        classification=1,
    )
    for doc in (doc_public, doc_secret, doc_crm):
        doc.status = DocumentStatus.indexed
    session.add_all([doc_public, doc_secret, doc_crm, doc_forgotten])
    await session.flush()

    session.add_all(
        [
            Chunk(
                project_id=project_id,
                document_id=doc_public.id,
                version=1,
                ordinal=0,
                text="Décision : PWA",
                text_redacted="Décision : PWA",
                classification=1,
            ),
            Chunk(
                project_id=project_id,
                document_id=doc_public.id,
                version=1,
                ordinal=1,
                text="ancien",
                text_redacted="ancien",
                classification=1,
                status=ChunkStatus.superseded,
            ),
        ]
    )

    # Jobs: one broken, one failed then retried successfully, one queued, one recent success.
    session.add_all(
        [
            IngestionJob(
                project_id=project_id,
                document_id=doc_crm.id,
                kind=JobKind.ingest,
                status=JobStatus.failed,
                created_at=now - timedelta(hours=5),
            ),
            IngestionJob(
                project_id=project_id,
                document_id=doc_public.id,
                kind=JobKind.ingest,
                status=JobStatus.failed,
                created_at=now - timedelta(hours=4),
            ),
            IngestionJob(
                project_id=project_id,
                document_id=doc_public.id,
                kind=JobKind.ingest,
                status=JobStatus.succeeded,
                created_at=now - timedelta(hours=3),
                started_at=now - timedelta(hours=3),
                finished_at=now - timedelta(hours=3) + timedelta(milliseconds=1500),
            ),
            IngestionJob(project_id=project_id, document_id=doc_secret.id, kind=JobKind.ingest),
        ]
    )

    def memory(**kwargs: object) -> MemoryItem:
        base: dict[str, object] = {
            "project_id": project_id,
            "scope": MemoryScope.project,
            "kind": MemoryKind.decision,
            "status": MemoryStatus.validated,
            "content": "…",
            "classification": 1,
        }
        base.update(kwargs)
        return MemoryItem(**base)

    decision_pwa = memory(title="Décision : PWA")
    decision_secret = memory(title="Décision : plafond budgétaire", classification=3)
    proposal = memory(title="Besoin : réserver depuis Teams", kind=MemoryKind.requirement, status="proposed")
    obsolete = memory(title="Fait : 720 postes", kind=MemoryKind.fact, status=MemoryStatus.obsolete)
    fact_650 = memory(title="Fait : 650 postes", kind=MemoryKind.fact, status=MemoryStatus.proposed)
    fact_800 = memory(title="Fait : 800 postes", kind=MemoryKind.fact, status=MemoryStatus.proposed)
    session.add_all([decision_pwa, decision_secret, proposal, obsolete, fact_650, fact_800])
    await session.flush()
    session.add_all(
        [
            # open: both endpoints active
            Relation(
                project_id=project_id,
                src_type=RelationNodeType.memory,
                src_id=fact_650.id,
                rel_type=RelationType.contradicts,
                dst_type=RelationNodeType.memory,
                dst_id=fact_800.id,
            ),
            # resolved: one endpoint obsolete
            Relation(
                project_id=project_id,
                src_type=RelationNodeType.memory,
                src_id=fact_650.id,
                rel_type=RelationType.contradicts,
                dst_type=RelationNodeType.memory,
                dst_id=obsolete.id,
            ),
        ]
    )

    def request(created_at: datetime, latency: int, tokens: int) -> ContextRequest:
        return ContextRequest(
            project_id=project_id,
            trace_id=uuid.uuid4().hex,
            agent_id=agent_id,
            user_id=viewer_id,
            requested_by_type=PrincipalKind.agent,
            task="Rédiger la spécification",
            intent=Intent.specification,
            latency_ms=latency,
            timings={"understand": 10, "retrieve": latency / 2, "total": latency, "note": "x"},
            candidates_count=10,
            included_count=3,
            excluded_count=2,
            tokens_used=tokens,
            token_budget=4000,
            cost_estimate=Decimal(tokens) / 1000 * Decimal("0.002"),
            context_text="## Sources",
            created_at=created_at,
        )

    today_a = request(now - timedelta(minutes=5), 100, 1000)
    today_b = request(now - timedelta(minutes=1), 300, 2000)
    yesterday = request(now - timedelta(days=1), 500, 1500)
    old = request(now - timedelta(days=20), 900, 800)
    session.add_all([today_a, today_b, yesterday, old])
    await session.flush()

    def decision(req: ContextRequest, **kwargs: object) -> ContextDecision:
        base: dict[str, object] = {
            "request_id": req.id,
            "candidate_type": CandidateType.chunk,
            "candidate_id": str(uuid.uuid4()),
            "title": "t",
            "included": True,
            "reason_code": ReasonCode.INCLUDED_RELEVANT,
            "classification": 1,
        }
        base.update(kwargs)
        return ContextDecision(**base)

    session.add_all(
        [
            decision(today_a, document_id=doc_public.id),
            decision(today_b, document_id=doc_public.id),
            decision(yesterday, document_id=doc_public.id),
            decision(today_a, document_id=doc_secret.id, classification=3),
            decision(today_b, document_id=doc_secret.id, classification=3),
            decision(
                today_a,
                candidate_type=CandidateType.memory,
                candidate_id=str(decision_pwa.id),
                memory_item_id=decision_pwa.id,
            ),
            decision(today_a, included=False, reason_code=ReasonCode.EXCLUDED_STALE),
            decision(today_b, included=False, reason_code=ReasonCode.EXCLUDED_ACL, classification=3),
            decision(yesterday, included=False, reason_code=ReasonCode.EXCLUDED_ACL, classification=3),
            decision(old, included=False, reason_code=ReasonCode.EXCLUDED_BUDGET),
        ]
    )
    session.add_all(
        [
            ContextFeedback(
                request_id=today_a.id, actor_type=PrincipalKind.agent, actor_id=agent_id, rating=4
            ),
            ContextFeedback(
                request_id=yesterday.id,
                actor_type=PrincipalKind.user,
                actor_id=viewer_id,
                rating=5,
                item_flags=[{"citation": "S1", "flag": "outdated"}],
            ),
            ContextSnapshot(
                project_id=project_id,
                name="spec-atlas",
                version=1,
                request_id=today_a.id,
                task="Rédiger la spécification",
                content="## Sources",
                items=[],
                content_hash="h",
                created_by_type=ActorType.agent,
                created_by_id=agent_id,
            ),
            AuditLog(
                project_id=project_id,
                actor_type=ActorType.system,
                actor_label="Système ORBIT",
                action="context.request",
                summary="Requête de contexte",
                details={"included": 3, "restricted": {"excluded_titles": ["Budget"]}},
            ),
            AuditLog(
                project_id=project_id,
                actor_type=ActorType.system,
                actor_label="Système ORBIT",
                action="document.indexed",
                target_type="document",
                target_id=str(doc_secret.id),
                summary="« Budget et négociation contrat Atlas » indexé (v1, 2 fragment(s), C3)",
                details={"version": 1},
            ),
        ]
    )
    await session.commit()
    return doc_public.id, doc_secret.id


@pytest.fixture
async def dataset(
    admin_client: httpx.AsyncClient,
    project: dict,  # type: ignore[type-arg]
    make_user,  # type: ignore[no-untyped-def]
    db_session: AsyncSession,
) -> Dataset:
    slug = str(project["slug"])
    viewer: UserInfo = await make_user(clearance=1, name="Sarah Nguyen")
    added = await admin_client.post(
        f"/api/v1/projects/{slug}/members", json={"email": viewer.email, "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    created = await admin_client.post(
        f"/api/v1/projects/{slug}/agents", json={"name": "Agent Produit", "kind": "product", "clearance": 2}
    )
    assert created.status_code == 201, created.text
    agent_id = uuid.UUID(created.json()["agent"]["id"])
    project_id = uuid.UUID(str(project["id"]))
    doc_public, doc_secret = await _seed_rows(db_session, project_id, agent_id, viewer.id)
    return Dataset(slug, project_id, agent_id, doc_public, doc_secret, viewer)


async def test_overview_aggregates_and_alerts(admin_client: httpx.AsyncClient, dataset: Dataset) -> None:
    response = await admin_client.get(f"/api/v1/projects/{dataset.slug}/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project"]["slug"] == dataset.slug
    stats = body["stats"]
    assert stats["sources"] == 2
    assert stats["documents"] == 3
    assert stats["documents_indexed"] == 3
    assert stats["chunks"] == 1
    assert stats["pii_documents"] == 1
    assert stats["restricted_documents"] == 2
    assert stats["validated_decisions"] == 2
    assert stats["memory_items"] == 6
    assert stats["snapshots"] == 1
    assert stats["context_requests_7d"] == 3

    assert body["ingestion"] == {"queued": 1, "running": 0, "failed": 1, "succeeded_24h": 1}
    assert set(body["memory_by_status"]) == {s.value for s in MemoryStatus}
    assert body["memory_by_status"]["validated"] == 2
    assert body["memory_by_status"]["proposed"] == 3
    assert body["memory_by_scope"]["project"] == 6
    assert body["sources_by_kind"]["note"] == 1 and body["sources_by_kind"]["crm"] == 1
    assert set(body["sources_by_kind"]) == {k.value for k in SourceKind}

    context = body["context"]
    assert context["requests_7d"] == 3
    assert context["p95_latency_ms"] == pytest.approx(480.0)  # percentile_cont over 100/300/500
    assert context["avg_tokens"] == pytest.approx(1500.0)
    assert context["avg_included"] == pytest.approx(3.0)
    assert context["exclusion_rate"] == pytest.approx(0.4)

    titles = [d["title"] for d in body["latest_decisions"]]
    assert set(titles) == {"Décision : PWA", "Décision : plafond budgétaire"}
    assert all(d["created_by_label"] == "Système ORBIT" for d in body["latest_decisions"])

    alerts = body["alerts"]
    assert alerts[0]["level"] == "critical"
    assert alerts[0]["message"].startswith("1 job d'ingestion en échec")
    messages = [a["message"] for a in alerts]
    assert any(m.startswith("1 contradiction non résolue") for m in messages)
    assert any(m.startswith("1 document classifié C3 (Secret)") for m in messages)
    assert any(m.startswith("3 propositions de mémoire en attente") for m in messages)

    restricted = [e for e in body["recent_activity"] if e["action"] == "context.request"]
    assert restricted and "restricted" in restricted[0]["details"]
    indexed = next(e for e in body["recent_activity"] if e["action"] == "document.indexed")
    assert "Budget" in indexed["summary"]  # owners/admins see the full audit trail


async def test_overview_hides_restricted_content_from_viewer(
    client_for,  # type: ignore[no-untyped-def]
    dataset: Dataset,
) -> None:
    viewer = await client_for(dataset.viewer)
    response = await viewer.get(f"/api/v1/projects/{dataset.slug}/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [d["title"] for d in body["latest_decisions"]] == ["Décision : PWA"]
    event = next(e for e in body["recent_activity"] if e["action"] == "context.request")
    assert "restricted" not in event["details"] and event["details"]["included"] == 3
    # Audit summaries quoting a content the viewer cannot read are redacted (no title, no id).
    indexed = next(e for e in body["recent_activity"] if e["action"] == "document.indexed")
    assert indexed["target_id"] is None and indexed["details"] == {}
    assert "caviardé" in indexed["summary"] and "Budget" not in json.dumps(body)
    # Counters stay global (no titles involved).
    assert body["stats"]["restricted_documents"] == 2


async def test_metrics_series_totals_and_breakdowns(
    admin_client: httpx.AsyncClient, dataset: Dataset
) -> None:
    response = await admin_client.get(f"/api/v1/projects/{dataset.slug}/metrics", params={"days": 14})
    assert response.status_code == 200, response.text
    body = response.json()

    totals = body["totals"]
    assert totals["requests"] == 3
    assert totals["avg_latency_ms"] == pytest.approx(300.0)
    assert totals["p50_latency_ms"] == pytest.approx(300.0)
    assert totals["p95_latency_ms"] == pytest.approx(480.0)
    assert totals["tokens"] == 4500
    assert totals["cost_estimate"] == pytest.approx(0.009)
    assert totals["avg_rating"] == pytest.approx(4.5)
    assert totals["feedback_count"] == 2

    series = body["series"]
    assert len(series) == 14
    assert series[-1]["date"] == datetime.now(UTC).date().isoformat()
    assert sum(p["requests"] for p in series) == 3
    assert all(p["requests"] == 0 and p["tokens"] == 0 for p in series[:-2])

    assert body["exclusions_by_reason"] == {"EXCLUDED_ACL": 2, "EXCLUDED_STALE": 1}
    assert body["inclusions_by_type"] == {"chunk": 5, "memory:decision": 1}
    assert [(s["title"], s["count"]) for s in body["top_sources"]] == [
        ("CR kick-off", 3),
        ("Budget et négociation contrat Atlas", 2),
    ]
    assert body["top_sources"][0]["source_kind"] == "note"
    assert body["by_agent"] == [
        {
            "agent_id": str(dataset.agent_id),
            "name": "Agent Produit",
            "kind": "product",
            "requests": 3,
            "avg_latency_ms": 300.0,
            "avg_tokens": 1500.0,
        }
    ]
    assert list(body["stage_latency_avg"]) == ["understand", "retrieve", "total"]
    assert body["stage_latency_avg"]["retrieve"] == pytest.approx(150.0)
    ingestion = body["ingestion"]
    assert ingestion["documents_by_status"]["indexed"] == 3
    assert ingestion["documents_by_status"]["forgotten"] == 1
    assert ingestion["jobs_by_status"] == {"queued": 1, "running": 0, "succeeded": 1, "failed": 2}
    assert ingestion["avg_ingest_ms"] == pytest.approx(1500.0, abs=1)


async def test_metrics_top_sources_respect_visibility(
    client_for,  # type: ignore[no-untyped-def]
    dataset: Dataset,
) -> None:
    viewer = await client_for(dataset.viewer)
    body = (await viewer.get(f"/api/v1/projects/{dataset.slug}/metrics")).json()
    assert [s["document_id"] for s in body["top_sources"]] == [str(dataset.doc_public)]
    assert "Budget" not in json.dumps(body["top_sources"])


async def test_metrics_validates_days(admin_client: httpx.AsyncClient, dataset: Dataset) -> None:
    response = await admin_client.get(f"/api/v1/projects/{dataset.slug}/metrics", params={"days": 0})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_trace_export_ndjson_owner_only(
    admin_client: httpx.AsyncClient,
    client_for,  # type: ignore[no-untyped-def]
    dataset: Dataset,
) -> None:
    viewer = await client_for(dataset.viewer)
    denied = await viewer.get(f"/api/v1/projects/{dataset.slug}/traces/export")
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"

    response = await admin_client.get(f"/api/v1/projects/{dataset.slug}/traces/export", params={"days": 30})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in response.headers["content-disposition"]
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert len(lines) == 4 == int(response.headers["x-orbit-trace-count"])
    created = [line["request"]["created_at"] for line in lines]
    assert created == sorted(created)
    first = lines[0]
    assert set(first) == {"schema", "request", "timings", "context", "decisions", "feedback"}
    assert first["request"]["agent"]["name"] == "Agent Produit"
    assert first["request"]["on_behalf_of"]["full_name"] == "Sarah Nguyen"
    with_feedback = [line for line in lines if line["feedback"]]
    assert sorted(line["feedback"][0]["rating"] for line in with_feedback) == [4, 5]

    audit = await admin_client.get(f"/api/v1/projects/{dataset.slug}/audit", params={"action": "traces"})
    assert audit.json()["items"][0]["action"] == "traces.export"


async def test_metrics_require_membership(
    make_user,  # type: ignore[no-untyped-def]
    client_for,  # type: ignore[no-untyped-def]
    dataset: Dataset,
) -> None:
    outsider = await client_for(await make_user())
    for path in ("overview", "metrics", "traces/export"):
        response = await outsider.get(f"/api/v1/projects/{dataset.slug}/{path}")
        assert response.status_code == 404, path

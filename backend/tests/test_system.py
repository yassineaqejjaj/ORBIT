"""System endpoints, error format and middleware."""

from __future__ import annotations

import httpx

from app.enums import REASON_CODE_LABELS, ReasonCode


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_reports_dependencies(client: httpx.AsyncClient) -> None:
    response = await client.get("/ready")
    body = response.json()
    assert set(body["checks"]) == {"postgres", "opensearch", "valkey", "model"}
    assert body["checks"]["postgres"]["status"] == "ok"
    assert body["checks"]["postgres"]["info"]["migration"] == "0006"  # head of the chained production-readiness migrations
    assert body["checks"]["valkey"]["status"] == "ok"
    assert body["checks"]["opensearch"]["status"] == "ok"
    assert response.status_code == (200 if body["status"] == "ok" else 503)


async def test_meta(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    assert body["embedding_model"]
    assert body["reranker"] == "heuristic"
    assert body["llm"] is None
    assert set(body["reason_codes"]) == {code.value for code in ReasonCode}
    assert body["reason_codes"]["EXCLUDED_ACL"] == REASON_CODE_LABELS[ReasonCode.EXCLUDED_ACL]


async def test_prometheus_metrics(client: httpx.AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "orbit_context_requests_total" in response.text
    assert "orbit_ingestion_jobs_total" in response.text


async def test_request_id_is_propagated(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "demo-request-42"})
    assert response.headers["x-request-id"] == "demo-request-42"
    generated = await client.get("/health")
    assert len(generated.headers["x-request-id"]) >= 6


async def test_unknown_route_uses_error_format(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Ressource introuvable", "code": "not_found"}


async def test_validation_error_format(admin_client: httpx.AsyncClient) -> None:
    response = await admin_client.post("/api/v1/projects", json={"name": "", "unexpected": 1})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["detail"].startswith("Données invalides")
    assert {e["field"] for e in body["errors"]} == {"name", "unexpected"}


async def test_not_implemented_maps_to_501(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/_test/not-implemented")
    assert response.status_code == 501
    assert response.json()["code"] == "not_implemented"


async def test_unhandled_error_maps_to_500(lenient_client: httpx.AsyncClient) -> None:
    response = await lenient_client.get("/api/v1/_test/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Erreur interne du serveur", "code": "internal_error"}


async def test_openapi_is_served(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in (
        "/api/v1/auth/login",
        "/api/v1/projects/{slug}/context",
        "/api/v1/projects/{slug}/memory/{memory_id}/supersede",
        "/api/v1/projects/{slug}/snapshots/{name}/diff",
        "/api/v1/projects/{slug}/traces/export",
    ):
        assert path in paths

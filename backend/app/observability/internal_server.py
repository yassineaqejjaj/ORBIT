"""Minimal internal HTTP endpoint (``ORBIT_METRICS_PORT``) for probes and Prometheus scrapes.

Served by processes that have no web framework of their own (the worker) — a few dozen lines of
``asyncio`` instead of a second ASGI server. Routes:

* ``GET /healthz`` — liveness verdict of the process (``200`` healthy, ``503`` otherwise) from the
  provided callback, as JSON;
* ``GET /metrics`` — Prometheus exposition, same token policy as the API
  (:func:`app.observability.metrics.authorized_scrape` with ``internal=True``).

Only ``GET``/``HEAD`` are accepted; requests are bounded (header size, read timeout) because the
port may be reachable from the cluster network.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.observability.metrics import authorized_scrape, metrics_payload, metrics_token

logger = logging.getLogger("orbit.internal_http")

MAX_HEADER_BYTES = 16 * 1024
READ_TIMEOUT_SECONDS = 5.0

#: ``(healthy, details)`` — details are serialised as the JSON body.
HealthCallback = Callable[[], Awaitable[tuple[bool, dict[str, Any]]]]

_REASONS = {
    200: "OK",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    503: "Service Unavailable",
}


@dataclass(slots=True)
class _Response:
    status: int
    body: bytes
    content_type: str = "application/json"


def _json(status: int, payload: dict[str, Any]) -> _Response:
    return _Response(status, json.dumps(payload, ensure_ascii=False, default=str).encode())


class InternalServer:
    """``/healthz`` + ``/metrics`` on ``host:port`` (start with :meth:`start`, stop with :meth:`close`)."""

    def __init__(self, host: str, port: int, health: HealthCallback) -> None:
        self.host = host
        self.port = port
        self._health = health
        self._server: asyncio.Server | None = None

    @property
    def bound_port(self) -> int | None:
        """Actual listening port (useful with ``port=0`` in tests)."""
        if self._server is None or not self._server.sockets:
            return None
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

    async def _route(self, method: str, path: str, headers: dict[str, str]) -> _Response:
        if method not in {"GET", "HEAD"}:
            return _json(405, {"detail": "Méthode non autorisée", "code": "method_not_allowed"})
        route = path.split("?", 1)[0]
        if route in {"/healthz", "/livez"}:
            try:
                healthy, details = await self._health()
            except Exception as exc:  # the probe itself must never crash the server
                logger.warning("Health callback failed: %s", exc)
                healthy, details = False, {"error": type(exc).__name__}
            return _json(200 if healthy else 503, {"status": "ok" if healthy else "unhealthy", **details})
        if route == "/metrics":
            if not authorized_scrape(headers.get("authorization"), internal=True):
                status = 401 if metrics_token() else 404
                return _json(status, {"detail": "Non autorisé", "code": "unauthorized"})
            payload, content_type = metrics_payload()
            return _Response(200, payload, content_type)
        return _json(404, {"detail": "Introuvable", "code": "not_found"})

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=READ_TIMEOUT_SECONDS)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
                return
            if len(raw) > MAX_HEADER_BYTES:
                return
            lines = raw.decode("latin-1").split("\r\n")
            parts = lines[0].split(" ")
            if len(parts) != 3:
                return
            method, path, _version = parts
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip().lower()] = value.strip()
            response = await self._route(method.upper(), path, headers)
            body = b"" if method.upper() == "HEAD" else response.body
            head = (
                f"HTTP/1.1 {response.status} {_REASONS.get(response.status, 'OK')}\r\n"
                f"Content-Type: {response.content_type}\r\n"
                f"Content-Length: {len(response.body)}\r\n"
                "Cache-Control: no-store\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(head.encode("latin-1") + body)
            await writer.drain()
        except (ConnectionError, OSError):
            return
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

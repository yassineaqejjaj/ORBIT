"""Pure-ASGI request middleware: request id propagation (``X-Request-ID``) and access log."""

from __future__ import annotations

import logging
import re
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.context import new_request_id, reset_request_id, set_request_id

logger = logging.getLogger("orbit.access")

_VALID_ID = re.compile(r"^[A-Za-z0-9._\-]{6,128}$")
_QUIET_PATHS = ("/health", "/ready", "/metrics")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming if incoming and _VALID_ID.match(incoming) else new_request_id()
        token = set_request_id(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                if not any(h[0].lower() == b"x-request-id" for h in headers):
                    headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if not path.startswith(_QUIET_PATHS):
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "%s %s -> %s (%.1f ms)",
                    scope.get("method", "?"),
                    path,
                    status_holder["status"],
                    elapsed_ms,
                )
            reset_request_id(token)

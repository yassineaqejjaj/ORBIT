"""Logging configuration (single-line records enriched with the request id)."""

from __future__ import annotations

import logging
import sys

from app.observability.context import get_request_id

_CONFIGURED = False


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


def setup_logging(level: str = "INFO") -> None:
    """Idempotent root logger configuration used by the API and the worker."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level)
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s [rid=%(request_id)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(RequestIdFilter())
    root.handlers = [handler]
    for noisy in ("httpx", "httpcore", "opensearch", "urllib3", "asyncio", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # uvicorn access logs are replaced by the request middleware log line.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    _CONFIGURED = True

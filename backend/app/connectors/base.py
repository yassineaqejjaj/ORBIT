"""Connector framework (docs/FEATURES.md F5): HTTP client with retries, item model, connector interface.

A connector turns a remote system into a stream of :class:`Change` (upserts and deletions) from an
incremental ``cursor``; :mod:`app.connectors.sync` maps them onto the ingestion pipeline.

Network access goes through :class:`HttpClient` only: retries with exponential backoff on 429/5xx and
transport errors, honouring ``Retry-After`` (seconds or HTTP date, capped). Tests replace the network
with ``transport_override`` (an ``httpx.MockTransport``) and ``sleep`` (no real waiting).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar

import httpx

from app.enums import SourceKind

USER_AGENT = "ORBIT-Connectors/1.0"
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 120.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Test hook: an ``httpx`` transport replacing the network (``httpx.MockTransport``).
transport_override: httpx.AsyncBaseTransport | None = None
#: Test hook: coroutine used to wait between retries.
sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


class ConnectorError(Exception):
    """Failure talking to the remote system (French, user-facing message)."""

    def __init__(self, message: str, *, auth: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.auth = auth
        self.status_code = status_code


class NotFoundError(ConnectorError):
    """The remote object does not exist (HTTP 404/410)."""


def retry_after_seconds(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header (delay in seconds or HTTP date)."""
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, min(MAX_RETRY_AFTER_SECONDS, seconds))


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter for retry number ``attempt`` (1-based): ~1 s, 2 s, 4 s…"""
    base = BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1))
    return min(MAX_RETRY_AFTER_SECONDS, base * (0.75 + random.random() / 2))


def _remote_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        for key in ("message", "errorMessages", "error_description", "error"):
            value = body.get(key)
            if isinstance(value, dict):
                value = value.get("message")
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            if value:
                return str(value)[:200]
    return ""


class HttpClient:
    """``httpx`` wrapper: base URL, auth headers, retries/backoff honouring ``Retry-After``."""

    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        max_retries: int = MAX_RETRIES,
        follow_redirects: bool = False,
    ) -> None:
        self.headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        self.max_retries = max_retries
        self.requests = 0
        self.retries = 0
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, transport=transport_override, follow_redirects=follow_redirects
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send with retries. Raises :class:`ConnectorError` (or :class:`NotFoundError`) on failure."""
        headers = {**self.headers, **(kwargs.pop("headers", None) or {})}
        attempt = 0
        while True:
            attempt += 1
            self.requests += 1
            try:
                response = await self._client.request(method, url, headers=headers, **kwargs)
            except httpx.TransportError as exc:
                if attempt > self.max_retries:
                    raise ConnectorError(f"Service injoignable : {type(exc).__name__}") from exc
                self.retries += 1
                await sleep(backoff_seconds(attempt))
                continue
            if response.status_code in RETRY_STATUSES and attempt <= self.max_retries:
                self.retries += 1
                delay = retry_after_seconds(response.headers.get("retry-after"))
                await sleep(delay if delay is not None else backoff_seconds(attempt))
                continue
            if response.status_code < 400:
                return response
            raise self._error(response)

    @staticmethod
    def _error(response: httpx.Response) -> ConnectorError:
        status = response.status_code
        detail = _remote_message(response)
        suffix = f" ({detail})" if detail else ""
        if status in (401, 403):
            return ConnectorError(
                f"Identifiants refusés par le service (HTTP {status}){suffix}", auth=True, status_code=status
            )
        if status in (404, 410):
            return NotFoundError(f"Ressource introuvable (HTTP {status})", status_code=status)
        if status == 429:
            return ConnectorError(
                "Limite de débit du service atteinte, réessayez plus tard", status_code=status
            )
        return ConnectorError(f"Erreur du service distant (HTTP {status}){suffix}", status_code=status)

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        response = await self.request("GET", url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError("Réponse inattendue du service (JSON invalide)") from exc


# --- Items ----------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Change:
    """One remote change: an upsert (content) or a deletion (``deleted=True``) of ``external_id``."""

    external_id: str
    deleted: bool = False
    title: str = ""
    mime_type: str = "text/markdown"
    data: bytes | None = None
    text: str | None = None
    filename: str | None = None
    uri: str | None = None
    author: str | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Reason the item is not ingested (unsupported format, too large…): counted as ``skipped``.
    skip_reason: str | None = None
    #: Fetching the item failed (counted as an error, the sync goes on).
    error: str | None = None


@dataclass(slots=True)
class ScopeOption:
    """Selectable scope element shown by the wizard (site, library, space, project)."""

    id: str
    label: str
    kind: str
    parent_id: str | None = None
    description: str = ""


@dataclass(slots=True)
class CredentialCheck:
    ok: bool
    message: str
    account: str | None = None
    scope_options: list[ScopeOption] = field(default_factory=list)


def parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    # Jira: 2026-09-30T10:15:00.000+0200 → insert the colon of the offset.
    if len(text) > 5 and text[-5] in "+-" and text[-3] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class BaseConnector:
    """Interface of a connector type. Instances are short-lived (one test or one sync)."""

    type: ClassVar[str]
    label: ClassVar[str]
    source_kind: ClassVar[SourceKind] = SourceKind.document

    def __init__(self, config: dict[str, Any], secret: str) -> None:
        self.config = config
        self.secret = secret
        self.http = HttpClient(headers=self.auth_headers())
        #: Cursor to persist once the sync completed (set by :meth:`changes`).
        self.next_cursor: dict[str, Any] = {}

    def auth_headers(self) -> dict[str, str]:
        return {}

    async def aclose(self) -> None:
        await self.http.aclose()

    async def test(self) -> CredentialCheck:
        """Check the credentials (no ingestion) and list the selectable scope."""
        raise NotImplementedError

    def changes(self, cursor: dict[str, Any]) -> AsyncIterator[Change]:
        """Changes since ``cursor`` (full listing when empty); sets :attr:`next_cursor` at the end."""
        raise NotImplementedError

    async def confirm_deleted(self, known_ids: set[str]) -> list[str]:
        """External ids among ``known_ids`` deleted at the source (sources without delta feeds)."""
        return []

    def scope_label(self) -> str:
        return ""

    @classmethod
    def validate_config(cls, config: dict[str, Any], *, require_scope: bool) -> dict[str, Any]:
        """Normalised non-secret configuration; raises ``ValueError`` (French message)."""
        raise NotImplementedError

    @classmethod
    def base_url(cls, config: dict[str, Any]) -> str | None:
        """User-provided base URL (checked against SSRF), ``None`` for fixed cloud endpoints."""
        return None


# --- Config helpers -------------------------------------------------------------------------------------


def text_field(
    config: dict[str, Any], key: str, label: str, *, required: bool = True, max_length: int = 500
) -> str:
    value = config.get(key)
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise ValueError(f"Champ requis : {label}")
    if len(value) > max_length:
        raise ValueError(f"{label} : {max_length} caractères maximum")
    return value


def list_field(config: dict[str, Any], key: str, label: str, *, max_items: int = 100) -> list[str]:
    raw = config.get(key) or []
    if isinstance(raw, str):
        raw = [part for part in raw.replace(";", ",").split(",")]
    if not isinstance(raw, list):
        raise ValueError(f"{label} : liste attendue")
    values: list[str] = []
    for item in raw:
        value = str(item).strip()
        if value and value not in values:
            values.append(value[:300])
    if len(values) > max_items:
        raise ValueError(f"{label} : {max_items} éléments maximum")
    return values


def deployment_field(config: dict[str, Any]) -> str:
    value = str(config.get("deployment") or "cloud").strip().lower()
    if value not in ("cloud", "datacenter"):
        raise ValueError("Déploiement inconnu : choisissez « cloud » ou « datacenter »")
    return value


def url_field(config: dict[str, Any]) -> str:
    value = text_field(config, "base_url", "URL du service", max_length=2000).rstrip("/")
    if not value.lower().startswith(("https://", "http://")):
        raise ValueError("L'URL du service doit commencer par https://")
    return value

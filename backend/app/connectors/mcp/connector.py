"""Generic MCP connector (type ``mcp``, preset id in ``config.preset``) — docs/FEATURES.md F6.

Implements the F5 connector interface (:class:`~app.connectors.base.BaseConnector`) on top of an MCP
session: the credentials test is ``initialize`` + ``list_tools`` (required tools present) + one
lightweight authenticated call; the sync runs the preset's plan (list → read → map) and yields
:class:`~app.connectors.base.Change` objects that :mod:`app.connectors.sync` ingests exactly like the
other connectors (content-hash dedupe, new versions, change events, audit).

Incremental sync: one cursor per stream and scope value (``"<stream>:<value>"`` → newest
``updated_at`` seen) when the tools allow filtering or ordering; otherwise every item is re-read and
unchanged ones are deduplicated by ``ingest_content``. Deletions are detected only for streams that
list every item at each sync (``full_listing``), only when the listing completed, the scope did not
change and something was listed; delta feeds (Microsoft Graph) report deletions directly.

Limits: ``ORBIT_MCP_MAX_ITEMS`` items per sync, ``ORBIT_MCP_MAX_CONTENT_BYTES`` per item,
``ORBIT_MCP_SYNC_TIMEOUT_SECONDS`` overall, ``ORBIT_MCP_TIMEOUT_SECONDS`` per call.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.config import settings
from app.connectors.base import (
    BaseConnector,
    Change,
    ConnectorError,
    CredentialCheck,
    ScopeOption,
    list_field,
    text_field,
)
from app.connectors.mcp.client import HttpTarget, McpCallError, McpClient, StdioTarget, resolve_command
from app.connectors.mcp.mapper import Record, as_datetime, csv_rows, find_list, first, payload, text_of
from app.connectors.mcp.presets import Ctx, Preset, PresetField, Stream, get_preset
from app.enums import SourceKind

logger = logging.getLogger(__name__)

MAX_PAGES_PER_SCOPE = 500
SCOPE_KEY = "__scope"


def parse_secret(preset: Preset, secret: str) -> dict[str, str]:
    """Secret fields of a preset from the stored secret (JSON object; a bare string = first field)."""
    secret = (secret or "").strip()
    fields = preset.secret_fields()
    try:
        value = json.loads(secret) if secret.startswith("{") else None
    except ValueError:
        value = None
    if isinstance(value, dict) and not (
        preset.id == "google_workspace" and value.get("type") == "service_account"
    ):
        return {str(k): str(v) for k, v in value.items() if v not in (None, "")}
    if fields and secret:
        return {fields[0].key: secret}
    return {}


def _coerce(field: PresetField, raw: Any) -> Any:
    if field.kind == "list":
        default = field.default if raw is None else raw
        return list_field({"v": default}, "v", field.label)
    if field.kind == "bool":
        if raw is None:
            return bool(field.default)
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "oui", "on")
        return bool(raw)
    if field.kind == "number":
        value = field.default if raw in (None, "") else raw
        if value in (None, ""):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field.label} : nombre entier attendu") from exc
        if not 0 < number <= 65535:
            raise ValueError(f"{field.label} : valeur hors limites")
        return number
    value = text_field(
        {"v": field.default if raw in (None, "") else raw}, "v", field.label, required=False, max_length=2000
    )
    if field.kind == "select" and value and field.options and value not in {o[0] for o in field.options}:
        raise ValueError(f"{field.label} : valeur inconnue « {value} »")
    if field.kind == "url" and value:
        value = value.rstrip("/")
        if not value.lower().startswith(("https://", "http://")):
            raise ValueError(f"{field.label} : l'URL doit commencer par https://")
    return value


def _visible(field: PresetField, config: dict[str, Any]) -> bool:
    if not field.visible_if:
        return True
    key, _, expected = field.visible_if.partition("=")
    value = config.get(key)
    if isinstance(value, bool):
        return str(value).lower() == expected
    return str(value or "") == expected


def _jsonable(metadata: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None or key == "replies":
            continue
        if isinstance(value, (str, int, float, bool)):
            out[key] = value if not isinstance(value, str) else value[:500]
        elif isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value):
            out[key] = value[:50]
    return out


class McpConnector(BaseConnector):
    type: ClassVar[str] = "mcp"
    label: ClassVar[str] = "MCP"
    source_kind: ClassVar[SourceKind] = SourceKind.document

    def __init__(self, config: dict[str, Any], secret: str) -> None:
        super().__init__(config, secret)
        self.preset = get_preset(config.get("preset"))
        self.secrets = parse_secret(self.preset, secret)
        self.client: McpClient | None = None
        self.tools: list[str] = []
        self._seen: dict[str, set[str]] = {}
        self._complete: dict[str, bool] = {}
        self._budget = int(settings.mcp_max_items)
        self._deadline = 0.0
        self.truncated = False

    # --- class-level hooks (service / API) -------------------------------------------------------------

    @classmethod
    def validate_config(cls, config: dict[str, Any], *, require_scope: bool) -> dict[str, Any]:
        preset = get_preset(config.get("preset"))
        clean: dict[str, Any] = {"preset": preset.id}
        for field in preset.config_fields():
            clean[field.key] = _coerce(field, config.get(field.key))
        for field in preset.config_fields():
            value = clean.get(field.key)
            empty = value in (None, "", [])
            needed = field.required and (field.group != "scope" or require_scope)
            if needed and empty and _visible(field, clean):
                raise ValueError(f"Champ requis : {field.label}")
        preset.validate(clean, require_scope)
        return clean

    @classmethod
    def base_urls(cls, config: dict[str, Any]) -> list[str]:
        preset = get_preset(config.get("preset"))
        return [url for url in preset.endpoints(config) if url]

    @classmethod
    def normalize_secret(cls, config: dict[str, Any], secret: str) -> str:
        preset = get_preset(config.get("preset"))
        values = parse_secret(preset, secret)
        for field in preset.secret_fields():
            if field.required and not values.get(field.key):
                raise ValueError(f"Champ requis : {field.label}")
        known = {f.key for f in preset.secret_fields()}
        return json.dumps({k: v for k, v in values.items() if k in known}, ensure_ascii=False)

    @classmethod
    def secret_hint_of(cls, config: dict[str, Any], secret: str) -> str:
        from app.connectors.secrets import hint

        values = parse_secret(get_preset(config.get("preset")), secret)
        longest = max(values.values(), key=len, default="")
        return hint(longest) if longest else "••••"

    @classmethod
    def display_label(cls, config: dict[str, Any]) -> str:
        try:
            return f"{get_preset(config.get('preset')).label} (MCP)"
        except ValueError:
            return "MCP"

    @classmethod
    def kind_for(cls, config: dict[str, Any]) -> SourceKind:
        try:
            return SourceKind(get_preset(config.get("preset")).source_kind)
        except ValueError:
            return SourceKind.document

    def scope_label(self) -> str:
        return self.preset.label

    # --- session ------------------------------------------------------------------------------------

    def target(self) -> StdioTarget | HttpTarget:
        preset, config = self.preset, self.config
        if preset.transport_of(config) == "http":
            url = preset.url(config) if preset.url else ""
            if not url:
                raise ConnectorError("URL du serveur MCP manquante")
            return HttpTarget(url=url, headers=preset.headers(config, self.secrets))
        if preset.id == "custom":
            command = [str(config.get("command") or "")]
        else:
            if not preset.command:
                raise ConnectorError("Commande MCP non définie pour ce préréglage")
            command = resolve_command(preset.command, list(preset.fallback)) or []
            if not command:
                raise ConnectorError(
                    f"Le serveur MCP « {preset.command} » n'est pas installé sur ce serveur ORBIT "
                    "(image Docker sans les outils MCP ?)"
                )
        return StdioTarget(
            command=command[0],
            args=[*command[1:], *preset.args(config)],
            env={k: v for k, v in preset.env(config, self.secrets).items() if v not in (None, "")},
        )

    async def _open(self) -> McpClient:
        if self.client is None:
            client = McpClient(
                self.target(),
                timeout=float(settings.mcp_timeout_seconds),
                secrets=list(self.secrets.values()),
                label=f"serveur MCP {self.preset.label}",
            )
            await client.start()
            self.client = client
        return self.client

    async def aclose(self) -> None:
        await super().aclose()
        if self.client is not None:
            client, self.client = self.client, None
            await client.aclose()

    async def _tools(self) -> list[str]:
        client = await self._open()
        self.tools = sorted(t.name for t in await client.list_tools())
        return self.tools

    # --- credentials test -----------------------------------------------------------------------------

    async def test(self) -> CredentialCheck:
        client = await self._open()
        tools = await self._tools()
        account = " ".join(p for p in (client.server_name, client.server_version) if p) or None
        missing = [t for t in self.preset.required_tools if t not in tools]
        if missing:
            return CredentialCheck(
                ok=False,
                message=f"Serveur MCP joignable mais outils requis absents : {', '.join(missing)}",
                account=account,
                tools=tools,
            )
        if self.preset.id == "custom" and not tools:
            resources = await client.list_resources()
            return CredentialCheck(
                ok=True, message=f"Connexion MCP établie : {len(resources)} ressource(s)", account=account
            )
        options: list[ScopeOption] = []
        probe = self.preset.probe(self.config)
        if probe and probe[0] in tools:
            try:
                result = await client.call_tool(probe[0], probe[1])
            except McpCallError as exc:
                return CredentialCheck(ok=False, message=exc.message, account=account, tools=tools)
            options = self._scope_options(result)
        return CredentialCheck(
            ok=True,
            message=(
                f"Connexion MCP établie : {len(tools)} outil(s) disponible(s), "
                f"{len(self.preset.required_tools)} requis présent(s)"
            ),
            account=account,
            scope_options=options,
            tools=tools,
        )

    def _scope_options(self, result: Any) -> list[ScopeOption]:
        """Selectable scope from the probe (Slack channels)."""
        if self.preset.id != "slack":
            return []
        data = payload(result)
        rows = find_list(data) if isinstance(data, (dict, list)) else csv_rows(str(data))
        options: list[ScopeOption] = []
        for row in rows[:100]:
            ident = text_of(first(row, "id", "channelid"))
            name = text_of(first(row, "name", "channelname"))
            if ident:
                options.append(ScopeOption(id=ident, label=name or ident, kind="channel"))
        return options

    # --- synchronisation -------------------------------------------------------------------------------

    def _out_of_budget(self) -> bool:
        if self._budget <= 0 or time.monotonic() > self._deadline:
            self.truncated = True
            return True
        return False

    def _limit_change(self) -> Change:
        reason = (
            f"Limite de {settings.mcp_max_items} élément(s) par synchronisation atteinte"
            if self._budget <= 0
            else f"Durée maximale de synchronisation atteinte ({settings.mcp_sync_timeout_seconds:.0f} s)"
        )
        return Change(
            external_id="__limit__", title="Limite MCP", error=f"{reason} : la suite au prochain passage"
        )

    def _change(self, stream: Stream, record: Record) -> Change:
        external_id = f"{stream.key}:{record.external_id}"[:1000]
        if record.deleted:
            return Change(external_id=external_id, deleted=True)
        metadata = _jsonable(
            {
                "mcp_preset": self.preset.id,
                "mcp_stream": stream.key,
                "source_kind": record.source_kind,
                **record.metadata,
            }
        )
        title = (record.title or record.external_id)[:500]
        max_bytes = int(settings.mcp_max_content_bytes)
        if record.data is not None:
            from app.ingestion.extractors import detect_mime_type, is_supported

            mime = detect_mime_type(record.filename or title, record.mime_type, record.data)
            skip = None
            if len(record.data) > max_bytes:
                skip = f"Fichier trop volumineux ({len(record.data)} octets)"
            elif not is_supported(mime, record.filename or title):
                skip = f"Format non pris en charge ({mime})"
            return Change(
                external_id=external_id,
                title=title,
                mime_type=mime,
                data=record.data,
                filename=record.filename,
                uri=record.uri,
                author=record.author,
                updated_at=record.updated_at,
                metadata=metadata,
                skip_reason=skip,
            )
        content = record.content or ""
        return Change(
            external_id=external_id,
            title=title,
            mime_type=record.mime_type or "text/markdown",
            text=content,
            uri=record.uri,
            author=(record.author or "")[:300] or None,
            updated_at=record.updated_at,
            metadata=metadata,
            skip_reason=(
                f"Contenu trop volumineux ({len(content.encode())} octets)"
                if len(content.encode()) > max_bytes
                else ("Contenu vide" if not content.strip() else None)
            ),
        )

    async def changes(self, cursor: dict[str, Any]) -> AsyncIterator[Change]:
        self.next_cursor = {}
        self._deadline = time.monotonic() + float(settings.mcp_sync_timeout_seconds)
        self._budget = int(settings.mcp_max_items)
        client = await self._open()
        tools = await self._tools()
        missing = [t for t in self.preset.required_tools if t not in tools]
        if missing:
            raise ConnectorError(f"Outils MCP requis absents du serveur : {', '.join(missing)}")
        if self.preset.id == "custom":
            async for change in self._resources(client, cursor):
                yield change
            return
        for stream in self.preset.streams:
            if not stream.enabled(self.config):
                continue
            tool = stream.list_tool if isinstance(stream.list_tool, str) else None
            if tool and tool not in tools:
                logger.info("MCP %s: stream %s skipped (tool %s absent)", self.preset.id, stream.key, tool)
                continue
            values: list[str | None] = [None]
            if stream.foreach:
                configured = [str(v) for v in (self.config.get(stream.foreach) or [])]
                values = list(configured) or ([stream.foreach_default] if stream.foreach_default else [])
            self._complete[stream.key] = True
            scope_hash = hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest()[:16]
            self.next_cursor[f"{stream.key}:{SCOPE_KEY}"] = scope_hash
            if cursor.get(f"{stream.key}:{SCOPE_KEY}") != scope_hash:
                self._complete[stream.key] = False  # scope changed: no deletion inference this time
            for value in values:
                async for change in self._run_stream(client, stream, value, cursor):
                    yield change
                if self.truncated:
                    break
            if self.truncated:
                yield self._limit_change()
                break

    async def _run_stream(
        self, client: McpClient, stream: Stream, value: str | None, cursor: dict[str, Any]
    ) -> AsyncIterator[Change]:
        cursor_key = f"{stream.key}:{value}" if value is not None else stream.key
        since = as_datetime(cursor.get(cursor_key)) if stream.incremental != "none" else None
        if since and stream.day_cursor:
            since = since.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        ctx = Ctx(config=self.config, item=value, since=since)
        seen = self._seen.setdefault(stream.key, set())
        local_seen: set[str] = set()
        newest: datetime | None = as_datetime(cursor.get(cursor_key))
        complete = True
        aggregated: list[Record] = []
        pages: deque[Any] = deque(stream.initial_pages(ctx))
        visited: set[str] = set()
        page_count = 0
        while pages:
            page = pages.popleft()
            marker = json.dumps(page, default=str)
            if marker in visited:
                continue
            visited.add(marker)
            page_count += 1
            if page_count > MAX_PAGES_PER_SCOPE or self._out_of_budget():
                complete = False
                break
            ctx.page = page
            tool = stream.list_tool(ctx) if callable(stream.list_tool) else stream.list_tool
            try:
                listed = await client.call_tool(tool, stream.list_args(ctx))
            except McpCallError as exc:
                if exc.auth:
                    raise
                if stream.ignore_list_errors:
                    continue
                complete = False
                yield Change(
                    external_id=f"{stream.key}:{value or '*'}",
                    title=f"{stream.label} {value or ''}".strip(),
                    error=exc.message,
                )
                break
            ctx.result = listed
            data = payload(listed)
            items = stream.items(data, ctx)
            stop = False
            for item in items:
                native = stream.item_id(item, ctx)
                if not native or native in local_seen:
                    continue
                local_seen.add(native)
                seen.add(f"{stream.key}:{native}")
                updated = stream.item_updated(item)
                if since and updated:
                    if stream.incremental == "stop" and updated <= since:
                        stop = True
                        break
                    if stream.incremental == "skip" and updated <= since:
                        continue
                if self._out_of_budget():
                    complete = False
                    stop = True
                    break
                read_data: Any = None
                if stream.read_tool and stream.read_args:
                    read_args = stream.read_args(item, ctx)
                    if read_args:
                        try:
                            read_result = await client.call_tool(stream.read_tool, read_args)
                        except McpCallError as exc:
                            if exc.auth:
                                raise
                            complete = False
                            yield Change(
                                external_id=f"{stream.key}:{native}", title=str(native), error=exc.message
                            )
                            continue
                        ctx.result = read_result
                        read_data = payload(read_result)
                try:
                    record = stream.map(item, read_data, ctx)
                except Exception as exc:  # a mapper bug must not stop the sync
                    logger.warning("MCP %s: mapping of %s failed: %s", self.preset.id, native, exc)
                    record = None
                    yield Change(
                        external_id=f"{stream.key}:{native}",
                        title=str(native),
                        error=f"Élément illisible ({type(exc).__name__})",
                    )
                ctx.result = listed
                if record is None:
                    continue
                stamp = record.updated_at or updated
                if stamp and (newest is None or stamp > newest):
                    newest = stamp
                if stream.aggregate:
                    aggregated.append(record)
                    continue
                self._budget -= 1
                yield self._change(stream, record)
            if stop:
                break
            pages.extend(stream.next_pages(data, items, ctx))
        if stream.aggregate and aggregated:
            for record in stream.aggregate(aggregated, ctx):
                self._budget -= 1
                yield self._change(stream, record)
        if not complete:
            self._complete[stream.key] = False
        if newest and (complete or stream.ascending):
            self.next_cursor[cursor_key] = newest.astimezone(UTC).isoformat()
        elif cursor.get(cursor_key):
            self.next_cursor[cursor_key] = cursor[cursor_key]

    async def _resources(self, client: McpClient, cursor: dict[str, Any]) -> AsyncIterator[Change]:
        """Custom servers: every listed resource is read and ingested (full listing)."""
        stream = Stream(
            key="resource",
            label="Ressources",
            list_tool="",
            list_args=lambda ctx: {},
            item_id=lambda item, ctx: None,
            map=lambda item, data, ctx: None,
            full_listing=True,
        )
        from app.connectors.mcp.presets import _map_resource

        resources = await client.list_resources()
        seen = self._seen.setdefault("resource", set())
        self._complete["resource"] = bool(resources)
        for resource in resources:
            if self._out_of_budget():
                self._complete["resource"] = False
                yield self._limit_change()
                return
            uri = str(resource.uri)
            seen.add(f"resource:{uri}")
            try:
                result = await client.read_resource(uri)
            except McpCallError as exc:
                if exc.auth:
                    raise
                self._complete["resource"] = False
                yield Change(external_id=f"resource:{uri}", title=resource.name or uri, error=exc.message)
                continue
            item = {
                "uri": uri,
                "name": resource.name,
                "title": resource.title,
                "mime_type": resource.mime_type,
            }
            record = _map_resource(item, None, Ctx(config=self.config, result=result))
            if record is not None:
                self._budget -= 1
                yield self._change(stream, record)

    async def confirm_deleted(self, known_ids: set[str]) -> list[str]:
        streams = [s.key for s in self.preset.streams if s.full_listing] + (
            ["resource"] if self.preset.id == "custom" else []
        )
        deleted: list[str] = []
        for key in streams:
            seen = self._seen.get(key) or set()
            if not self._complete.get(key) or not seen or self.truncated:
                continue
            deleted.extend(k for k in known_ids if k.startswith(f"{key}:") and k not in seen)
        return sorted(deleted)

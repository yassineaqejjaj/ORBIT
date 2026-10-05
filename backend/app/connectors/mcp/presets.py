"""Curated MCP presets (docs/FEATURES.md F6, docs/integrations/mcp-servers.md).

A preset declares *how* to start a known MCP server (allowlisted command or vendor URL, pinned
version), which credential/scope fields the wizard shows, which tools it needs, and a **plan**: a list
of :class:`Stream` (one list tool, its argument template, pagination, optional read tool per item and a
mapper to :class:`~app.connectors.mcp.mapper.Record`). Tool names and arguments come from the
discovery of each server (``list_tools`` on the pinned versions); they are never user-provided.

Only these commands can be started: user input only fills *arguments values* and *environment values*
of these commands, built server-side. The ``custom`` preset (arbitrary command/URL) is gated by
``ORBIT_MCP_ALLOW_CUSTOM`` and platform-admin rights (see the API).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal

from app.connectors.mcp.mapper import (
    Record,
    as_datetime,
    comments_markdown,
    csv_rows,
    dig,
    drive_lines,
    find_list,
    first,
    markdown_sections,
    resource_blobs,
    resource_texts,
    result_text,
    strip_preamble,
    text_of,
)

FieldKind = Literal["text", "password", "textarea", "list", "select", "bool", "number", "url"]
FieldGroup = Literal["secret", "connection", "scope"]


@dataclass(frozen=True, slots=True)
class PresetField:
    key: str
    label: str
    group: FieldGroup
    kind: FieldKind = "text"
    required: bool = False
    help: str = ""
    placeholder: str = ""
    default: Any = None
    options: tuple[tuple[str, str], ...] = ()
    #: Shown only when another field has a value (``"field=value"``).
    visible_if: str | None = None


@dataclass(slots=True)
class Ctx:
    """Template context of one tool call."""

    config: dict[str, Any]
    item: str | None = None
    since: datetime | None = None
    page: Any = None
    result: Any = None
    state: dict[str, Any] = field(default_factory=dict)


def _items_default(payload: Any, ctx: Ctx) -> list[dict[str, Any]]:
    return find_list(payload)


def _no_pages(payload: Any, items: list[dict[str, Any]], ctx: Ctx) -> list[Any]:
    return []


@dataclass(frozen=True, slots=True)
class Stream:
    """One « list → (read) → map » step of a plan."""

    key: str
    label: str
    list_tool: str
    list_args: Callable[[Ctx], dict[str, Any]]
    item_id: Callable[[dict[str, Any], Ctx], str | None]
    map: Callable[[dict[str, Any], Any, Ctx], Record | None]
    items: Callable[[Any, Ctx], list[dict[str, Any]]] = _items_default
    #: Next pages to list (cursor/token/offset/sub-directories); ``[]`` = done.
    next_pages: Callable[[Any, list[dict[str, Any]], Ctx], list[Any]] = _no_pages
    item_updated: Callable[[dict[str, Any]], datetime | None] = lambda item: None
    read_tool: str | None = None
    read_args: Callable[[dict[str, Any], Ctx], dict[str, Any]] | None = None
    #: Config key whose list values are iterated (one listing per space, repo, channel…).
    foreach: str | None = None
    enabled: Callable[[dict[str, Any]], bool] = lambda config: True
    #: ``filter``: the list call filters on ``ctx.since``; ``skip``: items not newer than the cursor are
    #: skipped client-side; ``stop``: listing sorted newest first, stop at the first older item;
    #: ``none``: everything is read each time (content-hash dedupe).
    incremental: Literal["filter", "skip", "stop", "none"] = "none"
    #: Every item is listed at each sync: missing ones are deleted at the source.
    full_listing: bool = False
    #: Post-processing of the records of one ``foreach`` value (e.g. messages grouped per day).
    aggregate: Callable[[list[Record], Ctx], list[Record]] | None = None
    #: Cursor granularity: the cursor goes back to the start of the day (day-grouped documents).
    day_cursor: bool = False


@dataclass(frozen=True, slots=True)
class Preset:
    id: str
    label: str
    vendor: str
    description: str
    icon: str
    source_kind: str
    transport: Literal["stdio", "http"]
    fields: tuple[PresetField, ...]
    streams: tuple[Stream, ...]
    required_tools: tuple[str, ...]
    #: Installed binary (Docker images) and pinned fallback (dev machines: uvx/npx).
    command: str | None = None
    fallback: tuple[str, ...] = ()
    args: Callable[[dict[str, Any]], list[str]] = lambda config: []
    env: Callable[[dict[str, Any], dict[str, str]], dict[str, str]] = lambda config, secrets: {}
    url: Callable[[dict[str, Any]], str] | None = None
    headers: Callable[[dict[str, Any], dict[str, str]], dict[str, str]] = lambda config, secrets: {}
    #: Lightweight authenticated call of the credentials test: ``(tool, args)`` or ``None``.
    probe: Callable[[dict[str, Any]], tuple[str, dict[str, Any]] | None] = lambda config: None
    #: User-provided endpoints reached by the server (anti-SSRF check).
    endpoints: Callable[[dict[str, Any]], list[str]] = lambda config: []
    #: Transport chosen by the config (GitHub: remote or local binary).
    transport_for: Callable[[dict[str, Any]], Literal["stdio", "http"]] | None = None
    validate: Callable[[dict[str, Any], bool], None] = lambda config, require_scope: None
    version: str = ""
    docs_url: str = ""
    credentials_help: str = ""
    suggested_task: str = "Résumer les décisions, risques et points ouverts récents"
    admin_only: bool = False

    def secret_fields(self) -> list[PresetField]:
        return [f for f in self.fields if f.group == "secret"]

    def config_fields(self) -> list[PresetField]:
        return [f for f in self.fields if f.group != "secret"]

    def transport_of(self, config: dict[str, Any]) -> Literal["stdio", "http"]:
        return self.transport_for(config) if self.transport_for else self.transport


# --- helpers ----------------------------------------------------------------------------------------------


def _drop_empty(args: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if v not in (None, "", [], {})}


def _list(config: dict[str, Any], key: str) -> list[str]:
    value = config.get(key) or []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _bool(config: dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "oui", "on")
    return bool(value)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _offset_pages(page_size: int, total_key: str = "total") -> Callable[[Any, list[dict[str, Any]], Ctx], list[Any]]:
    def pages(payload: Any, items: list[dict[str, Any]], ctx: Ctx) -> list[Any]:
        offset = int(ctx.page or 0) + len(items)
        total = payload.get(total_key) if isinstance(payload, dict) else None
        token = first(payload, "next_page_token", "nextPageToken") if isinstance(payload, dict) else None
        if not items or len(items) < page_size and not token:
            return []
        if isinstance(total, int) and total >= 0 and offset >= total:
            return []
        return [offset]

    return pages


def _graphql_pages(payload: Any, items: list[dict[str, Any]], ctx: Ctx) -> list[Any]:
    info = first(payload, "pageInfo", "page_info") if isinstance(payload, dict) else None
    if isinstance(info, dict) and info.get("hasNextPage") and info.get("endCursor"):
        return [info["endCursor"]]
    token = first(payload, "nextCursor", "next_cursor", "cursor", "endCursor") if isinstance(payload, dict) else None
    if isinstance(token, str) and token and items and token != ctx.page:
        return [token]
    return []


def _page_number_pages(page_size: int) -> Callable[[Any, list[dict[str, Any]], Ctx], list[Any]]:
    def pages(payload: Any, items: list[dict[str, Any]], ctx: Ctx) -> list[Any]:
        return [int(ctx.page or 1) + 1] if len(items) >= page_size else []

    return pages


def _day_groups(prefix: str, title: Callable[[Ctx, str], str]) -> Callable[[list[Record], Ctx], list[Record]]:
    """Messages of one channel grouped into one Markdown document per day (stable external id)."""

    def aggregate(records: list[Record], ctx: Ctx) -> list[Record]:
        days: dict[str, list[Record]] = defaultdict(list)
        for record in records:
            when = record.updated_at or datetime.now(UTC)
            days[when.astimezone(UTC).strftime("%Y-%m-%d")].append(record)
        out: list[Record] = []
        for day, messages in sorted(days.items()):
            messages.sort(key=lambda r: r.updated_at or datetime.min.replace(tzinfo=UTC))
            lines = [f"# {title(ctx, day)}", ""]
            for message in messages:
                hour = message.updated_at.astimezone(UTC).strftime("%H:%M") if message.updated_at else ""
                lines.append(f"- **{message.author or '?'}** ({hour} UTC) : {(message.content or '').strip()}")
                for reply in message.metadata.get("replies") or []:
                    lines.append(f"  - ↳ {reply}")
            authors = sorted({m.author for m in messages if m.author})
            out.append(
                Record(
                    external_id=f"{ctx.item}:{day}",
                    title=title(ctx, day),
                    content="\n".join(lines) + "\n",
                    uri=messages[0].uri,
                    author=", ".join(authors[:5]) or None,
                    updated_at=max((m.updated_at for m in messages if m.updated_at), default=None),
                    source_kind=messages[0].source_kind,
                    metadata={"channel": ctx.item, "day": day, "message_count": len(messages), "kind": prefix},
                )
            )
        return out

    return aggregate


def _since_days(ctx: Ctx, default_days: int) -> int:
    if ctx.since is None:
        return max(1, default_days)
    delta = datetime.now(UTC) - ctx.since
    return max(1, min(default_days, math.ceil(delta.total_seconds() / 86400) + 1))


def _https_endpoint(value: Any) -> list[str]:
    text = str(value or "").strip()
    return [text] if text else []


# --- 1. Atlassian (sooperset/mcp-atlassian) ---------------------------------------------------------------


ATLASSIAN_TOOLS = ("confluence_search", "confluence_get_page", "jira_search", "jira_get_issue")
JIRA_FIELDS = "summary,description,status,issuetype,priority,assignee,reporter,labels,created,updated,comment"


def _atlassian_env(config: dict[str, Any], secrets: dict[str, str]) -> dict[str, str]:
    token = secrets.get("api_token", "")
    datacenter = config.get("deployment") == "datacenter"
    env = {"READ_ONLY_MODE": "true", "ENABLED_TOOLS": ",".join(ATLASSIAN_TOOLS), "MCP_VERBOSE": "false"}
    if config.get("confluence_url"):
        env["CONFLUENCE_URL"] = str(config["confluence_url"])
        if datacenter:
            env["CONFLUENCE_PERSONAL_TOKEN"] = token
        else:
            env["CONFLUENCE_USERNAME"] = str(config.get("username") or "")
            env["CONFLUENCE_API_TOKEN"] = token
    if config.get("jira_url"):
        env["JIRA_URL"] = str(config["jira_url"])
        if datacenter:
            env["JIRA_PERSONAL_TOKEN"] = token
        else:
            env["JIRA_USERNAME"] = str(config.get("username") or "")
            env["JIRA_API_TOKEN"] = token
    return env


def _atlassian_validate(config: dict[str, Any], require_scope: bool) -> None:
    if not config.get("confluence_url") and not config.get("jira_url"):
        raise ValueError("Renseignez l'URL Confluence et/ou l'URL Jira")
    if config.get("deployment") != "datacenter" and not config.get("username"):
        raise ValueError("Champ requis : E-mail du compte (Atlassian Cloud)")
    if require_scope:
        if config.get("confluence_url") and not config.get("space_keys"):
            raise ValueError("Choisissez au moins un espace Confluence")
        if config.get("jira_url") and not config.get("jql"):
            raise ValueError("Champ requis : Requête JQL")


def _cql(ctx: Ctx) -> str:
    clauses = [f"type = page AND space = {_quote(str(ctx.item))}"]
    since = ctx.page or ctx.since
    if isinstance(since, datetime):
        clauses.append(f"lastmodified >= {_quote(since.astimezone(UTC).strftime('%Y-%m-%d %H:%M'))}")
    return " AND ".join(clauses) + " ORDER BY lastmodified ASC"


def _confluence_next(payload: Any, items: list[dict[str, Any]], ctx: Ctx) -> list[Any]:
    """Keyset pagination on ``lastmodified`` (the tool has no offset): continue after the newest page."""
    if len(items) < 50:
        return []
    newest = max((as_datetime(first(i, "updated", "last_modified")) for i in items), default=None, key=lambda d: d or datetime.min.replace(tzinfo=UTC))
    seen = ctx.state.setdefault("seen_pages", set())
    fresh = {str(i.get("id")) for i in items} - seen
    seen.update(str(i.get("id")) for i in items)
    if not newest or not fresh:
        return []
    return [newest]


def _map_confluence(item: dict[str, Any], page: Any, ctx: Ctx) -> Record | None:
    meta = page.get("metadata") if isinstance(page, dict) and isinstance(page.get("metadata"), dict) else page
    meta = meta if isinstance(meta, dict) else {}
    content = text_of(first(meta, "content.value", "content")) or text_of(dig(page, "content.value"))
    if not content and isinstance(page, str):
        content = page
    title = text_of(first(meta, "title") or item.get("title")) or f"Page {item.get('id')}"
    return Record(
        external_id=str(item.get("id")),
        title=title,
        content=markdown_sections(title, [("Espace", first(meta, "space.name", "space.key") or ctx.item)], content),
        uri=text_of(first(meta, "url") or item.get("url")) or None,
        author=text_of(first(meta, "author", "version.by") or item.get("author")) or None,
        updated_at=as_datetime(first(meta, "updated", "last_modified") or item.get("updated")),
        source_kind="document",
        metadata={"space": ctx.item, "version": first(meta, "version.number", "version"), "kind": "confluence_page"},
    )


def _jql(ctx: Ctx) -> str:
    base = str(ctx.config.get("jql") or "").strip()
    base = re.sub(r"(?i)\s+order\s+by\s+.*$", "", base)
    if ctx.since:
        since = ctx.since.astimezone(UTC).strftime("%Y/%m/%d %H:%M")
        base = f"({base}) AND updated >= {_quote(since)}" if base else f"updated >= {_quote(since)}"
    return f"{base} ORDER BY updated ASC"


def _map_jira(item: dict[str, Any], _: Any, ctx: Ctx) -> Record | None:
    key = text_of(item.get("key")) or text_of(item.get("id"))
    if not key:
        return None
    fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
    data = {**fields, **item}
    summary = text_of(data.get("summary"))
    comments = data.get("comments") or dig(data, "comment.comments") or []
    title = f"{key} — {summary}" if summary else key
    body = text_of(data.get("description"))
    return Record(
        external_id=key,
        title=title,
        content=markdown_sections(
            title,
            [
                ("Statut", data.get("status")),
                ("Type", first(data, "issue_type", "issuetype")),
                ("Priorité", data.get("priority")),
                ("Assigné à", data.get("assignee")),
                ("Rapporteur", data.get("reporter")),
                ("Étiquettes", data.get("labels")),
            ],
            body,
            comments_markdown(comments if isinstance(comments, list) else []),
        ),
        uri=text_of(first(data, "url", "browse_url")) or None,
        author=text_of(first(data, "reporter", "creator")) or None,
        updated_at=as_datetime(first(data, "updated", "updated_at")),
        source_kind="ticket",
        metadata={"kind": "jira_issue", "status": text_of(data.get("status")) or None},
    )


ATLASSIAN = Preset(
    id="atlassian",
    label="Confluence & Jira",
    vendor="Atlassian · mcp-atlassian",
    description="Pages Confluence et tickets Jira via le serveur MCP mcp-atlassian (Cloud ou Data Center).",
    icon="atlassian",
    source_kind="document",
    transport="stdio",
    command="mcp-atlassian",
    fallback=("uvx", "mcp-atlassian==0.23.1"),
    version="mcp-atlassian 0.23.1",
    env=_atlassian_env,
    validate=_atlassian_validate,
    endpoints=lambda config: _https_endpoint(config.get("confluence_url")) + _https_endpoint(config.get("jira_url")),
    required_tools=ATLASSIAN_TOOLS,
    probe=lambda config: (
        ("confluence_search", {"query": "type = page", "limit": 1})
        if config.get("confluence_url")
        else ("jira_search", {"jql": str(config.get("jql") or "order by updated DESC"), "limit": 1, "fields": "summary"})
    ),
    docs_url="https://github.com/sooperset/mcp-atlassian",
    credentials_help=(
        "Cloud : créez un jeton d'API sur id.atlassian.com → Sécurité → Jetons d'API (compte de service en lecture). "
        "Data Center : jeton d'accès personnel (PAT) depuis le profil utilisateur."
    ),
    fields=(
        PresetField("api_token", "Jeton d'API Atlassian (ou PAT Data Center)", "secret", "password", True),
        PresetField(
            "deployment",
            "Déploiement",
            "connection",
            "select",
            default="cloud",
            options=(("cloud", "Atlassian Cloud"), ("datacenter", "Data Center / Server")),
        ),
        PresetField("confluence_url", "URL Confluence", "connection", "url", placeholder="https://exemple.atlassian.net/wiki"),
        PresetField("jira_url", "URL Jira", "connection", "url", placeholder="https://exemple.atlassian.net"),
        PresetField(
            "username", "E-mail du compte (Cloud)", "connection", placeholder="robot-orbit@exemple.fr", visible_if="deployment=cloud"
        ),
        PresetField("space_keys", "Espaces Confluence (clés)", "scope", "list", placeholder="ORB, ARCHI", help="Clés des espaces à synchroniser"),
        PresetField("jql", "Requête JQL (tickets Jira)", "scope", placeholder="project = ORB", help="Le tri est ajouté par ORBIT"),
    ),
    streams=(
        Stream(
            key="confluence",
            label="Pages Confluence",
            list_tool="confluence_search",
            list_args=lambda ctx: {"query": _cql(ctx), "limit": 50},
            items=lambda payload, ctx: find_list(payload),
            next_pages=_confluence_next,
            item_id=lambda item, ctx: str(item.get("id") or "") or None,
            item_updated=lambda item: as_datetime(first(item, "updated", "last_modified")),
            read_tool="confluence_get_page",
            read_args=lambda item, ctx: {"page_id": str(item.get("id")), "convert_to_markdown": True, "include_metadata": True},
            map=_map_confluence,
            foreach="space_keys",
            enabled=lambda config: bool(config.get("confluence_url")),
            incremental="filter",
        ),
        Stream(
            key="jira",
            label="Tickets Jira",
            list_tool="jira_search",
            list_args=lambda ctx: {"jql": _jql(ctx), "fields": JIRA_FIELDS, "limit": 50, "start_at": int(ctx.page or 0)},
            next_pages=_offset_pages(50),
            item_id=lambda item, ctx: text_of(item.get("key")) or None,
            item_updated=lambda item: as_datetime(first(item, "updated", "fields.updated")),
            map=_map_jira,
            enabled=lambda config: bool(config.get("jira_url")),
            incremental="filter",
        ),
    ),
    suggested_task="Résumer les décisions, contraintes et tickets ouverts documentés dans Confluence et Jira",
)


# --- 2. Microsoft 365 (Softeria/ms-365-mcp-server) -----------------------------------------------------


def _ms365_file_ok(item: dict[str, Any]) -> bool:
    from app.ingestion.extractors import detect_mime_type, is_supported

    if not isinstance(item.get("file"), dict) or item.get("deleted"):
        return False
    name = str(item.get("name") or "")
    return is_supported(detect_mime_type(name, dig(item, "file.mimeType")))


def _map_ms365_file(item: dict[str, Any], result: Any, ctx: Ctx) -> Record | None:
    name = str(item.get("name") or item.get("id"))
    meta = {
        "kind": "sharepoint_file",
        "drive_id": ctx.item,
        "size": item.get("size"),
        "etag": item.get("eTag"),
    }
    if item.get("deleted"):
        return Record(external_id=str(item.get("id")), title=name, deleted=True)
    data: bytes | None = None
    body = ctx.result
    blobs = resource_blobs(body) if body is not None else []
    if blobs:
        data = blobs[0][2]
    elif isinstance(result, dict) and result.get("contentBytes"):
        import base64

        try:
            data = base64.b64decode(str(result["contentBytes"]))
        except ValueError:
            data = None
    if data is None:
        return None
    return Record(
        external_id=str(item.get("id")),
        title=name,
        data=data,
        filename=name,
        mime_type=str(dig(item, "file.mimeType") or (result or {}).get("contentType") or "application/octet-stream")
        if isinstance(result, dict) or result is None
        else "application/octet-stream",
        uri=text_of(item.get("webUrl")) or None,
        author=text_of(first(item, "lastModifiedBy.user.displayName", "createdBy.user.displayName")) or None,
        updated_at=as_datetime(item.get("lastModifiedDateTime")),
        metadata=meta,
    )


def _graph_next(payload: Any, items: list[dict[str, Any]], ctx: Ctx) -> list[Any]:
    link = first(payload, "@odata.nextLink", "nextLink") if isinstance(payload, dict) else None
    if isinstance(link, str):
        match = re.search(r"[$]?skiptoken=([^&]+)", link)
        if match and match.group(1) != ctx.page:
            return [match.group(1)]
    return []


def _map_mail(item: dict[str, Any], full: Any, ctx: Ctx) -> Record | None:
    data = full if isinstance(full, dict) and full.get("id") else item
    subject = text_of(data.get("subject")) or "(sans objet)"
    body = data.get("body") if isinstance(data.get("body"), dict) else {}
    html = str(body.get("contentType", "")).lower() == "html"
    sender = text_of(first(data, "from.emailAddress.name", "from.emailAddress.address"))
    content = text_of(body.get("content")) or text_of(data.get("bodyPreview"))
    if html:
        content = f"<h1>{subject}</h1><p><b>De :</b> {sender}</p>{content}"
    else:
        content = markdown_sections(subject, [("De", sender), ("Reçu le", data.get("receivedDateTime"))], content)
    return Record(
        external_id=str(data.get("id")),
        title=subject,
        content=content,
        mime_type="text/html" if html else "text/markdown",
        uri=text_of(data.get("webLink")) or None,
        author=sender or None,
        updated_at=as_datetime(first(data, "lastModifiedDateTime", "receivedDateTime")),
        source_kind="note",
        metadata={"kind": "outlook_mail"},
    )


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", value)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"&nbsp;", " ", text).strip()


def _map_teams_message(item: dict[str, Any], _: Any, ctx: Ctx) -> Record | None:
    if item.get("messageType") not in (None, "message") or item.get("deletedDateTime"):
        return None
    content = text_of(dig(item, "body.content"))
    if str(dig(item, "body.contentType") or "").lower() == "html":
        content = _html_to_text(content)
    if not content.strip():
        return None
    return Record(
        external_id=str(item.get("id")),
        title=text_of(item.get("subject")) or "Message Teams",
        content=content,
        uri=text_of(item.get("webUrl")) or None,
        author=text_of(first(item, "from.user.displayName", "from.application.displayName")) or None,
        updated_at=as_datetime(first(item, "lastModifiedDateTime", "createdDateTime")),
        source_kind="feedback",
    )


def _teams_args(ctx: Ctx) -> dict[str, Any]:
    team, _, channel = str(ctx.item or "").partition("/")
    return _drop_empty({"teamId": team, "channelId": channel, "top": 50, "skiptoken": ctx.page})


MS365 = Preset(
    id="ms365",
    label="Microsoft 365",
    vendor="Microsoft · ms-365-mcp-server",
    description="Fichiers SharePoint/OneDrive, e-mails Outlook et messages Teams via le serveur MCP Softeria (lecture seule).",
    icon="microsoft",
    source_kind="document",
    transport="stdio",
    command="ms-365-mcp-server",
    fallback=("npx", "-y", "@softeria/ms-365-mcp-server@0.158.0"),
    version="@softeria/ms-365-mcp-server 0.158.0",
    args=lambda config: ["--read-only", "--org-mode"],
    env=lambda config, secrets: {"MS365_MCP_OAUTH_TOKEN": secrets.get("access_token", ""), "LOG_LEVEL": "warn"},
    required_tools=("get-drive-delta", "download-bytes", "list-mail-messages", "list-channel-messages"),
    probe=lambda config: (
        ("get-drive-root-item", {"driveId": _list(config, "drive_ids")[0]}) if _list(config, "drive_ids") else None
    ),
    validate=lambda config, require_scope: (
        None
        if not require_scope or config.get("drive_ids") or config.get("channels") or _bool(config, "include_mail")
        else (_ for _ in ()).throw(ValueError("Choisissez au moins un drive, un canal Teams ou la messagerie"))
    ),
    docs_url="https://github.com/Softeria/ms-365-mcp-server",
    credentials_help=(
        "Mode « Bring Your Own Token » : jeton d'accès Microsoft Graph délégué (Files.Read.All, Mail.Read, "
        "ChannelMessage.Read.All) obtenu par votre application Entra ID. Il expire (~1 h) : pour une synchronisation "
        "planifiée durable, préférez le connecteur SharePoint natif (client credentials)."
    ),
    fields=(
        PresetField("access_token", "Jeton d'accès Microsoft Graph", "secret", "password", True),
        PresetField("drive_ids", "Drives / bibliothèques (ID Graph)", "scope", "list", placeholder="b!AbC…", help="ID des drives SharePoint/OneDrive"),
        PresetField("include_mail", "Inclure les e-mails Outlook", "scope", "bool", default=False),
        PresetField("mail_search", "Recherche e-mail (KQL)", "scope", placeholder="subject:ORBIT", visible_if="include_mail=true"),
        PresetField("channels", "Canaux Teams (teamId/channelId)", "scope", "list", placeholder="team-id/19:abc@thread.tacv2"),
    ),
    streams=(
        Stream(
            key="files",
            label="Fichiers SharePoint/OneDrive",
            list_tool="get-drive-delta",
            list_args=lambda ctx: _drop_empty({"driveId": ctx.item, "driveItemId": "root", "skiptoken": ctx.page}),
            items=lambda payload, ctx: [i for i in find_list(payload, "value") if isinstance(i.get("file"), dict) or i.get("deleted")],
            next_pages=_graph_next,
            item_id=lambda item, ctx: str(item.get("id") or "") or None,
            item_updated=lambda item: as_datetime(item.get("lastModifiedDateTime")),
            read_tool="download-bytes",
            read_args=lambda item, ctx: {"target": f"/drives/{ctx.item}/items/{item.get('id')}/content"},
            map=_map_ms365_file,
            foreach="drive_ids",
            incremental="skip",
            full_listing=True,
        ),
        Stream(
            key="mail",
            label="E-mails Outlook",
            list_tool="list-mail-messages",
            list_args=lambda ctx: _drop_empty(
                {
                    "top": 50,
                    "skip": int(ctx.page or 0) or None,
                    "search": ctx.config.get("mail_search") or None,
                    "filter": None
                    if ctx.config.get("mail_search") or not ctx.since
                    else f"receivedDateTime ge {_iso(ctx.since)}",
                    "select": ["id", "subject", "from", "receivedDateTime", "lastModifiedDateTime", "body", "webLink"],
                }
            ),
            next_pages=lambda payload, items, ctx: [int(ctx.page or 0) + len(items)] if len(items) >= 50 else [],
            item_id=lambda item, ctx: str(item.get("id") or "") or None,
            item_updated=lambda item: as_datetime(first(item, "lastModifiedDateTime", "receivedDateTime")),
            map=_map_mail,
            enabled=lambda config: _bool(config, "include_mail"),
            incremental="skip",
        ),
        Stream(
            key="teams",
            label="Messages Teams",
            list_tool="list-channel-messages",
            list_args=_teams_args,
            next_pages=_graph_next,
            item_id=lambda item, ctx: str(item.get("id") or "") or None,
            item_updated=lambda item: as_datetime(first(item, "lastModifiedDateTime", "createdDateTime")),
            map=_map_teams_message,
            foreach="channels",
            incremental="none",
            aggregate=_day_groups("teams_channel", lambda ctx, day: f"Teams {ctx.item} — {day}"),
            day_cursor=True,
        ),
    ),
)


# --- 3. Google Workspace (taylorwilsdon/google_workspace_mcp) ------------------------------------------


GOOGLE_FOLDER = "application/vnd.google-apps.folder"


def _drive_query(ctx: Ctx) -> str:
    clauses = ["trashed = false", f"mimeType != {_quote(GOOGLE_FOLDER)}".replace('"', "'")]
    if ctx.item and ctx.item != "*":
        clauses.append(f"'{ctx.item}' in parents")
    extra = str(ctx.config.get("drive_query") or "").strip()
    if extra:
        clauses.append(f"({extra})")
    if ctx.since:
        clauses.append(f"modifiedTime > '{_iso(ctx.since)}'")
    return " and ".join(clauses)


def _drive_items(payload: Any, ctx: Ctx) -> list[dict[str, Any]]:
    if isinstance(payload, (dict, list)):
        items = find_list(payload, "files")
        ctx.state["next_token"] = first(payload, "nextPageToken", "next_page_token") if isinstance(payload, dict) else None
    else:
        items, ctx.state["next_token"] = drive_lines(str(payload or ""))
    return [i for i in items if i.get("mimeType") != GOOGLE_FOLDER]


def _map_drive(item: dict[str, Any], content: Any, ctx: Ctx) -> Record | None:
    text = strip_preamble(content if isinstance(content, str) else result_text(ctx.result))
    if not text:
        return None
    name = str(item.get("name") or item.get("id"))
    return Record(
        external_id=str(item.get("id")),
        title=name,
        content=text,
        uri=text_of(item.get("webViewLink")) or None,
        updated_at=as_datetime(item.get("modifiedTime")),
        metadata={"kind": "google_drive_file", "mime": item.get("mimeType"), "folder": ctx.item},
    )


_GMAIL_ID = re.compile(r"(?:Message ID|ID)\s*[:=]\s*([A-Za-z0-9_-]{8,})")


def _gmail_items(payload: Any, ctx: Ctx) -> list[dict[str, Any]]:
    if isinstance(payload, (dict, list)):
        items = find_list(payload, "messages")
        ctx.state["next_token"] = first(payload, "nextPageToken") if isinstance(payload, dict) else None
        return items
    text = str(payload or "")
    token = re.search(r"(?i)next\s*page\s*token\s*[:=]\s*(\S+)", text)
    ctx.state["next_token"] = token.group(1) if token else None
    return [{"id": mid} for mid in dict.fromkeys(_GMAIL_ID.findall(text))]


def _map_gmail(item: dict[str, Any], content: Any, ctx: Ctx) -> Record | None:
    text = content if isinstance(content, str) else result_text(ctx.result)
    if not text.strip():
        return None
    subject = re.search(r"(?im)^Subject:\s*(.+)$", text)
    sender = re.search(r"(?im)^From:\s*(.+)$", text)
    date = re.search(r"(?im)^Date:\s*(.+)$", text)
    when = None
    if date:
        from email.utils import parsedate_to_datetime

        try:
            when = parsedate_to_datetime(date.group(1).strip())
        except (TypeError, ValueError):
            when = as_datetime(date.group(1).strip())
    return Record(
        external_id=str(item.get("id")),
        title=subject.group(1).strip() if subject else f"E-mail {item.get('id')}",
        content=text.strip(),
        author=sender.group(1).strip() if sender else None,
        updated_at=when,
        source_kind="note",
        metadata={"kind": "gmail_message"},
    )


GOOGLE = Preset(
    id="google_workspace",
    label="Google Workspace",
    vendor="Google · workspace-mcp",
    description="Fichiers Google Drive, Docs et Sheets (et Gmail en option) via le serveur MCP workspace-mcp, compte de service.",
    icon="google",
    source_kind="document",
    transport="stdio",
    command="workspace-mcp",
    fallback=("uvx", "workspace-mcp==2.0.1"),
    version="workspace-mcp 2.0.1",
    args=lambda config: [
        "--tools",
        "drive",
        "docs",
        "sheets",
        *(["gmail"] if _bool(config, "include_gmail") else []),
        "--read-only",
    ],
    env=lambda config, secrets: {
        "GOOGLE_SERVICE_ACCOUNT_KEY_JSON": secrets.get("service_account_json", ""),
        "USER_GOOGLE_EMAIL": str(config.get("user_email") or ""),
        "WORKSPACE_MCP_LOG_LEVEL": "WARNING",
    },
    required_tools=("search_drive_files", "get_drive_file_content"),
    probe=lambda config: (
        "search_drive_files",
        {"user_google_email": str(config.get("user_email") or ""), "query": "trashed = false", "page_size": 1},
    ),
    validate=lambda config, require_scope: (
        None if config.get("user_email") else (_ for _ in ()).throw(ValueError("Champ requis : Utilisateur Google à impersonner"))
    ),
    docs_url="https://github.com/taylorwilsdon/google_workspace_mcp",
    credentials_help=(
        "Console Google Cloud : créez un compte de service, une clé JSON, puis dans la console d'administration "
        "Workspace accordez la délégation au niveau du domaine (scopes drive.readonly, documents.readonly, "
        "spreadsheets.readonly, gmail.readonly)."
    ),
    fields=(
        PresetField("service_account_json", "Clé JSON du compte de service", "secret", "textarea", True, placeholder='{"type": "service_account", …}'),
        PresetField("user_email", "Utilisateur Google à impersonner", "connection", required=True, placeholder="robot-orbit@exemple.fr"),
        PresetField("folder_ids", "Dossiers Drive (ID)", "scope", "list", help="Vide = tous les fichiers accessibles"),
        PresetField("drive_query", "Filtre Drive (syntaxe q)", "scope", placeholder="name contains 'ADR'"),
        PresetField("include_gmail", "Inclure Gmail", "scope", "bool", default=False),
        PresetField("gmail_query", "Recherche Gmail", "scope", placeholder="label:orbit newer_than:30d", visible_if="include_gmail=true"),
    ),
    streams=(
        Stream(
            key="drive",
            label="Fichiers Drive",
            list_tool="search_drive_files",
            list_args=lambda ctx: _drop_empty(
                {
                    "user_google_email": str(ctx.config.get("user_email") or ""),
                    "query": _drive_query(ctx),
                    "page_size": 50,
                    "page_token": ctx.page,
                }
            ),
            items=_drive_items,
            next_pages=lambda payload, items, ctx: [ctx.state["next_token"]] if ctx.state.get("next_token") else [],
            item_id=lambda item, ctx: str(item.get("id") or "") or None,
            item_updated=lambda item: as_datetime(item.get("modifiedTime")),
            read_tool="get_drive_file_content",
            read_args=lambda item, ctx: {"user_google_email": str(ctx.config.get("user_email") or ""), "file_id": str(item.get("id"))},
            map=_map_drive,
            foreach="folder_ids",
            incremental="filter",
        ),
        Stream(
            key="gmail",
            label="E-mails Gmail",
            list_tool="search_gmail_messages",
            list_args=lambda ctx: _drop_empty(
                {
                    "query": " ".join(
                        p
                        for p in (
                            str(ctx.config.get("gmail_query") or ""),
                            f"after:{int(ctx.since.timestamp())}" if ctx.since else "",
                        )
                        if p
                    )
                    or "newer_than:30d",
                    "user_google_email": str(ctx.config.get("user_email") or ""),
                    "page_size": 25,
                    "page_token": ctx.page,
                }
            ),
            items=_gmail_items,
            next_pages=lambda payload, items, ctx: [ctx.state["next_token"]] if ctx.state.get("next_token") else [],
            item_id=lambda item, ctx: str(item.get("id") or "") or None,
            read_tool="get_gmail_message_content",
            read_args=lambda item, ctx: {"message_id": str(item.get("id")), "user_google_email": str(ctx.config.get("user_email") or "")},
            map=_map_gmail,
            enabled=lambda config: _bool(config, "include_gmail"),
            incremental="filter",
        ),
    ),
)


# --- 4. Slack (korotovsky/slack-mcp-server) ----------------------------------------------------------------


def _slack_env(config: dict[str, Any], secrets: dict[str, str]) -> dict[str, str]:
    token = secrets.get("token", "")
    env = {
        "SLACK_MCP_ENABLED_TOOLS": "conversations_history,conversations_replies,channels_list",
        "SLACK_MCP_LOG_LEVEL": "warn",
    }
    env["SLACK_MCP_XOXB_TOKEN" if token.startswith("xoxb-") else "SLACK_MCP_XOXP_TOKEN"] = token
    return env


def _slack_items(payload: Any, ctx: Ctx) -> list[dict[str, Any]]:
    rows = find_list(payload) if isinstance(payload, (dict, list)) else csv_rows(str(payload or ""))
    ctx.state["next_cursor"] = next((r.get("cursor") for r in reversed(rows) if r.get("cursor")), None)
    return [r for r in rows if first(r, "msgid", "ts", "msgID") and first(r, "text")]


def _slack_time(item: dict[str, Any]) -> datetime | None:
    return as_datetime(first(item, "time", "msgid", "ts", "msgID"))


def _map_slack(item: dict[str, Any], replies: Any, ctx: Ctx) -> Record | None:
    text = text_of(item.get("text"))
    if not text.strip():
        return None
    thread: list[str] = []
    if replies is not None:
        rows = find_list(replies) if isinstance(replies, (dict, list)) else csv_rows(str(replies))
        for row in rows:
            if first(row, "msgid", "ts") == first(item, "msgid", "ts"):
                continue
            who = text_of(first(row, "realname", "username", "userName")) or "?"
            thread.append(f"**{who}** : {text_of(row.get('text'))}")
    return Record(
        external_id=str(first(item, "msgid", "ts")),
        title="Message Slack",
        content=text,
        author=text_of(first(item, "realname", "username", "userName")) or None,
        updated_at=_slack_time(item),
        source_kind="feedback",
        metadata={"replies": thread[:50]},
    )


SLACK = Preset(
    id="slack",
    label="Slack",
    vendor="Slack · slack-mcp-server",
    description="Historique et fils de discussion des canaux Slack choisis (un document par canal et par jour).",
    icon="slack",
    source_kind="feedback",
    transport="stdio",
    command="slack-mcp-server",
    fallback=("npx", "-y", "slack-mcp-server@1.3.0"),
    version="slack-mcp-server 1.3.0",
    args=lambda config: ["--transport", "stdio"],
    env=_slack_env,
    required_tools=("conversations_history", "conversations_replies"),
    probe=lambda config: ("channels_list", {"channel_types": "public_channel", "limit": 20}),
    validate=lambda config, require_scope: (
        None if not require_scope or config.get("channels") else (_ for _ in ()).throw(ValueError("Choisissez au moins un canal Slack"))
    ),
    docs_url="https://github.com/korotovsky/slack-mcp-server",
    credentials_help=(
        "api.slack.com/apps → votre application → OAuth & Permissions : jeton utilisateur (xoxp-) ou bot (xoxb-, "
        "canaux où le bot est invité) avec channels:history, groups:history, channels:read, users:read."
    ),
    fields=(
        PresetField("token", "Jeton Slack (xoxp-… ou xoxb-…)", "secret", "password", True),
        PresetField("channels", "Canaux", "scope", "list", placeholder="#projet-orbit, C0123456789"),
        PresetField("history_days", "Historique initial (jours)", "scope", "number", default=30),
        PresetField("include_threads", "Inclure les fils de discussion", "scope", "bool", default=True),
    ),
    streams=(
        Stream(
            key="slack",
            label="Messages Slack",
            list_tool="conversations_history",
            list_args=lambda ctx: _drop_empty(
                {
                    "channel_id": ctx.item,
                    "include_activity_messages": False,
                    "cursor": ctx.page,
                    "limit": None if ctx.page else f"{_since_days(ctx, int(ctx.config.get('history_days') or 30))}d",
                }
            ),
            items=_slack_items,
            next_pages=lambda payload, items, ctx: [ctx.state["next_cursor"]]
            if ctx.state.get("next_cursor") and ctx.state.get("next_cursor") != ctx.page
            else [],
            item_id=lambda item, ctx: str(first(item, "msgid", "ts") or "") or None,
            item_updated=_slack_time,
            read_tool="conversations_replies",
            read_args=lambda item, ctx: (
                {"channel_id": ctx.item, "thread_ts": str(first(item, "msgid", "ts"))}
                if _bool(ctx.config, "include_threads", True)
                and first(item, "threadts", "thread_ts")
                and first(item, "threadts", "thread_ts") == first(item, "msgid", "ts")
                else {}
            ),
            map=_map_slack,
            foreach="channels",
            incremental="filter",
            aggregate=_day_groups("slack_channel", lambda ctx, day: f"Slack {ctx.item} — {day}"),
            day_cursor=True,
        ),
    ),
    suggested_task="Synthétiser les échanges récents des canaux Slack : décisions, questions ouvertes et irritants",
)


# --- 5. GitHub (github/github-mcp-server) -------------------------------------------------------------


GITHUB_TOOLSETS = "repos,issues,pull_requests,discussions"
GITHUB_REMOTE_URL = "https://api.githubcopilot.com/mcp/"


def _repo(ctx: Ctx) -> tuple[str, str]:
    owner, _, name = str(ctx.item or "").partition("/")
    return owner, name


def _map_issue_like(kind: str) -> Callable[[dict[str, Any], Any, Ctx], Record | None]:
    def mapper(item: dict[str, Any], extra: Any, ctx: Ctx) -> Record | None:
        number = first(item, "number")
        if number is None:
            return None
        title = f"{ctx.item}#{number} — {text_of(item.get('title'))}"
        comments: list[dict[str, Any]] = []
        body = text_of(item.get("body"))
        if isinstance(extra, dict) and extra.get("body") and not body:
            body = text_of(extra.get("body"))
        if extra is not None:
            comments = find_list(extra, "comments")
        labels = [text_of(label) for label in (item.get("labels") or []) if text_of(label)]
        return Record(
            external_id=f"{ctx.item}#{number}",
            title=title,
            content=markdown_sections(
                title,
                [
                    ("État", first(item, "state", "closed")),
                    ("Auteur", first(item, "user.login", "author.login", "user", "author")),
                    ("Étiquettes", labels),
                    ("Catégorie", first(item, "category.name")),
                ],
                body,
                comments_markdown(comments),
            ),
            uri=text_of(first(item, "html_url", "url")) or None,
            author=text_of(first(item, "user.login", "author.login", "user", "author")) or None,
            updated_at=as_datetime(first(item, "updated_at", "updatedAt")),
            source_kind="ticket" if kind != "discussion" else "feedback",
            metadata={"kind": f"github_{kind}", "repo": ctx.item, "state": text_of(item.get("state")) or None},
        )

    return mapper


def _docs_items(payload: Any, ctx: Ctx) -> list[dict[str, Any]]:
    entries = payload if isinstance(payload, list) else find_list(payload, "entries", "contents")
    out: list[dict[str, Any]] = []
    if entries:
        for entry in entries:
            path = str(entry.get("path") or entry.get("name") or "")
            if entry.get("type") == "dir":
                if ctx.state.get("depth", 0) < 2:
                    ctx.state.setdefault("dirs", []).append(path)
                continue
            if PurePosixPath(path).suffix.lower() in (".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc"):
                out.append({"path": path, "sha": entry.get("sha"), "html_url": entry.get("html_url")})
        return out
    texts = resource_texts(ctx.result)
    if texts:  # the configured path is a file
        return [{"path": str(ctx.page or ""), "_inline": texts[0][2]}]
    return []


def _docs_pages(payload: Any, items: list[dict[str, Any]], ctx: Ctx) -> list[Any]:
    dirs = ctx.state.pop("dirs", [])
    ctx.state["depth"] = ctx.state.get("depth", 0) + 1
    return dirs


def _map_doc(item: dict[str, Any], content: Any, ctx: Ctx) -> Record | None:
    text = item.get("_inline")
    if text is None:
        texts = resource_texts(ctx.result)
        text = texts[0][2] if texts else (content if isinstance(content, str) else "")
    if not str(text).strip():
        return None
    path = str(item.get("path"))
    return Record(
        external_id=f"{ctx.item}:{path}",
        title=f"{ctx.item} — {path}",
        content=str(text),
        uri=text_of(item.get("html_url")) or f"https://github.com/{ctx.item}/blob/HEAD/{path}",
        source_kind="document",
        metadata={"kind": "github_file", "repo": ctx.item, "path": path, "sha": item.get("sha")},
    )


def _github_validate(config: dict[str, Any], require_scope: bool) -> None:
    for repo in _list(config, "repos"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError(f"Dépôt invalide : {repo} (format attendu : owner/nom)")
    if require_scope and not config.get("repos"):
        raise ValueError("Choisissez au moins un dépôt GitHub (owner/nom)")


GITHUB = Preset(
    id="github",
    label="GitHub",
    vendor="GitHub · github-mcp-server",
    description="Issues, pull requests, discussions et documentation (README, docs/) des dépôts choisis via le serveur MCP officiel.",
    icon="github",
    source_kind="ticket",
    transport="http",
    transport_for=lambda config: "stdio" if config.get("transport") == "local" else "http",
    command="github-mcp-server",
    args=lambda config: ["stdio", "--read-only", "--toolsets", GITHUB_TOOLSETS],
    env=lambda config, secrets: {"GITHUB_PERSONAL_ACCESS_TOKEN": secrets.get("token", "")},
    url=lambda config: GITHUB_REMOTE_URL,
    headers=lambda config, secrets: {
        "Authorization": f"Bearer {secrets.get('token', '')}",
        "X-MCP-Toolsets": GITHUB_TOOLSETS,
        "X-MCP-Readonly": "true",
    },
    version="github-mcp-server v1.14.0 (binaire) / serveur distant api.githubcopilot.com",
    required_tools=("list_issues", "issue_read", "list_pull_requests", "get_file_contents"),
    probe=lambda config: (
        ("get_file_contents", {"owner": _list(config, "repos")[0].split("/")[0], "repo": _list(config, "repos")[0].split("/")[1], "path": "/"})
        if _list(config, "repos")
        else None
    ),
    validate=_github_validate,
    docs_url="https://github.com/github/github-mcp-server",
    credentials_help=(
        "github.com → Settings → Developer settings → Fine-grained tokens : accès en lecture seule aux dépôts "
        "choisis (Contents, Issues, Pull requests, Discussions : Read-only)."
    ),
    fields=(
        PresetField("token", "Jeton GitHub (fine-grained, lecture seule)", "secret", "password", True),
        PresetField(
            "transport",
            "Serveur MCP",
            "connection",
            "select",
            default="remote",
            options=(("remote", "Distant (api.githubcopilot.com)"), ("local", "Local (binaire dans le conteneur ORBIT)")),
        ),
        PresetField("repos", "Dépôts (owner/nom)", "scope", "list", True, placeholder="exemple/orbit"),
        PresetField("include_issues", "Issues", "scope", "bool", default=True),
        PresetField("include_pulls", "Pull requests", "scope", "bool", default=True),
        PresetField("include_discussions", "Discussions", "scope", "bool", default=False),
        PresetField("docs_paths", "Documentation (fichiers ou dossiers)", "scope", "list", default=["README.md", "docs"]),
    ),
    streams=(
        Stream(
            key="issues",
            label="Issues",
            list_tool="list_issues",
            list_args=lambda ctx: _drop_empty(
                {
                    "owner": _repo(ctx)[0],
                    "repo": _repo(ctx)[1],
                    "since": _iso(ctx.since),
                    "orderBy": "UPDATED_AT",
                    "direction": "ASC",
                    "perPage": 50,
                    "after": ctx.page,
                }
            ),
            items=lambda payload, ctx: find_list(payload, "issues"),
            next_pages=_graphql_pages,
            item_id=lambda item, ctx: str(item.get("number") or "") or None,
            item_updated=lambda item: as_datetime(first(item, "updated_at", "updatedAt")),
            read_tool="issue_read",
            read_args=lambda item, ctx: {
                "method": "get_comments",
                "owner": _repo(ctx)[0],
                "repo": _repo(ctx)[1],
                "issue_number": int(item.get("number") or 0),
            },
            map=_map_issue_like("issue"),
            foreach="repos",
            enabled=lambda config: _bool(config, "include_issues", True),
            incremental="filter",
        ),
        Stream(
            key="pulls",
            label="Pull requests",
            list_tool="list_pull_requests",
            list_args=lambda ctx: {
                "owner": _repo(ctx)[0],
                "repo": _repo(ctx)[1],
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "perPage": 50,
                "page": int(ctx.page or 1),
            },
            items=lambda payload, ctx: find_list(payload, "pull_requests", "pullRequests"),
            next_pages=_page_number_pages(50),
            item_id=lambda item, ctx: str(item.get("number") or "") or None,
            item_updated=lambda item: as_datetime(first(item, "updated_at", "updatedAt")),
            map=_map_issue_like("pull_request"),
            foreach="repos",
            enabled=lambda config: _bool(config, "include_pulls", True),
            incremental="stop",
        ),
        Stream(
            key="discussions",
            label="Discussions",
            list_tool="list_discussions",
            list_args=lambda ctx: _drop_empty(
                {
                    "owner": _repo(ctx)[0],
                    "repo": _repo(ctx)[1],
                    "orderBy": "UPDATED_AT",
                    "direction": "DESC",
                    "perPage": 50,
                    "after": ctx.page,
                }
            ),
            items=lambda payload, ctx: find_list(payload, "discussions"),
            next_pages=_graphql_pages,
            item_id=lambda item, ctx: str(item.get("number") or "") or None,
            item_updated=lambda item: as_datetime(first(item, "updated_at", "updatedAt")),
            read_tool="get_discussion",
            read_args=lambda item, ctx: {
                "owner": _repo(ctx)[0],
                "repo": _repo(ctx)[1],
                "discussionNumber": int(item.get("number") or 0),
            },
            map=_map_issue_like("discussion"),
            foreach="repos",
            enabled=lambda config: _bool(config, "include_discussions"),
            incremental="stop",
        ),
        Stream(
            key="docs",
            label="Documentation",
            list_tool="get_file_contents",
            list_args=lambda ctx: {"owner": _repo(ctx)[0], "repo": _repo(ctx)[1], "path": str(ctx.page or "/")},
            items=_docs_items,
            next_pages=_docs_pages,
            item_id=lambda item, ctx: str(item.get("path") or "") or None,
            read_tool="get_file_contents",
            read_args=lambda item, ctx: (
                {} if item.get("_inline") is not None else {"owner": _repo(ctx)[0], "repo": _repo(ctx)[1], "path": str(item.get("path"))}
            ),
            map=_map_doc,
            foreach="repos",
            enabled=lambda config: bool(_list(config, "docs_paths") or config.get("docs_paths") is None),
            incremental="none",
            full_listing=True,
        ),
    ),
    suggested_task="Faire le point sur les issues et pull requests récentes : décisions, blocages et prochaines étapes",
)


# --- 6. Linear (remote MCP) ----------------------------------------------------------------------------


def _map_linear_issue(item: dict[str, Any], _: Any, ctx: Ctx) -> Record | None:
    ident = text_of(first(item, "identifier", "id"))
    if not ident:
        return None
    title = f"{ident} — {text_of(item.get('title'))}"
    return Record(
        external_id=ident,
        title=title,
        content=markdown_sections(
            title,
            [
                ("Statut", first(item, "status", "state")),
                ("Priorité", first(item, "priorityLabel", "priority")),
                ("Assigné à", first(item, "assignee", "assigneeName")),
                ("Équipe", first(item, "team", "teamName")),
                ("Projet", first(item, "project", "projectName")),
                ("Étiquettes", first(item, "labels")),
            ],
            text_of(first(item, "description", "body")),
        ),
        uri=text_of(item.get("url")) or None,
        author=text_of(first(item, "creator", "createdBy")) or None,
        updated_at=as_datetime(first(item, "updatedAt", "updated_at")),
        source_kind="ticket",
        metadata={"kind": "linear_issue"},
    )


def _map_linear_project(item: dict[str, Any], _: Any, ctx: Ctx) -> Record | None:
    name = text_of(item.get("name"))
    if not name:
        return None
    return Record(
        external_id=str(item.get("id") or name),
        title=f"Projet Linear — {name}",
        content=markdown_sections(
            f"Projet Linear — {name}",
            [("Statut", first(item, "status", "state")), ("Responsable", first(item, "lead")), ("Échéance", first(item, "targetDate"))],
            text_of(first(item, "content", "description", "summary")),
        ),
        uri=text_of(item.get("url")) or None,
        updated_at=as_datetime(first(item, "updatedAt", "updated_at")),
        source_kind="document",
        metadata={"kind": "linear_project"},
    )


LINEAR = Preset(
    id="linear",
    label="Linear",
    vendor="Linear · serveur MCP officiel (distant)",
    description="Tickets et projets Linear via le serveur MCP distant officiel (point d'accès en lecture seule).",
    icon="linear",
    source_kind="ticket",
    transport="http",
    url=lambda config: "https://mcp.linear.app/mcp/readonly",
    headers=lambda config, secrets: {"Authorization": f"Bearer {secrets.get('api_key', '')}"},
    version="serveur distant mcp.linear.app (géré par Linear)",
    required_tools=("list_issues",),
    probe=lambda config: ("list_issues", _drop_empty({"limit": 1, "team": config.get("team")})),
    docs_url="https://linear.app/docs/mcp",
    credentials_help=(
        "Linear → Settings → Security & access → Personal API keys : créez une clé en lecture seule (Read), "
        "idéalement pour un compte de service. Passée en « Authorization: Bearer » au serveur MCP distant."
    ),
    fields=(
        PresetField("api_key", "Clé d'API Linear (lecture seule)", "secret", "password", True),
        PresetField("team", "Équipe (nom ou clé)", "scope", placeholder="ORB", help="Vide = toutes les équipes accessibles"),
        PresetField("project", "Projet (optionnel)", "scope"),
        PresetField("include_projects", "Inclure les projets", "scope", "bool", default=True),
    ),
    streams=(
        Stream(
            key="issues",
            label="Tickets Linear",
            list_tool="list_issues",
            list_args=lambda ctx: _drop_empty(
                {
                    "team": ctx.config.get("team"),
                    "project": ctx.config.get("project"),
                    "updatedAt": _iso(ctx.since) or "-P365D",
                    "orderBy": "updatedAt",
                    "limit": 50,
                    "cursor": ctx.page,
                }
            ),
            items=lambda payload, ctx: find_list(payload, "issues"),
            next_pages=_graphql_pages,
            item_id=lambda item, ctx: text_of(first(item, "identifier", "id")) or None,
            item_updated=lambda item: as_datetime(first(item, "updatedAt", "updated_at")),
            map=_map_linear_issue,
            incremental="filter",
        ),
        Stream(
            key="projects",
            label="Projets Linear",
            list_tool="list_projects",
            list_args=lambda ctx: _drop_empty({"team": ctx.config.get("team"), "limit": 50, "cursor": ctx.page}),
            items=lambda payload, ctx: find_list(payload, "projects"),
            next_pages=_graphql_pages,
            item_id=lambda item, ctx: text_of(first(item, "id", "name")) or None,
            item_updated=lambda item: as_datetime(first(item, "updatedAt", "updated_at")),
            map=_map_linear_project,
            enabled=lambda config: _bool(config, "include_projects", True),
            incremental="skip",
        ),
    ),
)


# --- 7. Obsidian (MarkusPfundstein/mcp-obsidian + Local REST API plugin) ------------------------------


NOTE_SUFFIXES = (".md", ".markdown", ".txt", ".canvas")


def _obsidian_items(payload: Any, ctx: Ctx) -> list[dict[str, Any]]:
    entries = payload if isinstance(payload, list) else find_list(payload, "files")
    base = str(ctx.page or ctx.state.get("root") or "").strip("/")
    out: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry.get("name") if isinstance(entry, dict) else entry)
        path = f"{base}/{name}" if base and not name.startswith(f"{base}/") else name
        if name.endswith("/"):
            ctx.state.setdefault("dirs", []).append(path.rstrip("/"))
        elif PurePosixPath(path).suffix.lower() in NOTE_SUFFIXES[:3]:
            out.append({"path": path})
    return out


def _obsidian_args(ctx: Ctx) -> dict[str, Any]:
    directory = ctx.page if ctx.page is not None else (ctx.item if ctx.item not in (None, "", "*", "/") else None)
    if directory:
        ctx.state["root"] = str(directory)
        return {"dirpath": str(directory).strip("/")}
    return {}


def _obsidian_tool(ctx: Ctx) -> str:
    return "obsidian_list_files_in_dir" if _obsidian_args(ctx) else "obsidian_list_files_in_vault"


def _map_note(item: dict[str, Any], content: Any, ctx: Ctx) -> Record | None:
    text = content if isinstance(content, str) else result_text(ctx.result)
    if not str(text).strip():
        return None
    path = str(item.get("path"))
    frontmatter_date = re.search(r"(?im)^(?:updated|modified|date)\s*:\s*([0-9T:\-+. Z]+)$", text[:2000])
    return Record(
        external_id=path,
        title=PurePosixPath(path).stem,
        content=text,
        uri=None,
        updated_at=as_datetime(frontmatter_date.group(1).strip()) if frontmatter_date else None,
        source_kind="note",
        metadata={"kind": "obsidian_note", "path": path, "folder": str(PurePosixPath(path).parent)},
    )


OBSIDIAN = Preset(
    id="obsidian",
    label="Obsidian",
    vendor="Obsidian · mcp-obsidian",
    description="Notes d'un coffre Obsidian via le serveur MCP mcp-obsidian et le plugin « Local REST API ».",
    icon="obsidian",
    source_kind="note",
    transport="stdio",
    command="mcp-obsidian",
    fallback=("uvx", "mcp-obsidian==0.2.3"),
    version="mcp-obsidian 0.2.3",
    env=lambda config, secrets: {
        "OBSIDIAN_API_KEY": secrets.get("api_key", ""),
        "OBSIDIAN_HOST": str(config.get("host") or "127.0.0.1"),
        "OBSIDIAN_PORT": str(config.get("port") or 27124),
    },
    endpoints=lambda config: [f"https://{config.get('host')}:{config.get('port') or 27124}"] if config.get("host") else [],
    required_tools=("obsidian_list_files_in_vault", "obsidian_list_files_in_dir", "obsidian_get_file_contents"),
    probe=lambda config: ("obsidian_list_files_in_vault", {}),
    validate=lambda config, require_scope: (
        None if config.get("host") else (_ for _ in ()).throw(ValueError("Champ requis : Hôte de l'API Local REST"))
    ),
    docs_url="https://github.com/MarkusPfundstein/mcp-obsidian",
    credentials_help=(
        "Dans Obsidian : installez le plugin communautaire « Local REST API », copiez la clé d'API affichée dans ses "
        "réglages et exposez l'API (HTTPS, port 27124) sur une adresse joignable par ORBIT."
    ),
    fields=(
        PresetField("api_key", "Clé de l'API Local REST", "secret", "password", True),
        PresetField("host", "Hôte de l'API Local REST", "connection", required=True, placeholder="obsidian.exemple.fr"),
        PresetField("port", "Port", "connection", "number", default=27124),
        PresetField("folders", "Dossiers du coffre", "scope", "list", placeholder="Projets/ORBIT", help="Vide = tout le coffre"),
    ),
    streams=(
        Stream(
            key="notes",
            label="Notes",
            list_tool="obsidian_list_files_in_dir",
            list_args=_obsidian_args,
            items=_obsidian_items,
            next_pages=lambda payload, items, ctx: ctx.state.pop("dirs", []),
            item_id=lambda item, ctx: str(item.get("path") or "") or None,
            read_tool="obsidian_get_file_contents",
            read_args=lambda item, ctx: {"filepath": str(item.get("path"))},
            map=_map_note,
            foreach="folders",
            incremental="none",
            full_listing=True,
        ),
    ),
    suggested_task="Résumer les notes récentes du coffre : décisions, idées à creuser et points ouverts",
)


# --- Custom server (platform admins, ORBIT_MCP_ALLOW_CUSTOM) ----------------------------------------


def _custom_args(config: dict[str, Any]) -> list[str]:
    return [str(a) for a in (config.get("args") or [])][:50]


def _custom_env(config: dict[str, Any], secrets: dict[str, str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in str(secrets.get("env") or "").splitlines():
        key, sep, value = line.partition("=")
        if sep and re.fullmatch(r"[A-Z_][A-Z0-9_]*", key.strip()):
            env[key.strip()] = value.strip()
    return env


def _map_resource(item: dict[str, Any], _: Any, ctx: Ctx) -> Record | None:
    texts = resource_texts(ctx.result)
    if texts:
        text = "\n\n".join(t[2] for t in texts)
    else:
        text = ""
        for content in getattr(ctx.result, "contents", None) or []:
            text += str(getattr(content, "text", "") or "")
    if not text.strip():
        return None
    return Record(
        external_id=str(item.get("uri")),
        title=str(item.get("name") or item.get("title") or item.get("uri")),
        content=text,
        mime_type="text/html" if "html" in str(item.get("mime_type") or "") else "text/markdown",
        uri=str(item.get("uri")) if str(item.get("uri", "")).startswith("http") else None,
        metadata={"kind": "mcp_resource", "resource_uri": item.get("uri")},
    )


CUSTOM = Preset(
    id="custom",
    label="Serveur MCP personnalisé",
    vendor="Administrateurs de la plateforme",
    description="Serveur MCP arbitraire (commande stdio ou URL HTTPS) : ses ressources sont lues et ingérées.",
    icon="plug",
    source_kind="document",
    transport="stdio",
    transport_for=lambda config: "http" if config.get("transport") == "http" else "stdio",
    command=None,
    args=_custom_args,
    env=_custom_env,
    url=lambda config: str(config.get("url") or ""),
    headers=lambda config, secrets: {"Authorization": f"Bearer {secrets['token']}"} if secrets.get("token") else {},
    endpoints=lambda config: _https_endpoint(config.get("url")) if config.get("transport") == "http" else [],
    required_tools=(),
    admin_only=True,
    validate=lambda config, require_scope: _custom_validate(config),
    credentials_help="Réservé aux administrateurs : la commande s'exécute dans le conteneur ORBIT avec ces variables.",
    fields=(
        PresetField("token", "Jeton Bearer (HTTP)", "secret", "password", visible_if="transport=http"),
        PresetField("env", "Variables d'environnement (CLÉ=valeur, une par ligne)", "secret", "textarea", visible_if="transport=stdio"),
        PresetField("transport", "Transport", "connection", "select", True, default="stdio", options=(("stdio", "stdio (commande)"), ("http", "HTTP streamable"))),
        PresetField("command", "Commande", "connection", placeholder="/usr/local/bin/mon-serveur-mcp", visible_if="transport=stdio"),
        PresetField("args", "Arguments", "connection", "list", visible_if="transport=stdio"),
        PresetField("url", "URL du serveur MCP", "connection", "url", placeholder="https://mcp.exemple.fr/mcp", visible_if="transport=http"),
    ),
    streams=(),  # resources-based plan (see connector)
)


def _custom_validate(config: dict[str, Any]) -> None:
    if config.get("transport") == "http":
        url = str(config.get("url") or "")
        if not url.lower().startswith(("https://", "http://")):
            raise ValueError("L'URL du serveur MCP doit commencer par https://")
    elif not str(config.get("command") or "").strip():
        raise ValueError("Champ requis : Commande")


PRESETS: dict[str, Preset] = {p.id: p for p in (ATLASSIAN, MS365, GOOGLE, SLACK, GITHUB, LINEAR, OBSIDIAN, CUSTOM)}


def get_preset(preset_id: str | None) -> Preset:
    try:
        return PRESETS[str(preset_id or "")]
    except KeyError as exc:
        raise ValueError(f"Préréglage MCP inconnu : {preset_id or '(vide)'}") from exc


#: Unused-import guard for helpers re-exported to tests.
__all__ = ["CUSTOM", "PRESETS", "Ctx", "Preset", "PresetField", "Stream", "get_preset", "timedelta"]

"""Robust parsing of MCP tool results into ORBIT records (docs/FEATURES.md F6).

MCP servers answer with very different shapes: JSON serialized in a text block (mcp-atlassian,
GitHub, Obsidian), ``structuredContent`` (often ``{"result": …}``), CSV text (Slack), human-readable
lines (Google Workspace), embedded resources (files, base64 blobs). Every helper here tolerates
missing or unknown fields and never raises on unexpected shapes: callers get ``None``/empty values.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.connectors.base import parse_datetime

LIST_KEYS = (
    "items",
    "results",
    "issues",
    "values",
    "value",
    "data",
    "nodes",
    "edges",
    "files",
    "messages",
    "pages",
    "pull_requests",
    "pullRequests",
    "discussions",
    "projects",
    "documents",
    "entries",
    "children",
)


@dataclass(slots=True)
class Record:
    """One item read from an MCP server, ready to become a connector :class:`Change`."""

    external_id: str
    title: str
    content: str | None = None
    data: bytes | None = None
    filename: str | None = None
    mime_type: str = "text/markdown"
    uri: str | None = None
    author: str | None = None
    updated_at: datetime | None = None
    source_kind: str = "document"
    metadata: dict[str, Any] = field(default_factory=dict)
    #: The item was deleted at the source (delta feeds).
    deleted: bool = False


# --- Tool results ---------------------------------------------------------------------------------------


def _blocks(result: Any) -> list[Any]:
    return list(getattr(result, "content", None) or [])


def result_text(result: Any) -> str:
    """Concatenated text of the text blocks and embedded text resources."""
    parts: list[str] = []
    for block in _blocks(result):
        kind = getattr(block, "type", None)
        if kind == "text":
            parts.append(str(getattr(block, "text", "") or ""))
        elif kind == "resource":
            resource = getattr(block, "resource", None)
            text = getattr(resource, "text", None)
            if text:
                parts.append(str(text))
    return "\n".join(part for part in parts if part)


def resource_blobs(result: Any) -> list[tuple[str, str | None, bytes]]:
    """Embedded binary resources ``(uri, mime_type, bytes)``."""
    blobs: list[tuple[str, str | None, bytes]] = []
    for block in _blocks(result):
        resource = getattr(block, "resource", None) if getattr(block, "type", None) == "resource" else None
        blob = getattr(resource, "blob", None)
        if blob:
            try:
                blobs.append(
                    (
                        str(getattr(resource, "uri", "")),
                        getattr(resource, "mime_type", None),
                        base64.b64decode(blob),
                    )
                )
            except (ValueError, TypeError):
                continue
    return blobs


def resource_texts(result: Any) -> list[tuple[str, str | None, str]]:
    """Embedded text resources ``(uri, mime_type, text)``."""
    texts: list[tuple[str, str | None, str]] = []
    for block in _blocks(result):
        if getattr(block, "type", None) != "resource":
            continue
        resource = getattr(block, "resource", None)
        text = getattr(resource, "text", None)
        if text is not None:
            texts.append((str(getattr(resource, "uri", "")), getattr(resource, "mime_type", None), str(text)))
    return texts


def loads(text: str) -> Any:
    """JSON value of ``text`` (also when wrapped in a Markdown code fence), else ``None``."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", stripped)
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        return None


def payload(result: Any) -> Any:
    """Best structured value of a tool result: structured content, JSON text, else the raw text."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and structured:
        if set(structured) == {"result"}:
            inner = structured["result"]
            if isinstance(inner, str):
                parsed = loads(inner)
                return parsed if parsed is not None else inner
            return inner
        return structured
    texts = [str(getattr(b, "text", "") or "") for b in _blocks(result) if getattr(b, "type", None) == "text"]
    if len(texts) > 1:
        parsed_all = [loads(t) for t in texts]
        if all(p is not None for p in parsed_all):
            return parsed_all
    text = "\n".join(texts) if texts else result_text(result)
    parsed = loads(text)
    return parsed if parsed is not None else text


# --- Generic accessors ---------------------------------------------------------------------------------


def dig(value: Any, path: str) -> Any:
    """``dig(d, "fields.status.name")``; list indexes allowed (``"items.0.id"``)."""
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
        if current is None:
            return None
    return current


def first(value: Any, *paths: str) -> Any:
    """First non-empty value among ``paths``."""
    for path in paths:
        found = dig(value, path)
        if found not in (None, "", [], {}):
            return found
    return None


def text_of(value: Any) -> str:
    """Readable text of a field that may be a string, a ``{"value"/"text"/"content"/"displayName"}`` dict…"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in (
            "value",
            "text",
            "content",
            "markdown",
            "body",
            "displayName",
            "display_name",
            "name",
            "login",
        ):
            if value.get(key):
                return text_of(value[key])
        return ""
    if isinstance(value, list):
        return ", ".join(t for t in (text_of(v) for v in value) if t)
    return str(value)


def find_list(value: Any, *keys: str) -> list[dict[str, Any]]:
    """The list of objects of a listing payload (top-level list or under a usual key)."""
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = None
        for key in (*keys, *LIST_KEYS):
            candidate = value.get(key)
            if isinstance(candidate, list):
                items = candidate
                break
            if isinstance(candidate, dict):
                nested = find_list(candidate, *keys)
                if nested:
                    return nested
        if items is None:
            return []
    else:
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("node"), dict):
            item = item["node"]  # GraphQL edges
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            out.append({"name": item})
    return out


def as_datetime(value: Any) -> datetime | None:
    """ISO 8601, ``YYYY-MM-DD HH:MM[:SS]``, epoch seconds (Slack ``ts``) or milliseconds."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and re.fullmatch(r"\d{9,13}(\.\d+)?", value)
    ):
        number = float(value)
        if number > 1e11:
            number /= 1000
        try:
            return datetime.fromtimestamp(number, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?", text):
            text = text.replace(" ", "T")
        return parse_datetime(text)
    return None


def csv_rows(text: str) -> list[dict[str, str]]:
    """Rows of a CSV answer (Slack), keys lower-cased; empty when it does not look like CSV."""
    stripped = text.strip()
    if not stripped or "," not in stripped.splitlines()[0]:
        return []
    try:
        reader = csv.DictReader(io.StringIO(stripped))
        return [{(k or "").strip().lower(): (v or "") for k, v in row.items()} for row in reader]
    except csv.Error:
        return []


_DRIVE_LINE = re.compile(
    r'^-\s*Name:\s*"(?P<name>.*)"\s*\(ID:\s*(?P<id>[^,)]+)(?:,\s*Type:\s*(?P<mime>[^,)]+))?(?P<rest>.*?)\)'
    r"(?:\s*Link:\s*(?P<link>\S+))?\s*$"
)


def drive_lines(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """Files of a Google Workspace MCP listing.

    One ``- Name: "…" (ID: …, Type: …, Modified: …) Link: …`` line per file, then ``nextPageToken: …``.
    """
    files: list[dict[str, Any]] = []
    next_token: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("nextpagetoken:"):
            next_token = line.split(":", 1)[1].strip() or None
            continue
        match = _DRIVE_LINE.match(line)
        if not match:
            continue
        rest = match.group("rest") or ""
        modified = re.search(r"Modified:\s*([0-9T:.\-+Z]+)", rest)
        files.append(
            {
                "id": match.group("id").strip(),
                "name": match.group("name"),
                "mimeType": (match.group("mime") or "").strip(),
                "modifiedTime": modified.group(1) if modified else None,
                "webViewLink": match.group("link") if match.group("link") not in (None, "#") else None,
            }
        )
    return files, next_token


def strip_preamble(text: str) -> str:
    """Drop a « File: … / --- CONTENT --- » style header some servers put before the content."""
    marker = re.search(r"^-{2,}\s*CONTENT\s*-{2,}\s*$", text, flags=re.MULTILINE | re.IGNORECASE)
    if marker:
        return text[marker.end() :].strip()
    return text.strip()


def markdown_sections(title: str, fields: list[tuple[str, Any]], body: str = "", extra: str = "") -> str:
    """Markdown document: ``# title``, a field list, the body and an extra section (comments…)."""
    lines = [f"# {title.strip()}", ""]
    for label, value in fields:
        rendered = text_of(value).strip()
        if rendered:
            lines.append(f"- **{label}** : {rendered}")
    if len(lines) > 2:
        lines.append("")
    if body.strip():
        lines.extend([body.strip(), ""])
    if extra.strip():
        lines.append(extra.strip())
    return "\n".join(lines).strip() + "\n"


def comments_markdown(comments: list[dict[str, Any]], *, limit: int = 50) -> str:
    rendered: list[str] = []
    for comment in comments[:limit]:
        body = text_of(first(comment, "body", "text", "content", "message"))
        if not body.strip():
            continue
        who = text_of(first(comment, "author", "user", "author.login", "user.login", "created_by")) or "?"
        when = text_of(first(comment, "created", "created_at", "createdAt", "updated"))
        header = f"**{who}**" + (f" ({when})" if when else "")
        rendered.append(f"- {header} : {body.strip()}")
    return ("## Commentaires\n\n" + "\n".join(rendered)) if rendered else ""

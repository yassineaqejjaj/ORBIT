"""Bulk import of business records (tickets, CRM accounts, feedback, agent traces) from JSON or CSV.

One record = one document (docs/API.md « Import JSON/CSV »). Recognised columns (case-insensitive):

====================  ==========================================================
field                 columns
====================  ==========================================================
``external_id``       ``id`` | ``external_id`` (also ``key``, ``ticket_id``)
``title``             ``title`` | ``summary`` | ``subject`` | ``name``
``content``           ``content`` | ``description`` | ``body`` | ``text`` | ``notes``
``author``            ``author`` | ``reporter`` | ``owner``
``source_updated_at`` ``updated_at`` | ``date`` | ``created``
``status``            ``status``
``priority``          ``priority``
``tags``              ``tags`` | ``labels``
``classification``    ``classification``
``uri``               ``url`` | ``uri``
====================  ==========================================================

Every other column goes to ``metadata``. The ingested text is the content followed by readable
``Clé : valeur`` lines for status, priority, author, tags and the other columns, so that they are
searchable and their personal data is detected and redacted like the rest of the text.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.enums import SOURCE_KIND_LABELS, SourceKind
from app.ingestion.normalize import collapse_whitespace

MAX_IMPORT_RECORDS = 5000
MAX_TITLE_LENGTH = 300

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "external_id": ("id", "external_id", "key", "ticket_id"),
    "title": ("title", "summary", "subject", "name"),
    "content": ("content", "description", "body", "text", "notes"),
    "author": ("author", "reporter", "owner"),
    "source_updated_at": ("updated_at", "date", "created"),
    "status": ("status",),
    "priority": ("priority",),
    "tags": ("tags", "labels"),
    "classification": ("classification",),
    "uri": ("url", "uri"),
}

_LIST_CONTAINER_KEYS = ("items", "records", "data", "results", "rows", "entries", "issues", "tickets")
_CLASSIFICATION_WORDS = {
    "public": 0,
    "interne": 1,
    "internal": 1,
    "confidentiel": 2,
    "confidential": 2,
    "secret": 3,
}
_DATE_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)
_TAG_SPLIT = re.compile(r"[,;|]")

FIELD_LABELS_FR: dict[str, str] = {
    "status": "Statut",
    "priority": "Priorité",
    "author": "Auteur",
    "tags": "Étiquettes",
}


class RecordParseError(ValueError):
    """The uploaded file cannot be read as records (message in French)."""


@dataclass(slots=True)
class ImportedRecord:
    index: int
    title: str
    content: str
    external_id: str | None = None
    author: str | None = None
    source_updated_at: datetime | None = None
    status: str | None = None
    priority: str | None = None
    tags: list[str] = field(default_factory=list)
    classification: int | None = None
    uri: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# --- Parsing ---------------------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    from app.ingestion.extractors import decode_text

    return decode_text(data)


def _flatten(record: dict[str, Any]) -> dict[str, Any]:
    """Jira-style ``{"key": …, "fields": {...}}`` → flat record."""
    fields = record.get("fields")
    if isinstance(fields, dict):
        flat = {k: v for k, v in record.items() if k != "fields"}
        for key, value in fields.items():
            flat.setdefault(key, value)
        return flat
    return record


def parse_json_records(data: bytes) -> list[dict[str, Any]]:
    """JSON array, object wrapping an array (``items``, ``records``, ``issues``…), single object or NDJSON."""
    text = _decode(data).strip()
    if not text:
        raise RecordParseError("Le fichier JSON est vide")
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        records: list[Any] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                raise RecordParseError(
                    f"JSON invalide (ligne {exc.lineno}, colonne {exc.colno}) : {exc.msg}"
                ) from exc
            if number > MAX_IMPORT_RECORDS + 1:
                break
        payload = records
    if isinstance(payload, dict):
        for key in _LIST_CONTAINER_KEYS:
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        raise RecordParseError("Le JSON doit contenir un tableau d'objets")
    result = [_flatten(item) for item in payload if isinstance(item, dict)]
    if len(payload) and not result:
        raise RecordParseError("Le tableau JSON ne contient aucun objet")
    _check_size(result)
    return result


def _dedupe_headers(headers: Iterable[str | None]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for index, raw in enumerate(headers, start=1):
        name = (raw or "").strip() or f"colonne_{index}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        result.append(name)
    return result


def parse_csv_records(data: bytes) -> list[dict[str, Any]]:
    """CSV with a header row; the delimiter (``,`` ``;`` tab ``|``) is detected."""
    text = _decode(data)
    if not text.strip():
        raise RecordParseError("Le fichier CSV est vide")
    sample = text[:8192]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise RecordParseError(f"CSV invalide : {exc}") from exc
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise RecordParseError("Le CSV doit contenir une ligne d'en-tête et au moins une ligne de données")
    headers = _dedupe_headers(rows[0])
    records: list[dict[str, Any]] = []
    for row in rows[1:]:
        record: dict[str, Any] = {}
        for index, header in enumerate(headers):
            value = row[index].strip() if index < len(row) else ""
            record[header] = value
        if len(row) > len(headers):
            extra = [cell.strip() for cell in row[len(headers) :] if cell.strip()]
            if extra:
                record["colonnes_supplementaires"] = extra
        records.append(record)
    _check_size(records)
    return records


def _check_size(records: list[dict[str, Any]]) -> None:
    if len(records) > MAX_IMPORT_RECORDS:
        raise RecordParseError(
            f"Trop d'enregistrements ({len(records)}) : {MAX_IMPORT_RECORDS} maximum par import"
        )


def parse_records(
    data: bytes, filename: str | None = None, content_type: str | None = None
) -> list[dict[str, Any]]:
    """Parse a JSON or CSV file (format from the extension, the content type, then the content)."""
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if name.endswith((".json", ".ndjson", ".jsonl")) or "json" in ctype:
        return parse_json_records(data)
    if name.endswith((".csv", ".tsv")) or "csv" in ctype or "tab-separated" in ctype:
        return parse_csv_records(data)
    stripped = data.lstrip()[:1]
    if stripped in (b"[", b"{"):
        return parse_json_records(data)
    if name and not name.endswith(".txt"):
        raise RecordParseError("Format d'import non pris en charge : fichier JSON (tableau) ou CSV attendu")
    return parse_csv_records(data)


# --- Mapping ---------------------------------------------------------------------------------------


def _key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\s\-.]+", "_", folded.strip().lower())


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value in ([], {})


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("displayName", "display_name", "name", "value", "email"):
            if isinstance(value.get(key), str):
                return value[key].strip()
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return ", ".join(_as_text(v) for v in value if not _is_empty(v))
    return str(value).strip()


def parse_datetime(value: Any) -> datetime | None:
    """ISO 8601, ``JJ/MM/AAAA[ HH:MM]``, epoch seconds or milliseconds. Naive values are UTC."""
    if _is_empty(value):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, int | float) and not isinstance(value, bool):
        seconds = float(value) / 1000 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if re.fullmatch(r"\d{9,13}", text):
            return parse_datetime(int(text))
        candidate = text.replace("Z", "+00:00") if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None  # type: ignore[assignment]
            for fmt in _DATE_FORMATS:
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def parse_classification(value: Any) -> int | None:
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        level = int(value)
        return level if 0 <= level <= 3 else None
    text = str(value).strip().lower()
    match = re.fullmatch(r"c?([0-3])", text)
    if match:
        return int(match.group(1))
    for word, level in _CLASSIFICATION_WORDS.items():
        if text.startswith(word):
            return level
    return None


def parse_tags(value: Any) -> list[str]:
    if _is_empty(value):
        return []
    items: list[str] = []
    raw_items = value if isinstance(value, list) else _TAG_SPLIT.split(str(value))
    for raw in raw_items:
        tag = _as_text(raw)
        if tag and tag not in items:
            items.append(tag[:64])
    return items[:50]


def _pick(record: dict[str, Any], aliases: tuple[str, ...]) -> tuple[str | None, Any]:
    index = {_key(k): k for k in record}
    for alias in aliases:
        original = index.get(alias)
        if original is not None and not _is_empty(record[original]):
            return original, record[original]
    return None, None


def _label(key: str) -> str:
    text = str(key).replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else key


def render_content(record: ImportedRecord, body: str) -> str:
    """Ingested text: body + readable metadata lines (searchable, PII-scanned)."""
    lines: list[str] = []
    for name in ("status", "priority", "author"):
        value = getattr(record, name)
        if value:
            lines.append(f"{FIELD_LABELS_FR[name]} : {value}")
    if record.tags:
        lines.append(f"{FIELD_LABELS_FR['tags']} : {', '.join(record.tags)}")
    for key, value in record.metadata.items():
        if _is_empty(value):
            continue
        rendered = _as_text(value)
        if rendered and len(rendered) <= 2000:
            lines.append(f"{_label(key)} : {rendered}")
    parts = [body.strip()] if body.strip() else []
    if lines:
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def map_record(record: dict[str, Any], source_kind: SourceKind | str, index: int) -> ImportedRecord | None:
    """Map one raw record to an :class:`ImportedRecord` (``None`` when it holds no usable text)."""
    kind = SourceKind(source_kind)
    used: set[str] = set()
    values: dict[str, Any] = {}
    for field_name, aliases in FIELD_ALIASES.items():
        column, value = _pick(record, aliases)
        if column is not None:
            used.add(column)
            values[field_name] = value

    external_id = _as_text(values["external_id"])[:300] if "external_id" in values else None
    body = _as_text(values.get("content")) if "content" in values else ""
    raw_title = collapse_whitespace(_as_text(values.get("title"))) if "title" in values else ""
    metadata = {str(k): v for k, v in record.items() if k not in used and not _is_empty(v)}

    item = ImportedRecord(
        index=index,
        title="",
        content="",
        external_id=external_id or None,
        author=_as_text(values["author"])[:300] if "author" in values else None,
        source_updated_at=parse_datetime(values.get("source_updated_at")),
        status=_as_text(values["status"])[:100] if "status" in values else None,
        priority=_as_text(values["priority"])[:100] if "priority" in values else None,
        tags=parse_tags(values.get("tags")),
        classification=parse_classification(values.get("classification")),
        uri=_as_text(values["uri"])[:2000] if "uri" in values else None,
        metadata=metadata,
    )
    for name in ("status", "priority"):
        value = getattr(item, name)
        if value:
            item.metadata[name] = value

    content = render_content(item, body)
    if not content and not raw_title:
        return None
    label = SOURCE_KIND_LABELS.get(kind, "Enregistrement")
    if raw_title:
        title = raw_title
    elif body:
        title = collapse_whitespace(body)[:120]
    elif external_id:
        title = f"{label} {external_id}"
    else:
        title = f"{label} {index + 1}"
    if external_id and raw_title and external_id not in raw_title and kind == SourceKind.ticket:
        title = f"{external_id} — {raw_title}"
    item.title = title[:MAX_TITLE_LENGTH]
    item.content = content or item.title
    return item


def map_records(records: list[dict[str, Any]], source_kind: SourceKind | str) -> list[ImportedRecord]:
    """Map every record, skipping empty ones. Raises :class:`RecordParseError` if none is usable."""
    mapped = [m for i, r in enumerate(records) if (m := map_record(r, source_kind, i)) is not None]
    if not mapped:
        raise RecordParseError("Aucun enregistrement exploitable (titre ou contenu manquant)")
    return mapped

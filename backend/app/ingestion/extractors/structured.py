"""JSON / CSV files uploaded as a single document: records rendered as readable text.

(Bulk imports where each record becomes its own document go through :mod:`app.ingestion.importers`.)
"""

from __future__ import annotations

import json
from typing import Any

from app.ingestion.extractors import CSV, JSON, ExtractedDocument, ExtractionError, decode_text
from app.ingestion.importers import RecordParseError, parse_csv_records, parse_json_records

MAX_RENDERED_RECORDS = 5000


def _scalar(value: Any) -> str:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def render_record(record: dict[str, Any]) -> str:
    """``clé : valeur`` lines (empty values skipped)."""
    lines = []
    for key, value in record.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        lines.append(f"- {key} : {_scalar(value)}")
    return "\n".join(lines)


def _render(records: list[dict[str, Any]], label: str) -> str:
    parts = []
    for index, record in enumerate(records[:MAX_RENDERED_RECORDS], start=1):
        body = render_record(record)
        if body:
            parts.append(f"## {label} {index}\n{body}")
    return "\n\n".join(parts)


def extract_json(data: bytes, filename: str | None = None) -> ExtractedDocument:
    try:
        records = parse_json_records(data)
    except RecordParseError as exc:
        raise ExtractionError(str(exc)) from exc
    text = _render(records, "Enregistrement")
    if not text:
        # Scalar JSON document: keep the pretty-printed payload.
        try:
            text = json.dumps(json.loads(decode_text(data)), ensure_ascii=False, indent=2)
        except ValueError as exc:
            raise ExtractionError(f"JSON invalide : {exc}") from exc
    return ExtractedDocument(text=text, format="json", mime_type=JSON, metadata={"record_count": len(records)})


def extract_csv(data: bytes, filename: str | None = None) -> ExtractedDocument:
    try:
        records = parse_csv_records(data)
    except RecordParseError as exc:
        raise ExtractionError(str(exc)) from exc
    return ExtractedDocument(
        text=_render(records, "Ligne"), format="csv", mime_type=CSV, metadata={"record_count": len(records)}
    )

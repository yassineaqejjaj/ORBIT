"""Text extraction per MIME type (ARCHITECTURE §7 step 1).

:func:`extract` is synchronous and CPU-bound: the pipeline runs it in a thread. Every extractor
returns Markdown-flavoured text (headings as ``#``, lists as ``-``) so that the chunker can follow
the document structure, then :func:`app.ingestion.normalize.normalize_text` is applied.

Errors: :class:`UnsupportedFormatError` (unknown type) and :class:`ExtractionError` (corrupt, empty
or encrypted file) carry French messages shown in the Sources screen; both are permanent failures.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from app.ingestion.normalize import normalize_text


class ExtractionError(Exception):
    """The file cannot be turned into text (message in French)."""


class UnsupportedFormatError(ExtractionError):
    """No extractor for this MIME type / extension."""


@dataclass(slots=True)
class ExtractedDocument:
    text: str
    format: str
    mime_type: str
    title: str | None = None
    author: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MARKDOWN = "text/markdown"
TEXT = "text/plain"
HTML = "text/html"
JSON = "application/json"
CSV = "text/csv"

MIME_BY_EXTENSION: dict[str, str] = {
    ".pdf": PDF,
    ".docx": DOCX,
    ".md": MARKDOWN,
    ".markdown": MARKDOWN,
    ".mdown": MARKDOWN,
    ".txt": TEXT,
    ".text": TEXT,
    ".log": TEXT,
    ".html": HTML,
    ".htm": HTML,
    ".xhtml": HTML,
    ".json": JSON,
    ".ndjson": JSON,
    ".jsonl": JSON,
    ".csv": CSV,
    ".tsv": CSV,
}

_MIME_ALIASES: dict[str, str] = {
    "application/x-pdf": PDF,
    "text/x-markdown": MARKDOWN,
    "text/md": MARKDOWN,
    "application/xhtml+xml": HTML,
    "application/x-ndjson": JSON,
    "application/ndjson": JSON,
    "application/jsonl": JSON,
    "text/json": JSON,
    "application/csv": CSV,
    "text/tab-separated-values": CSV,
    "application/vnd.ms-excel": CSV,  # browsers often label .csv this way
}

SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(MIME_BY_EXTENSION.values())
SUPPORTED_FORMATS_LABEL = "PDF, DOCX, Markdown, texte, HTML, JSON, CSV"


def _canonical(mime: str | None) -> str | None:
    if not mime:
        return None
    base = mime.split(";", 1)[0].strip().lower()
    return _MIME_ALIASES.get(base, base)


def detect_mime_type(filename: str | None, content_type: str | None = None, data: bytes | None = None) -> str:
    """Best MIME type from the file extension, the declared content type and magic bytes.

    Returns the canonical type (one of :data:`SUPPORTED_MIME_TYPES` when supported), or the
    declared/guessed type otherwise (callers check :func:`is_supported`).
    """
    if data:
        head = data[:8]
        if head.startswith(b"%PDF-"):
            return PDF
    extension = PurePosixPath((filename or "").lower()).suffix
    if extension in MIME_BY_EXTENSION:
        return MIME_BY_EXTENSION[extension]
    from app.ingestion.extractors.markitdown import CONVERTIBLE_BY_EXTENSION

    if extension in CONVERTIBLE_BY_EXTENSION:  # converted by MarkItDown (MCP) when available
        return CONVERTIBLE_BY_EXTENSION[extension]
    declared = _canonical(content_type)
    if declared in SUPPORTED_MIME_TYPES:
        return declared
    if data and data[:4] == b"PK\x03\x04" and b"word/" in data[:4000]:
        return DOCX
    guessed = _canonical(mimetypes.guess_type(filename or "")[0])
    if guessed in SUPPORTED_MIME_TYPES:
        return guessed
    if declared and declared.startswith("text/"):
        return TEXT
    return declared or guessed or "application/octet-stream"


def is_supported(mime_type: str | None, filename: str | None = None) -> bool:
    """Native format, or a format converted by the MarkItDown MCP fallback when it is available."""
    from app.ingestion.extractors import markitdown

    if markitdown.is_convertible(mime_type, filename):
        return markitdown.available()
    return _canonical(mime_type) in SUPPORTED_MIME_TYPES


def needs_conversion(mime_type: str | None, filename: str | None = None, data: bytes | None = None) -> bool:
    """Not parsed natively but convertible by MarkItDown (``.xls`` labelled as CSV, OLE files…)."""
    from app.ingestion.extractors import markitdown

    if markitdown.is_convertible(mime_type, filename):
        return True
    return bool(data) and data[:4] == b"\xd0\xcf\x11\xe0" and _canonical(mime_type) == CSV


def decode_text(data: bytes) -> str:
    """Decode text bytes: UTF-8 (with or without BOM), UTF-16 with BOM, then Windows-1252."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _extractors() -> dict[str, Callable[[bytes, str | None], ExtractedDocument]]:
    from app.ingestion.extractors import html, pdf, structured, text, word

    return {
        PDF: pdf.extract_pdf,
        DOCX: word.extract_docx,
        MARKDOWN: text.extract_markdown,
        TEXT: text.extract_plain,
        HTML: html.extract_html,
        JSON: structured.extract_json,
        CSV: structured.extract_csv,
    }


def extract(data: bytes, mime_type: str, filename: str | None = None) -> ExtractedDocument:
    """Extract and normalise the text of ``data``. Raises :class:`ExtractionError` (FR message)."""
    canonical = _canonical(mime_type) or detect_mime_type(filename, None, data)
    extractor = None if needs_conversion(mime_type, filename, data) else _extractors().get(canonical)
    if extractor is None:
        raise UnsupportedFormatError(
            f"Format non pris en charge ({mime_type or 'inconnu'}) — "
            f"formats acceptés : {SUPPORTED_FORMATS_LABEL}"
        )
    if not data:
        raise ExtractionError("Le fichier est vide")
    try:
        result = extractor(data, filename)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Fichier illisible ou corrompu ({type(exc).__name__}) : {exc}") from exc
    result.text = normalize_text(result.text)
    if not result.text:
        raise ExtractionError("Aucun texte exploitable n'a été trouvé dans le document")
    result.metadata.setdefault("char_count", len(result.text))
    return result


def extract_text_content(content: str, mime_type: str = MARKDOWN) -> ExtractedDocument:
    """Normalise a text pushed through the API (notes, tickets…): no decoding needed."""
    text = normalize_text(content)
    if not text:
        raise ExtractionError("Le contenu est vide")
    fmt = "html" if _canonical(mime_type) == HTML else "markdown"
    if fmt == "html":
        from app.ingestion.extractors.html import extract_html

        extracted = extract_html(content.encode("utf-8"), None)
        extracted.text = normalize_text(extracted.text)
        return extracted
    return ExtractedDocument(text=text, format=fmt, mime_type=MARKDOWN, metadata={"char_count": len(text)})


__all__ = [
    "CSV",
    "DOCX",
    "HTML",
    "JSON",
    "MARKDOWN",
    "PDF",
    "SUPPORTED_FORMATS_LABEL",
    "SUPPORTED_MIME_TYPES",
    "TEXT",
    "ExtractedDocument",
    "ExtractionError",
    "UnsupportedFormatError",
    "decode_text",
    "detect_mime_type",
    "extract",
    "extract_text_content",
    "is_supported",
    "needs_conversion",
]

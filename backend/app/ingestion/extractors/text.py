"""Markdown and plain-text extraction (decoding, YAML front matter, title detection)."""

from __future__ import annotations

import re

from app.ingestion.extractors import MARKDOWN, TEXT, ExtractedDocument, decode_text

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n(?:---|\.\.\.)\s*(?:\n|\Z)", re.DOTALL)
_FRONT_MATTER_LINE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")
_FIRST_HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)
_SETEXT_H1 = re.compile(r"^(?P<title>[^\n#][^\n]*)\n=+\s*$", re.MULTILINE)
_SETEXT_H2 = re.compile(r"^(?P<title>[^\n#-][^\n]*)\n-{3,}\s*$", re.MULTILINE)


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    values: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        pair = _FRONT_MATTER_LINE.match(line.strip())
        if pair:
            values[pair.group(1).lower()] = pair.group(2).strip().strip("\"'")
    return values, text[match.end() :]


def markdown_to_structured(text: str) -> str:
    """Convert Setext headings (``Titre\\n=====``) to ATX (``# Titre``) for the chunker."""
    text = _SETEXT_H1.sub(lambda m: f"# {m.group('title').strip()}", text)
    return _SETEXT_H2.sub(lambda m: f"## {m.group('title').strip()}", text)


def extract_markdown(data: bytes, filename: str | None = None) -> ExtractedDocument:
    raw = decode_text(data)
    meta, body = _front_matter(raw)
    body = markdown_to_structured(body)
    heading = _FIRST_HEADING.search(body)
    title = meta.get("title") or (heading.group(1).strip() if heading else None)
    metadata: dict[str, object] = {}
    if meta:
        metadata["front_matter"] = meta
    return ExtractedDocument(
        text=body,
        format="markdown",
        mime_type=MARKDOWN,
        title=title,
        author=meta.get("author") or None,
        metadata=metadata,
    )


def extract_plain(data: bytes, filename: str | None = None) -> ExtractedDocument:
    return ExtractedDocument(text=decode_text(data), format="text", mime_type=TEXT)

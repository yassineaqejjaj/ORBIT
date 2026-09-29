"""PDF extraction with pypdf (text layer only; scanned PDFs without OCR are rejected)."""

from __future__ import annotations

import io
import logging
import re

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from app.ingestion.extractors import PDF, ExtractedDocument, ExtractionError
from app.ingestion.normalize import normalize_text, unwrap_lines

logger = logging.getLogger("orbit.extract.pdf")

_PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s*)?\d{1,4}\s*(?:/\s*\d{1,4})?\s*$", re.IGNORECASE)


def _clean_page(text: str) -> str:
    lines = [line for line in text.split("\n") if not _PAGE_NUMBER_LINE.match(line)]
    return unwrap_lines(normalize_text("\n".join(lines)))


def extract_pdf(data: bytes, filename: str | None = None) -> ExtractedDocument:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except PdfReadError as exc:
        raise ExtractionError(f"PDF illisible ou corrompu : {exc}") from exc
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ExtractionError("PDF protégé par mot de passe : impossible d'extraire le texte")
        except (FileNotDecryptedError, NotImplementedError) as exc:
            raise ExtractionError("PDF chiffré : impossible d'extraire le texte") from exc

    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # a single broken page must not lose the whole document
            logger.warning("PDF page %d of %s unreadable: %s", number, filename, exc)
            continue
        cleaned = _clean_page(raw)
        if cleaned:
            pages.append(cleaned)
    if not pages:
        raise ExtractionError(
            "Le PDF ne contient pas de texte extractible (document scanné ? l'OCR n'est pas activé)"
        )

    title: str | None = None
    author: str | None = None
    try:
        info = reader.metadata
        if info is not None:
            title = (info.title or "").strip() or None
            author = (info.author or "").strip() or None
    except Exception:  # malformed metadata dictionary
        logger.debug("PDF metadata unreadable for %s", filename, exc_info=True)

    return ExtractedDocument(
        text="\n\n".join(pages),
        format="pdf",
        mime_type=PDF,
        title=title,
        author=author,
        metadata={"page_count": len(reader.pages), "pages_with_text": len(pages)},
    )

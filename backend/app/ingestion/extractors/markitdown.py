"""MarkItDown fallback extractor through MCP (docs/FEATURES.md F6).

Formats ORBIT does not parse natively (PowerPoint, Excel, Outlook ``.msg``, ``.eml``, EPUB, OpenDocument,
RTF, images…) are converted to Markdown by Microsoft's MarkItDown MCP server (``markitdown-mcp``, stdio,
tool ``convert_to_markdown(uri)``) on a temporary ``file://`` copy of the file.

``ORBIT_MARKITDOWN_MCP=auto`` (default) uses it when the ``markitdown-mcp`` binary is installed (Docker
images pre-install it), ``off`` disables it. The server runs with the minimal MCP environment (no
secret, temporary HOME) and the per-call timeout ``ORBIT_MCP_TIMEOUT_SECONDS``; it is killed on timeout.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import PurePosixPath

from app.config import settings
from app.ingestion.extractors import ExtractedDocument, ExtractionError

CONVERTER = "markitdown-mcp"
TOOL = "convert_to_markdown"

#: Formats converted by MarkItDown (extension → MIME type).
CONVERTIBLE_BY_EXTENSION: dict[str, str] = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".msg": "application/vnd.ms-outlook",
    ".eml": "message/rfc822",
    ".epub": "application/epub+zip",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".rtf": "application/rtf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
CONVERTIBLE_MIME_TYPES: frozenset[str] = frozenset(CONVERTIBLE_BY_EXTENSION.values()) | {"text/rtf"}
EXTENSION_BY_MIME: dict[str, str] = {mime: ext for ext, mime in reversed(CONVERTIBLE_BY_EXTENSION.items())}
CONVERTIBLE_LABEL = "PowerPoint, Excel, Outlook (.msg/.eml), EPUB, OpenDocument, RTF, images"


def _mime(mime_type: str | None) -> str:
    return (mime_type or "").split(";", 1)[0].strip().lower()


def extension_of(filename: str | None) -> str:
    return PurePosixPath((filename or "").lower()).suffix


def is_convertible(mime_type: str | None, filename: str | None = None) -> bool:
    """A format MarkItDown can convert (by extension, else by MIME type)."""
    if extension_of(filename) in CONVERTIBLE_BY_EXTENSION:
        return True
    mime = _mime(mime_type)
    return mime in CONVERTIBLE_MIME_TYPES and mime != "application/vnd.ms-excel"  # .csv often labelled so


def command() -> str | None:
    """Installed ``markitdown-mcp`` binary, ``None`` when missing or disabled."""
    if settings.markitdown_mcp == "off":
        return None
    configured = settings.markitdown_mcp_command or CONVERTER
    if os.path.isabs(configured):
        return configured if os.access(configured, os.X_OK) else None
    return shutil.which(configured)


def available() -> bool:
    return command() is not None


def unavailable_reason(mime_type: str | None, filename: str | None) -> str:
    fmt = extension_of(filename).lstrip(".") or _mime(mime_type) or "inconnu"
    why = (
        "désactivé (ORBIT_MARKITDOWN_MCP=off)"
        if settings.markitdown_mcp == "off"
        else f"indisponible (« {settings.markitdown_mcp_command or CONVERTER} » n'est pas installé)"
    )
    return (
        f"Format « {fmt} » non pris en charge nativement et convertisseur MarkItDown (MCP) {why} — "
        f"installez markitdown-mcp ou convertissez le fichier en PDF/DOCX"
    )


async def convert(data: bytes, mime_type: str | None, filename: str | None) -> ExtractedDocument:
    """Markdown of ``data`` through the MarkItDown MCP server. Raises :class:`ExtractionError` (French)."""
    from app.connectors.base import ConnectorError
    from app.connectors.mcp.client import McpClient, StdioTarget
    from app.connectors.mcp.mapper import payload, result_text

    binary = command()
    if binary is None:
        raise ExtractionError(unavailable_reason(mime_type, filename))
    if not data:
        raise ExtractionError("Le fichier est vide")
    suffix = extension_of(filename) or EXTENSION_BY_MIME.get(_mime(mime_type), ".bin")
    workdir = tempfile.mkdtemp(prefix="orbit-markitdown-")
    try:
        os.chmod(workdir, 0o755)
        path = os.path.join(workdir, f"document{suffix}")
        with open(path, "wb") as handle:  # noqa: ASYNC230 — small local temp file
            handle.write(data)
        os.chmod(path, 0o644)
        try:
            async with McpClient(
                StdioTarget(command=binary),
                timeout=float(settings.mcp_timeout_seconds),
                label="convertisseur MarkItDown (MCP)",
            ) as client:
                result = await client.call_tool(TOOL, {"uri": f"file://{path}"})
        except ConnectorError as exc:
            raise ExtractionError(f"Conversion MarkItDown (MCP) impossible : {exc.message}") from exc
        value = payload(result)
        text = value if isinstance(value, str) else result_text(result)
        if not text.strip():
            raise ExtractionError("Conversion MarkItDown (MCP) : aucun texte exploitable n'a été trouvé")
        from app.ingestion.normalize import normalize_text

        return ExtractedDocument(
            text=normalize_text(text),
            format="markitdown",
            mime_type=_mime(mime_type) or "application/octet-stream",
            metadata={"converter": CONVERTER, "source_format": suffix.lstrip(".")},
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

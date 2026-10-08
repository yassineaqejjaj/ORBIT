"""Optional audio transcription (docs/AI_CONTEXT_ENGINEERING.md §F1).

Calls an OpenAI-compatible ``POST {ORBIT_TRANSCRIPTION_BASE_URL}/audio/transcriptions`` endpoint
(OpenAI Whisper, faster-whisper-server, vLLM, LocalAI…) with ``response_format=verbose_json`` and turns the
returned segments into a :class:`app.ingestion.meetings.Transcript` (no speaker diarisation: Whisper
does not return speakers, a ``speaker`` field is used when the server provides one).

Guardrail: audio above ``ORBIT_LLM_MAX_CLASSIFICATION`` (C1 by default) is **never** sent to an external
server — only ``ORBIT_TRANSCRIPTION_LOCAL=true`` (self-hosted server) lifts the ceiling. Files larger than
``ORBIT_TRANSCRIPTION_MAX_MB`` are refused before any call.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.ingestion.meetings import Transcript, Turn
from app.llm import guardrail

MAX_LEVEL = 3


class TranscriptionError(Exception):
    """Transcription refused or failed (French message shown in the Sources screen)."""


def enabled() -> bool:
    return bool(settings.transcription_base_url.strip())


def max_bytes() -> int:
    return int(settings.transcription_max_mb) * 1024 * 1024


def ceiling() -> int:
    """Highest classification whose audio may be sent to the transcription server."""
    return MAX_LEVEL if settings.transcription_local else int(settings.llm_max_classification)


def allows(classification: int | None) -> bool:
    level = MAX_LEVEL if classification is None else int(classification)
    return level <= ceiling()


def check(size: int, classification: int | None) -> None:
    """Raise :class:`TranscriptionError` when the audio may not be transcribed (before any network call)."""
    if not enabled():
        raise TranscriptionError(
            "Transcription audio non configurée (ORBIT_TRANSCRIPTION_BASE_URL) — importez une transcription "
            "(VTT, SRT, DOCX ou texte)"
        )
    if size > max_bytes():
        raise TranscriptionError(
            "Fichier audio trop volumineux pour la transcription "
            f"(maximum {settings.transcription_max_mb} Mo)"
        )
    if not allows(classification):
        guardrail.record_skip(guardrail.REASON_CLASSIFICATION)
        level = MAX_LEVEL if classification is None else int(classification)
        raise TranscriptionError(
            f"Transcription refusée par le garde-fou : un enregistrement C{level} n'est jamais envoyé à un "
            "service de transcription externe (ORBIT_TRANSCRIPTION_LOCAL=true pour un serveur auto-hébergé)"
        )


def _transcript(payload: object) -> Transcript:
    transcript = Transcript(format="audio")
    if isinstance(payload, dict):
        segments = payload.get("segments")
        if isinstance(segments, list) and segments:
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                text = " ".join(str(segment.get("text") or "").split())
                if not text:
                    continue
                speaker = segment.get("speaker")
                transcript.turns.append(
                    Turn(
                        str(speaker) if speaker else None,
                        text,
                        float(segment["start"]) if segment.get("start") is not None else None,
                        float(segment["end"]) if segment.get("end") is not None else None,
                    )
                )
        elif payload.get("text"):
            transcript.turns.append(Turn(None, " ".join(str(payload["text"]).split()), 0.0))
    elif isinstance(payload, str) and payload.strip():
        transcript.turns.append(Turn(None, " ".join(payload.split()), 0.0))
    return transcript


async def transcribe(
    data: bytes,
    filename: str,
    mime_type: str,
    *,
    classification: int | None,
    language: str | None = "fr",
    transport: httpx.AsyncBaseTransport | None = None,
) -> Transcript:
    """Transcribe ``data`` (guardrail and size limit checked first). Raises :class:`TranscriptionError`."""
    check(len(data), classification)
    url = settings.transcription_base_url.rstrip("/") + "/audio/transcriptions"
    key = settings.transcription_api_key
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    form = {"model": settings.transcription_model, "response_format": "verbose_json"}
    if language:
        form["language"] = language
    try:
        timeout = settings.transcription_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(
                url, headers=headers, data=form, files={"file": (filename, data, mime_type)}
            )
    except httpx.HTTPError as exc:
        raise TranscriptionError(f"Service de transcription injoignable ({type(exc).__name__})") from exc
    if response.status_code >= 400:
        raise TranscriptionError(f"Le service de transcription a répondu {response.status_code}")
    try:
        payload: object = response.json()
    except ValueError:
        payload = response.text
    transcript = _transcript(payload)
    if not transcript.turns:
        raise TranscriptionError("La transcription est vide (aucune parole détectée)")
    return transcript


__all__ = ["TranscriptionError", "allows", "ceiling", "check", "enabled", "max_bytes", "transcribe"]

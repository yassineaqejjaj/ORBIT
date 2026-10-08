"""Meeting transcripts (docs/AI_CONTEXT_ENGINEERING.md §F1).

Parsers for the usual transcript exports, all producing a :class:`Transcript` (speaker turns with
timestamps in seconds):

* **WebVTT** (Teams, Zoom, Meet): cues ``00:00:03.120 --> 00:00:07.450``, speaker in a voice tag
  ``<v Alice Martin>…</v>`` or a ``Alice Martin: …`` prefix;
* **SRT**: numbered cues ``00:00:03,120 --> …``, speaker as ``Name: …`` or ``[Name] …``;
* **DOCX** transcripts (Teams « Télécharger en .docx », Google Meet « Transcription » documents): the
  paragraphs are read in order then parsed like text;
* **text**: ``Name: text`` lines, optionally ``[00:01:02] Name: text``, standalone timestamp lines
  (Meet), ``Name   0:03`` header lines followed by the text (new Teams) or cue lines followed by the
  speaker then the text (classic Teams).

:func:`render` turns a transcript into the Markdown indexed by ORBIT: one line per turn
``[hh:mm:ss] Speaker : text`` — speakers and timestamps stay inside every chunk — and
:func:`timeline` gives the compact turn list stored in ``documents.metadata.meeting`` (speaker
timeline of the document view, speaker attribution of the memory extractor).
"""

from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.ingestion.extractors import DOCX, ExtractedDocument, ExtractionError, decode_text

VTT = "text/vtt"
SRT = "application/x-subrip"
TRANSCRIPT_MIME_TYPES = frozenset({VTT, SRT})
TRANSCRIPT_EXTENSIONS = {".vtt": VTT, ".srt": SRT}
AUDIO_EXTENSIONS: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".flac": "audio/flac",
}
#: Turns kept in the document metadata (speaker timeline) and characters per turn there.
MAX_TIMELINE_TURNS = 2000
TIMELINE_TEXT_CHARS = 280
#: Consecutive cues of one speaker are merged into one turn up to this length.
MAX_TURN_CHARS = 1200
#: … and when the silence between them is short (seconds).
MAX_MERGE_GAP_SECONDS = 5.0

_TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_TS_RE = re.compile(r"^(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>\d{2})(?:[.,](?P<ms>\d{1,3}))?$")
_CUE = re.compile(rf"^\s*(?P<start>{_TS})\s*-->\s*(?P<end>{_TS})")
_VOICE = re.compile(r"<v(?:\.[\w.-]+)?\s+(?P<name>[^>]+)>(?P<text>.*?)(?:</v>|$)", re.DOTALL)
_TAG = re.compile(r"</?[^>]{1,40}>")
_NAME = r"[A-ZÀ-ÝŒ][\w'’.\-]*(?:[ \t]+[A-Za-zÀ-ÿŒœ][\w'’.\-]*){0,4}"
_NAME_TEXT = re.compile(rf"^(?:-\s*)?(?P<name>{_NAME})\s*[:：]\s+(?P<text>\S.*)$")
_BRACKET_NAME = re.compile(r"^\[(?P<name>[^\]\d][^\]]{0,60})\]\s*(?P<text>\S.*)$")
_TS_LINE = re.compile(rf"^\[?\(?(?P<ts>{_TS})\)?\]?$")
_TS_PREFIX = re.compile(rf"^\[?\(?(?P<ts>{_TS})\)?\]?\s*[-–—]?\s*(?P<rest>\S.*)$")
_NAME_TS = re.compile(rf"^(?P<name>{_NAME})\s{{1,}}(?P<ts>{_TS})(?:\s*.*)?$")
_NAME_ALONE = re.compile(rf"^(?P<name>{_NAME})$")
#: Line prefixes that are labels of the content, never speakers (« Décision : … », « Date : … »).
_NOT_SPEAKERS = frozenset(
    {
        "decision", "decisions", "action", "actions", "besoin", "exigence", "contrainte", "risque", "fait",
        "note", "notes", "date", "participants", "participant", "presents", "absents", "objet", "lieu",
        "heure", "ordre du jour", "remarque", "question", "reponse", "conclusion", "resume", "titre",
        "transcription", "reunion", "webvtt", "kind", "language", "duree", "attention", "important", "todo",
        "a faire", "prochaine etape", "prochaines etapes", "point de vigilance", "user story", "en resume",
    }
)  # fmt: skip


@dataclass(slots=True)
class Turn:
    speaker: str | None
    text: str
    start: float | None = None
    end: float | None = None


@dataclass(slots=True)
class Transcript:
    format: str
    turns: list[Turn] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        seen: dict[str, None] = {}
        for turn in self.turns:
            if turn.speaker:
                seen.setdefault(turn.speaker, None)
        return list(seen)

    @property
    def duration(self) -> float | None:
        ends = [t.end if t.end is not None else t.start for t in self.turns]
        known = [v for v in ends if v is not None]
        return max(known) if known else None


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def parse_timestamp(value: str) -> float | None:
    match = _TS_RE.match(value.strip())
    if not match:
        return None
    hours = int(match.group("h") or 0)
    millis = (match.group("ms") or "0").ljust(3, "0")
    return hours * 3600 + int(match.group("m")) * 60 + int(match.group("s")) + int(millis) / 1000


def format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _speaker(name: str) -> str | None:
    cleaned = " ".join(name.strip(" -–—*_").split())
    if not cleaned or len(cleaned) > 60 or fold(cleaned) in _NOT_SPEAKERS or cleaned[0].isdigit():
        return None
    return cleaned


def split_speaker(text: str) -> tuple[str | None, str]:
    """``(speaker, text)`` from ``Name: text`` / ``[Name] text`` / ``<v Name>text``, else ``(None, text)``."""
    voice = _VOICE.search(text)
    if voice:
        return _speaker(voice.group("name")), _clean(voice.group("text"))
    for pattern in (_NAME_TEXT, _BRACKET_NAME):
        match = pattern.match(text)
        if match:
            name = _speaker(match.group("name"))
            if name:
                return name, _clean(match.group("text"))
    return None, _clean(text)


def _clean(text: str) -> str:
    return " ".join(_TAG.sub("", text).split())


def _append(turns: list[Turn], turn: Turn) -> None:
    """Merge consecutive cues of the same speaker into one turn."""
    if not turn.text:
        return
    last = turns[-1] if turns else None
    if (
        last is not None
        and last.speaker == turn.speaker
        and last.speaker is not None
        and len(last.text) + len(turn.text) < MAX_TURN_CHARS
        and (turn.start is None or last.end is None or turn.start - last.end <= MAX_MERGE_GAP_SECONDS)
    ):
        last.text = f"{last.text} {turn.text}"
        last.end = turn.end if turn.end is not None else last.end
        return
    turns.append(turn)


def _blocks(text: str) -> Iterable[list[str]]:
    block: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            block.append(line.strip())
        elif block:
            yield block
            block = []
    if block:
        yield block


def parse_cues(text: str, fmt: str) -> Transcript:
    """WebVTT and SRT: cue blocks with a ``start --> end`` line."""
    transcript = Transcript(format=fmt)
    for block in _blocks(text):
        index = next((i for i, line in enumerate(block) if _CUE.match(line)), None)
        if index is None:
            continue  # WEBVTT header, NOTE / STYLE / REGION blocks
        cue = _CUE.match(block[index])
        assert cue is not None
        payload = " ".join(block[index + 1 :])
        if not payload:
            continue
        speaker, body = split_speaker(payload)
        _append(
            transcript.turns,
            Turn(speaker, body, parse_timestamp(cue.group("start")), parse_timestamp(cue.group("end"))),
        )
    return transcript


def parse_text_lines(lines: Sequence[str], fmt: str = "text") -> Transcript:
    """Line-oriented transcripts (plain text, DOCX paragraphs) — see the module docstring."""
    transcript = Transcript(format=fmt)
    current: Turn | None = None
    pending_ts: float | None = None
    expect_speaker = False

    def flush() -> None:
        nonlocal current
        if current is not None and current.text:
            _append(transcript.turns, current)
        current = None

    for raw in lines:
        line = raw.strip()
        if not line or line.upper() == "WEBVTT":
            continue
        cue = _CUE.match(line)
        if cue:  # classic Teams: cue line, then the speaker alone, then the text
            flush()
            pending_ts = parse_timestamp(cue.group("start"))
            expect_speaker = True
            continue
        ts_only = _TS_LINE.match(line)
        if ts_only:  # Google Meet: standalone timestamp line
            flush()
            pending_ts = parse_timestamp(ts_only.group("ts"))
            continue
        if expect_speaker:
            expect_speaker = False
            alone = _NAME_ALONE.match(line)
            name = _speaker(alone.group("name")) if alone else None
            if name:
                current = Turn(name, "", pending_ts)
                pending_ts = None
                continue
        name_ts = _NAME_TS.match(line)
        # new Teams: « Alice Martin   0:03 »
        if name_ts and _speaker(name_ts.group("name")) and len(line) < 90:
            flush()
            current = Turn(_speaker(name_ts.group("name")), "", parse_timestamp(name_ts.group("ts")))
            continue
        start = pending_ts
        prefixed = _TS_PREFIX.match(line)
        if prefixed and parse_timestamp(prefixed.group("ts")) is not None:
            start = parse_timestamp(prefixed.group("ts"))
            line = prefixed.group("rest")
        speaker, body = split_speaker(line)
        if speaker:
            flush()
            current = Turn(speaker, body, start)
            pending_ts = None
        elif current is not None:
            current.text = f"{current.text}\n{body}".strip()
        else:
            current = Turn(None, body, start)
            pending_ts = None
            flush()
    flush()
    return transcript


def _docx_lines(data: bytes) -> list[str]:
    from docx import Document as load_docx

    try:
        document = load_docx(io.BytesIO(data))
    except Exception as exc:  # corrupt package
        raise ExtractionError(f"Transcription DOCX illisible ou corrompue : {exc}") from exc
    lines: list[str] = []
    for paragraph in document.paragraphs:
        # Teams puts « Name   0:03 » and the text in one paragraph separated by line breaks.
        lines.extend(part for part in paragraph.text.split("\n"))
    for table in document.tables:  # some exports lay out « heure | intervenant | texte » in a table
        for row in table.rows:
            cells = [" ".join(c.text.split()) for c in row.cells]
            if len(cells) >= 3 and parse_timestamp(cells[0]) is not None:
                lines.append(f"[{cells[0]}] {cells[1]}: {' '.join(cells[2:])}")
            elif len(cells) == 2 and cells[0] and cells[1]:
                lines.append(f"{cells[0]}: {cells[1]}")
    return lines


def parse(data: bytes, mime_type: str | None, filename: str | None = None) -> Transcript:
    """Parse a transcript file. Raises :class:`ExtractionError` (FR) when nothing usable is found."""
    name = (filename or "").lower()
    if mime_type == DOCX or name.endswith(".docx"):
        transcript = parse_text_lines(_docx_lines(data), "docx")
    else:
        text = decode_text(data)
        if mime_type == VTT or name.endswith(".vtt") or text.lstrip().upper().startswith("WEBVTT"):
            transcript = parse_cues(text, "vtt")
        elif mime_type == SRT or name.endswith(".srt"):
            transcript = parse_cues(text, "srt")
        else:
            transcript = parse_text_lines(text.splitlines(), "text")
    if not transcript.turns:
        raise ExtractionError("Aucune intervention n'a été trouvée dans la transcription")
    return transcript


def render(
    transcript: Transcript,
    *,
    title: str | None = None,
    date: str | None = None,
    participants: Sequence[str] = (),
) -> str:
    """Markdown indexed by ORBIT: header then one ``[hh:mm:ss] Speaker : text`` line per turn."""
    lines: list[str] = []
    if title:
        lines += [f"# {title}", ""]
    if date:
        lines.append(f"Date : {date}")
    people = list(dict.fromkeys([*participants, *transcript.speakers]))
    if people:
        lines.append(f"Participants : {', '.join(people)}")
    if date or people:
        lines.append("")
    lines += ["## Transcription", ""]
    for turn in transcript.turns:
        stamp = f"[{format_timestamp(turn.start)}] " if turn.start is not None else ""
        speaker = f"{turn.speaker} : " if turn.speaker else ""
        lines += [f"{stamp}{speaker}{turn.text}", ""]  # continuation lines keep the turn's speaker
    return "\n".join(lines).rstrip() + "\n"


def timeline(transcript: Transcript) -> list[dict[str, Any]]:
    """Compact turn list for ``documents.metadata.meeting.turns`` (speaker timeline)."""
    items: list[dict[str, Any]] = []
    for turn in transcript.turns[:MAX_TIMELINE_TURNS]:
        text = " ".join(turn.text.split())
        item: dict[str, Any] = {"speaker": turn.speaker, "text": text[:TIMELINE_TEXT_CHARS]}
        if turn.start is not None:
            item["start"] = round(turn.start, 2)
        if turn.end is not None:
            item["end"] = round(turn.end, 2)
        items.append(item)
    return items


def meeting_metadata(transcript: Transcript) -> dict[str, Any]:
    duration = transcript.duration
    return {
        "format": transcript.format,
        "speakers": transcript.speakers,
        "turn_count": len(transcript.turns),
        "duration_seconds": round(duration, 1) if duration is not None else None,
        "turns": timeline(transcript),
    }


def extract_meeting(
    data: bytes,
    mime_type: str | None,
    filename: str | None = None,
    *,
    title: str | None = None,
    date: str | None = None,
    participants: Sequence[str] = (),
) -> ExtractedDocument:
    """Transcript file → :class:`ExtractedDocument` whose metadata carries ``meeting`` (pipeline step 1)."""
    transcript = parse(data, mime_type, filename)
    return document_from_transcript(transcript, title=title, date=date, participants=participants)


def document_from_transcript(
    transcript: Transcript,
    *,
    title: str | None = None,
    date: str | None = None,
    participants: Sequence[str] = (),
) -> ExtractedDocument:
    from app.ingestion.extractors import MARKDOWN

    return ExtractedDocument(
        text=render(transcript, title=title, date=date, participants=participants),
        format="transcript",
        mime_type=MARKDOWN,
        title=title,
        metadata={"meeting": meeting_metadata(transcript), "source_format": transcript.format},
    )


def is_transcript_file(mime_type: str | None, filename: str | None) -> bool:
    name = (filename or "").lower()
    return (mime_type or "") in TRANSCRIPT_MIME_TYPES or name.endswith(tuple(TRANSCRIPT_EXTENSIONS))


def audio_mime(filename: str | None, content_type: str | None = None) -> str | None:
    """Audio MIME type of an upload (by extension, then declared type), ``None`` for non-audio files."""
    name = (filename or "").lower()
    for extension, mime in AUDIO_EXTENSIONS.items():
        if name.endswith(extension):
            return mime
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    return declared if declared.startswith("audio/") else None


# --- Turn lines of the rendered Markdown (memory extraction, §F1 attribution) ---------------------------

_TURN_LINE = re.compile(
    r"^(?:\[(?P<ts>\d{2}:\d{2}:\d{2})\]\s*)?(?P<speaker>[^:\[\]\n]{1,60}?) : (?P<text>.+)$"
)


def split_turn_line(line: str, speakers: Iterable[str] | None = None) -> tuple[str | None, str | None, str]:
    """``(timestamp, speaker, text)`` of a rendered turn line (speaker only when known or timestamped)."""
    match = _TURN_LINE.match(line.strip())
    if not match:
        return None, None, line.strip()
    known = set(speakers or ())
    speaker = match.group("speaker").strip()
    if (known and speaker not in known) or (not known and not match.group("ts")) or not _speaker(speaker):
        return None, None, line.strip()
    return match.group("ts"), speaker, match.group("text").strip()


__all__ = [
    "AUDIO_EXTENSIONS",
    "SRT",
    "TRANSCRIPT_EXTENSIONS",
    "VTT",
    "Transcript",
    "Turn",
    "audio_mime",
    "document_from_transcript",
    "extract_meeting",
    "format_timestamp",
    "is_transcript_file",
    "meeting_metadata",
    "parse",
    "parse_cues",
    "parse_text_lines",
    "parse_timestamp",
    "render",
    "split_speaker",
    "split_turn_line",
    "timeline",
]

"""Structure-aware chunking (ARCHITECTURE §7 step 4).

1. The text is split into **units** — headings, sentences, list items, table rows — with exact
   character offsets; Markdown headings (``#``…``######``, as produced by every extractor) maintain
   a section path (« Contexte > Objectifs »).
2. Units are packed greedily into windows of ~``target_tokens`` (350) with an overlap of
   ~``overlap_tokens`` (50) made of whole units, so a chunk never starts or ends mid-sentence when
   avoidable. A sentence longer than the window is cut at word boundaries.
3. A new section starts a new chunk once the current one holds at least ``min_tokens``; small
   sections are merged with the following ones instead of producing tiny chunks.

Each :class:`ChunkSpan` satisfies ``text == source[char_start:char_end]``. Token counts use
:func:`app.search.tokens.estimate_tokens`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.search.tokens import CHARS_PER_TOKEN, estimate_tokens

DEFAULT_TARGET_TOKENS = 350
DEFAULT_OVERLAP_TOKENS = 50
DEFAULT_MIN_TOKENS = 80
MAX_SECTION_DEPTH = 3

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_LIST_OR_TABLE = re.compile(r"^\s*(?:[-*+•·‣◦▪]\s|\d{1,3}[.)]\s|\|)")
#: Sentence end: terminal punctuation (optionally followed by closing quotes/brackets) then space.
_SENTENCE_END = re.compile(r"[.!?…]+[»\"')\]]*(?=\s+)")
_ABBREVIATIONS = frozenset(
    {
        "m", "mm", "mme", "mmes", "mlle", "mlles", "dr", "pr", "me", "st", "ste", "cf", "ex", "etc", "env",
        "p", "pp", "art", "al", "fig", "vol", "no", "n°", "tél", "tel", "av", "bd", "min", "max", "approx",
        "vs", "e.g", "i.e", "c.-à-d", "resp", "déc", "janv", "févr", "avr", "juil", "sept", "oct", "nov",
    }
)  # fmt: skip


@dataclass(slots=True)
class ChunkSpan:
    ordinal: int
    text: str
    char_start: int
    char_end: int
    section: str | None
    token_count: int


@dataclass(slots=True)
class _Unit:
    start: int
    end: int
    section: str | None
    is_heading: bool = False

    @property
    def tokens(self) -> int:
        return max(1, round((self.end - self.start) / CHARS_PER_TOKEN))


def _is_sentence_boundary(text: str, match_start: int) -> bool:
    """Reject splits after abbreviations (« M. Dupont », « p. 12 ») and initials."""
    if text[match_start] != ".":
        return True
    word_start = match_start
    while word_start > 0 and not text[word_start - 1].isspace() and text[word_start - 1] not in "(«\"'":
        word_start -= 1
    word = text[word_start:match_start].lower()
    if not word:
        return True
    if word in _ABBREVIATIONS:
        return False
    return not (len(word) == 1 and word.isalpha())  # initial (« J. Martin »)


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Sentences of ``text[start:end]`` as absolute ``(start, end)`` offsets (whitespace trimmed)."""
    spans: list[tuple[int, int]] = []
    segment = text[start:end]
    cursor = 0
    for match in _SENTENCE_END.finditer(segment):
        if not _is_sentence_boundary(segment, match.start()):
            continue
        spans.append((cursor, match.end()))
        cursor = match.end()
    spans.append((cursor, len(segment)))
    result: list[tuple[int, int]] = []
    for s, e in spans:
        piece = segment[s:e]
        lstrip = len(piece) - len(piece.lstrip())
        rstrip = len(piece) - len(piece.rstrip())
        if e - s - lstrip - rstrip > 0:
            result.append((start + s + lstrip, start + e - rstrip))
    return result


def _split_long(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Cut an over-long span at whitespace so that each piece has at most ``max_chars``."""
    pieces: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > max_chars:
        limit = cursor + max_chars
        cut = text.rfind(" ", cursor + max_chars // 2, limit)
        if cut == -1:
            cut = text.rfind("\n", cursor + max_chars // 2, limit)
        if cut == -1:
            cut = limit
        pieces.append((cursor, cut))
        cursor = cut
        while cursor < end and text[cursor].isspace():
            cursor += 1
    if cursor < end:
        pieces.append((cursor, end))
    return [(s, e) for s, e in pieces if e > s]


def _units(text: str, max_unit_chars: int) -> list[_Unit]:
    units: list[_Unit] = []
    stack: list[tuple[int, str]] = []
    section: str | None = None
    paragraph_start: int | None = None
    paragraph_end = 0

    def flush_paragraph() -> None:
        nonlocal paragraph_start
        if paragraph_start is None:
            return
        for s, e in _sentence_spans(text, paragraph_start, paragraph_end):
            for ps, pe in _split_long(text, s, e, max_unit_chars):
                units.append(_Unit(ps, pe, section))
        paragraph_start = None

    offset = 0
    for line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        content = line.rstrip("\r\n")
        stripped = content.strip()
        line_end = line_start + len(content)
        if not stripped:
            flush_paragraph()
            continue
        heading = _HEADING.match(content)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            stack = [(lvl, name) for lvl, name in stack if lvl < level]
            stack.append((level, title))
            section = " > ".join(name for _, name in stack[:MAX_SECTION_DEPTH]) or None
            lead = len(content) - len(content.lstrip())
            units.append(_Unit(line_start + lead, line_end, section, is_heading=True))
            continue
        if _LIST_OR_TABLE.match(content):
            # List items and table rows are units of their own (never merged into a sentence).
            flush_paragraph()
            lead = len(content) - len(content.lstrip())
            for ps, pe in _split_long(text, line_start + lead, line_end, max_unit_chars):
                units.append(_Unit(ps, pe, section))
            continue
        if paragraph_start is None:
            paragraph_start = line_start + (len(content) - len(content.lstrip()))
        paragraph_end = line_end
    flush_paragraph()
    return units


def chunk_text(
    text: str,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    min_tokens: int = DEFAULT_MIN_TOKENS,
) -> list[ChunkSpan]:
    """Split ``text`` into overlapping, structure-aware chunks (see module docstring)."""
    if not text or not text.strip():
        return []
    target_tokens = max(20, target_tokens)
    overlap_tokens = max(0, min(overlap_tokens, target_tokens // 2))
    max_unit_chars = max(40, int(target_tokens * CHARS_PER_TOKEN))
    units = _units(text, max_unit_chars)
    if not units:
        return []

    windows: list[tuple[int, int]] = []  # (first unit index, last unit index exclusive)
    i = 0
    n = len(units)
    while i < n:
        j = i
        tokens = 0
        while j < n:
            unit = units[j]
            if j > i:
                # Section boundary: close the chunk if it already has enough content.
                if unit.is_heading and tokens >= min_tokens:
                    break
                if tokens + unit.tokens > target_tokens:
                    break
            tokens += unit.tokens
            j += 1
        # Never end a chunk on a heading (it belongs to the next chunk).
        while j - 1 > i and units[j - 1].is_heading:
            j -= 1
        windows.append((i, j))
        if j >= n:
            break
        # Overlap with whole units, unless the next chunk starts a new section.
        k = j
        if not units[j].is_heading and overlap_tokens > 0:
            overlap = 0
            while k - 1 > i and not units[k - 1].is_heading and overlap + units[k - 1].tokens <= overlap_tokens:
                overlap += units[k - 1].tokens
                k -= 1
        i = max(k, i + 1)

    chunks: list[ChunkSpan] = []
    for ordinal, (first, last) in enumerate(windows):
        start = units[first].start
        end = units[last - 1].end
        body = text[start:end]
        section = next((u.section for u in units[first:last] if not u.is_heading), units[first].section)
        chunks.append(
            ChunkSpan(
                ordinal=ordinal,
                text=body,
                char_start=start,
                char_end=end,
                section=section,
                token_count=estimate_tokens(body),
            )
        )
    return chunks

"""Text normalisation applied to every extracted text (ARCHITECTURE §7 step 1).

* Unicode NFC, ligatures (ﬁ, ﬂ…) expanded, soft hyphens and zero-width characters removed;
* line endings unified, control characters dropped, non-breaking spaces turned into spaces;
* hyphenation at line ends repaired (``infor-\\nmation`` → ``information``);
* runs of spaces collapsed, trailing spaces removed, at most one blank line between paragraphs.

Markdown structure (headings, lists, tables) is preserved. :func:`unwrap_lines` additionally joins
hard-wrapped lines inside paragraphs (PDF output).
"""

from __future__ import annotations

import re
import unicodedata

_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"), None)
_SPACES = dict.fromkeys(map(ord, "\u00a0\u202f\u2007\u2009\u200a\u2002\u2003\u2004\u2005\u2006\u3000"), " ")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(?<=[a-zà-öø-ÿ])-\n[ \t]*(?=[a-zà-öø-ÿ])")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_TABS = re.compile(r"\t")

#: Lines starting like this are structure (never merged by :func:`unwrap_lines`).
_STRUCTURAL_LINE = re.compile(r"^\s*(#{1,6}\s|[-*•·‣◦▪]\s|\d{1,3}[.)]\s|\|)")
_SENTENCE_END = re.compile(r"[.!?:;…»\"')\]]$")


def normalize_text(text: str | None) -> str:
    """Normalise ``text`` (see module docstring). Idempotent."""
    if not text:
        return ""
    value = unicodedata.normalize("NFC", text)
    for ligature, replacement in _LIGATURES.items():
        if ligature in value:
            value = value.replace(ligature, replacement)
    value = value.translate(_INVISIBLE).translate(_SPACES)
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n\n")
    value = _CONTROL.sub("", value)
    value = _TABS.sub(" ", value)
    value = _HYPHEN_BREAK.sub("", value)
    value = _MULTI_SPACE.sub(" ", value)
    value = _TRAILING_SPACE.sub("\n", value)
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    value = _MANY_NEWLINES.sub("\n\n", value)
    return value.strip()


def unwrap_lines(text: str) -> str:
    """Join hard-wrapped lines of a paragraph (typical PDF output), keeping lists and headings.

    A line is merged with the next one when it does not end a sentence and the next line starts
    with a lower-case letter or a digit continuation.
    """
    lines = text.split("\n")
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if (
            merged
            and stripped
            and merged[-1].strip()
            and not _STRUCTURAL_LINE.match(line)
            and not _STRUCTURAL_LINE.match(merged[-1])
            and not _SENTENCE_END.search(merged[-1].rstrip())
            and (stripped[0].islower() or stripped[0] in ",;)")
        ):
            merged[-1] = f"{merged[-1].rstrip()} {stripped}"
        else:
            merged.append(line)
    return "\n".join(merged)


def collapse_whitespace(text: str) -> str:
    """Single-line form (titles, excerpts)."""
    return re.sub(r"\s+", " ", text or "").strip()

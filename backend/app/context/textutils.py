"""Small, dependency-free text helpers shared by the context engine.

French-aware normalisation (accent folding, stop words, light prefix stemming), sentence splitting,
shingles and similarity measures used by reranking, deduplication, MMR and extractive compression.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence

#: Prefix length used as a crude but robust French stemmer ("réservation" / "réserver" -> "reserv").
STEM_LENGTH = 6

_WORD = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…;])\s+(?=[A-ZÀ-ÖØ-Ý0-9«\"(\[-])|\n+")
_BULLET = re.compile(r"^\s*(?:[-*•·▪]|\d+[.)])\s+")
_WHITESPACE = re.compile(r"\s+")
_ELISION = re.compile(r"^(?:l|d|j|m|n|s|t|c|qu|jusqu|lorsqu|puisqu)['’]")

FRENCH_STOPWORDS: frozenset[str] = frozenset(
    """
    a ai aie aient aies ait alors as au aucun aucune aupres auquel aura aurai auraient aurais aurait
    aux avaient avais avait avant avec avez aviez avions avoir avons ayant bon car ce ceci cela celle
    celles celui ces cet cette ceux chaque chez ci comme comment dans de des donc dont du elle elles
    en encore entre es est et etaient etais etait etant ete etre eu eux fait faire fois font hors ici
    il ils je jusqu la le les leur leurs lui ma mais me meme memes mes moi mon ne ni non nos notre
    nous on ont or ou par parce pas peu peut plus pour pourquoi qu quand que quel quelle quelles quels
    qui quoi sa sans se selon ses si sien son sont sous soyez sur ta tandis te tes toi ton tous tout
    toute toutes tres tu un une unes uns vers voici voila vont vos votre vous vu y the of and to in for
    on with is are be this that from by an or as at it its doit doivent sera seront etc afin ainsi
    """.split()  # noqa: SIM905 - readable word list
)


def fold(text: str) -> str:
    """Lower-case and strip diacritics (``"Réservation"`` -> ``"reservation"``)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).replace("œ", "oe")


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def stem(word: str) -> str:
    """Light French stemming: plural removal then prefix truncation."""
    if len(word) > 4 and word.endswith(("s", "x")):
        word = word[:-1]
    return word[:STEM_LENGTH]


def words(text: str) -> list[str]:
    """Folded word tokens (elisions such as ``l'``/``d'`` removed)."""
    result: list[str] = []
    for token in _WORD.findall(fold(text)):
        token = _ELISION.sub("", token)
        if token:
            result.append(token)
    return result


def terms(text: str, *, min_length: int = 3) -> list[str]:
    """Stemmed content terms (stop words and very short tokens removed), in order of appearance."""
    result: list[str] = []
    for token in words(text):
        if len(token) < min_length and not token.isdigit():
            continue
        if token in FRENCH_STOPWORDS:
            continue
        result.append(stem(token))
    return result


def key_terms(text: str, *, limit: int = 24) -> list[str]:
    """Distinct stemmed terms of a query, most frequent first (ties keep their original order)."""
    counts: dict[str, int] = {}
    for term in terms(text):
        counts[term] = counts.get(term, 0) + 1
    ordered = sorted(counts, key=lambda t: -counts[t])
    return ordered[:limit]


def term_overlap(query_terms: Sequence[str], text: str) -> float:
    """Share of the query terms present in ``text`` (0..1)."""
    if not query_terms:
        return 0.0
    present = set(terms(text))
    return sum(1 for t in query_terms if t in present) / len(query_terms)


def shingles(text: str, size: int = 3) -> set[tuple[str, ...]]:
    """Word shingles over folded tokens (stop words kept: they matter for near-duplicate detection)."""
    tokens = words(text)
    if len(tokens) < size:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def jaccard[T](a: set[T], b: set[T]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def cosine(a: Sequence[float] | None, b: Sequence[float] | None) -> float | None:
    """Cosine similarity, ``None`` when a vector is missing or dimensions differ."""
    if not a or not b or len(a) != len(b):
        return None
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return None
    return dot / (math.sqrt(na) * math.sqrt(nb))


def split_sentences(text: str) -> list[str]:
    """Split a passage into sentences / bullet lines (Markdown-friendly), whitespace-normalised."""
    sentences: list[str] = []
    for raw in _SENTENCE_BOUNDARY.split(text or ""):
        line = _BULLET.sub("", raw).strip()
        line = line.lstrip("#").strip()
        line = normalize_whitespace(line)
        if line:
            sentences.append(line)
    return sentences


def one_line(text: str) -> str:
    """Collapse a passage to a single Markdown-safe line (used in bullets)."""
    return normalize_whitespace(text.replace("\r", " "))


def preview(text: str, max_chars: int = 280) -> str:
    """Short single-line preview cut at a word boundary."""
    line = one_line(text)
    if len(line) <= max_chars:
        return line
    cut = line[:max_chars]
    boundary = cut.rfind(" ")
    if boundary > max_chars * 0.6:
        cut = cut[:boundary]
    return cut.rstrip(" ,;:") + "…"


def unique_preserving(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

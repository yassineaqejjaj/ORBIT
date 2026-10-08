"""Text analysis for memory relations: similarity, divergence markers and explicit replacements.

Used by :func:`app.memory.lifecycle.detect_relations` (ARCHITECTURE §8) and reusable by the context
assembler (conflict resolution, §9 step 6):

* :func:`cosine`, :func:`lexical_similarity`, :func:`topic_similarity` — dense and lexical
  similarity measures;
* :func:`divergences` — French divergence markers between two statements (negation mismatch,
  differing numeric values, antonym pairs) returned as human-readable French descriptions;
* :func:`replacement_phrase` — detects that a newer statement explicitly replaces an older one
  (« PWA **plutôt qu'une application native** », « **abandon du** login email/mot de passe »);
* :func:`conflict_winner` — the most reliable of two conflicting items
  (validated > proposed, then more recent, then higher confidence).

Everything here is pure (no I/O) and deterministic.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.enums import MemoryKind, MemoryStatus

# --- Normalisation & tokens -----------------------------------------------------------------------

STOPWORDS: frozenset[str] = frozenset(
    """
    a ai aie aient aies ait alors as au aucun aucune aura aurai auraient aurais aurait auras aurez
    auriez aurions aurons auront aussi autre aux avaient avais avait avant avec avez aviez avions avoir
    avons ayant ayez ayons c ca car ce ceci cela celle celles celui cependant ces cet cette ceux chaque
    chez ci comme comment d dans de des deja depuis donc dont du elle elles en encore entre es est et
    etaient etais etait etant ete etes etions etre eu eue eues eurent eus eusse eut eux fait faire fois
    furent fut ici il ils j je jusqu l la le les leur leurs lors lui m ma mais me meme memes mes moi mon
    n ne ni nos notre nous on ont ou par parce pas peu peut peuvent plus pour pourquoi qu quand que quel
    quelle quelles quels qui quoi s sa sans se sera serai seraient serais serait seras serez seriez
    serions serons seront ses si sien soit sommes son sont sous suis sur t ta te tes toi ton tous tout
    toute toutes tres tu un une unes uns vers via voici voila vos votre vous y
    """.split()  # noqa: SIM905 - readable word list
)

_WORD = re.compile(r"[a-z0-9]+")
_ELISION = re.compile(r"\b(?:l|d|j|m|n|s|t|c|qu|jusqu|lorsqu|puisqu)['’]", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


def fold(text: str) -> str:
    """Lower-case and strip accents (``« Élevé »`` → ``« eleve »``)."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def normalize_text(text: str) -> str:
    """Whitespace-collapsed, folded text used for exact-duplicate detection."""
    return _SPACES.sub(" ", fold(text)).strip(" .;:!?-–—")


def _stem(token: str) -> str:
    """Very light French stemming (plural / feminine endings) — enough for term overlap."""
    if token.isdigit() or len(token) <= 3:
        return token
    for suffix in ("ements", "ement", "ations", "ation", "ees", "ee", "es", "s", "x", "e"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def tokens(text: str) -> list[str]:
    """Folded word tokens with French elisions removed (``l'application`` → ``application``)."""
    return _WORD.findall(fold(_ELISION.sub(" ", text or "")))


def content_terms(text: str) -> set[str]:
    """Stemmed, stop-word-free terms of ``text``."""
    return {_stem(tok) for tok in tokens(text) if tok not in STOPWORDS and (len(tok) > 1 or tok.isdigit())}


# --- Similarity -----------------------------------------------------------------------------------


def cosine(u: Sequence[float] | None, v: Sequence[float] | None) -> float:
    """Cosine similarity (0.0 when a vector is missing or null)."""
    if not u or not v or len(u) != len(v):
        return 0.0
    dot = sum(a * b for a, b in zip(u, v, strict=True))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    if nu == 0 or nv == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (nu * nv)))


def _dice(ta: set[str], tb: set[str]) -> float:
    if not ta or not tb:
        return 0.0
    return 2 * len(ta & tb) / (len(ta) + len(tb))


def lexical_similarity(a: str, b: str) -> float:
    """Dice coefficient over content terms (numbers included)."""
    return _dice(content_terms(a), content_terms(b))


#: Label words that say nothing about the topic (« Décision : », « Besoin : »…).
LABEL_TERMS: frozenset[str] = frozenset(
    {"decision", "decid", "besoin", "contraint", "risqu", "fait", "exigenc", "note", "point", "vigilanc"}
)


def topic_terms(text: str) -> set[str]:
    """Content terms without numbers and label words: what a statement is *about*."""
    return {term for term in content_terms(text) if not term[0].isdigit() and term not in LABEL_TERMS}


def topic_similarity(a: str, b: str) -> float:
    """Dice coefficient over :func:`topic_terms` — high for « 720 postes » vs « 650 postes »
    about the same site, which is what contradiction detection needs."""
    return _dice(topic_terms(a), topic_terms(b))


def duplicate_similarity(a: str, b: str) -> float:
    """Lexical similarity for near-duplicate detection (numbers count: 720 ≠ 650)."""
    return lexical_similarity(a, b)


# --- Numbers --------------------------------------------------------------------------------------

_NUMBER = re.compile(
    r"(?<![\w.,-])(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,](\d+))?(?:er|re|ère|ème|e)?(?![\w-])"
)
_UNIT_WORD = re.compile(r"\s*(%|€|k€|m²|m2|[a-zà-ÿ]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NumericValue:
    value: float
    #: Stem of the word following the number (comparison key) and the word as written (display).
    unit: str | None
    unit_label: str | None = None

    @property
    def label(self) -> str:
        return _format_number(self.value)


def _format_number(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def numeric_values(text: str) -> list[NumericValue]:
    """Numbers found in ``text`` with the word that follows them (``720 postes`` → (720, "poste"))."""
    found: list[NumericValue] = []
    for match in _NUMBER.finditer(text or ""):
        integer = re.sub(r"[ \u00a0\u202f]", "", match.group(1))
        raw = f"{integer}.{match.group(2)}" if match.group(2) else integer
        try:
            value = float(raw)
        except ValueError:
            continue
        unit_match = _UNIT_WORD.match(text, match.end())
        unit = unit_label = None
        if unit_match:
            word = fold(unit_match.group(1))
            if word not in STOPWORDS:
                unit, unit_label = _stem(word), unit_match.group(1)
        found.append(NumericValue(value, unit, unit_label))
    return found


def numeric_divergence(a: str, b: str) -> str | None:
    """French description of differing numeric values between ``a`` and ``b`` (``None`` if none)."""
    va, vb = numeric_values(a), numeric_values(b)
    if not va or not vb:
        return None
    by_unit_a: dict[str, set[float]] = {}
    by_unit_b: dict[str, set[float]] = {}
    labels: dict[str, str] = {}
    for item in va:
        if item.unit:
            by_unit_a.setdefault(item.unit, set()).add(item.value)
            labels.setdefault(item.unit, item.unit_label or item.unit)
    for item in vb:
        if item.unit:
            by_unit_b.setdefault(item.unit, set()).add(item.value)
    for unit in sorted(set(by_unit_a) & set(by_unit_b)):
        if by_unit_a[unit].isdisjoint(by_unit_b[unit]):
            left = "/".join(_format_number(v) for v in sorted(by_unit_a[unit]))
            right = "/".join(_format_number(v) for v in sorted(by_unit_b[unit]))
            return f"valeurs numériques divergentes ({left} ≠ {right} {labels[unit]})"
    set_a = {item.value for item in va}
    set_b = {item.value for item in vb}
    if set_a - set_b and set_b - set_a:
        left = "/".join(_format_number(v) for v in sorted(set_a - set_b))
        right = "/".join(_format_number(v) for v in sorted(set_b - set_a))
        return f"valeurs numériques divergentes ({left} ≠ {right})"
    return None


# --- Negation, antonyms, replacement ------------------------------------------------------------------

_NEGATION = re.compile(
    r"\b(?:ne|n['’])\s*(?:\w+['’]?\s+){0,3}?(?:pas|plus|jamais|guere|aucun\w*|rien|nullement)\b"
    r"|\b(?:pas\s+de|pas\s+d['’]|aucun\w*|jamais|abandon\w*|plutot\s+qu\w*|au\s+lieu\s+d\w*|et\s+non)\b",
    re.IGNORECASE,
)

#: Mutually exclusive term pairs, as prefixes of the stems produced by :func:`content_terms`.
ANTONYM_PAIRS: tuple[tuple[str, str], ...] = (
    ("obligatoir", "facultati"),
    ("obligatoir", "optionnel"),
    ("autoris", "interdit"),
    ("activ", "desactiv"),
    ("inclu", "exclu"),
    ("accept", "refus"),
    ("augment", "diminu"),
    ("hauss", "baiss"),
    ("ouvert", "ferm"),
    ("public", "priv"),
    ("intern", "extern"),
    ("synchron", "asynchron"),
    ("centralis", "decentralis"),
    ("nativ", "web"),
    ("natif", "web"),
    ("minimum", "maximum"),
    ("possibl", "impossibl"),
    ("compatibl", "incompatibl"),
    ("valid", "rejet"),
)

_REPLACEMENT = re.compile(
    r"(?:plutôt|plutot)\s+qu(?:e|['’])\s*"
    r"|au\s+lieu\s+(?:de\s+|d['’]|du\s+|des\s+)"
    r"|à\s+la\s+place\s+(?:de\s+|d['’]|du\s+|des\s+)"
    r"|en\s+remplacement\s+(?:de\s+|d['’]|du\s+|des\s+)"
    r"|remplacer?(?:a|ont|ons)?\s+"
    r"|abandon(?:ne|née|nées|nent|ner|nons)?\s+(?:de\s+|du\s+|des\s+|d['’]|la\s+|le\s+|les\s+|l['’])?"
    r"|renon\w*\s+(?:à|a)\s+"
    r"|et\s+non\s+(?:plus\s+)?",
    re.IGNORECASE,
)
_PHRASE_END = re.compile(r"[.;:!?,()\[\]\n«»\"]| et | mais | car ")


def has_negation(text: str) -> bool:
    return bool(_NEGATION.search(fold(text or "")))


_CLAUSE_SPLIT = re.compile(r"[;.!?]\s*")


def _negated_on_shared_topic(text: str, other: str) -> bool:
    """Negation in a clause of ``text`` that talks about ``other``'s subject: « …; les rappels pourraient ne
    pas être reçus » does not contradict a statement that never mentions the reminders."""
    other_terms = content_terms(other)
    return any(
        has_negation(clause) and content_terms(clause) & other_terms
        for clause in _CLAUSE_SPLIT.split(text or "")
        if clause.strip()
    )


def _prefixed(terms: set[str], prefix: str) -> bool:
    return any(term.startswith(prefix) for term in terms)


def antonym_divergence(a: str, b: str) -> str | None:
    ta, tb = content_terms(a), content_terms(b)
    for left, right in ANTONYM_PAIRS:
        a_left, a_right = _prefixed(ta, left), _prefixed(ta, right)
        b_left, b_right = _prefixed(tb, left), _prefixed(tb, right)
        if (a_left and b_right and not a_right and not b_left) or (
            a_right and b_left and not a_left and not b_right
        ):
            return f"termes opposés ({left} / {right})"
    return None


def divergences(a: str, b: str) -> list[str]:
    """Divergence markers between two statements, as French descriptions (empty when consistent)."""
    markers: list[str] = []
    numeric = numeric_divergence(a, b)
    if numeric:
        markers.append(numeric)
    if _negated_on_shared_topic(a, b) != _negated_on_shared_topic(b, a):
        markers.append("négation divergente")
    antonym = antonym_divergence(a, b)
    if antonym:
        markers.append(antonym)
    return markers


def replacement_phrases(text: str) -> list[str]:
    """Phrases introduced by an explicit replacement marker (« plutôt qu'**une application native** »)."""
    phrases: list[str] = []
    for match in _REPLACEMENT.finditer(text or ""):
        rest = text[match.end() : match.end() + 160]
        end = _PHRASE_END.search(rest)
        phrase = (rest[: end.start()] if end else rest).strip()
        if phrase:
            phrases.append(phrase[:120])
    return phrases


def _positive_terms(text: str) -> set[str]:
    """Terms of ``text`` outside its replacement phrases (what the statement asserts)."""
    stripped = text
    for phrase in replacement_phrases(text):
        stripped = stripped.replace(phrase, " ")
    return content_terms(_REPLACEMENT.sub(" ", stripped))


def replacement_phrase(newer: str, older: str) -> str | None:
    """Return the phrase of ``newer`` that explicitly replaces what ``older`` asserts, if any.

    ``newer`` = « L'application sera une PWA plutôt qu'une application native », ``older`` =
    « Application mobile native iOS/Android » → ``"une application native"`` (the distinctive term
    *native* is replaced in ``newer`` and asserted by ``older``).
    """
    positive_new = _positive_terms(newer)
    asserted_old = _positive_terms(older)
    for phrase in replacement_phrases(newer):
        distinctive = content_terms(phrase) - positive_new
        if distinctive & asserted_old:
            return phrase
    return None


# --- Conflict resolution ---------------------------------------------------------------------------


class _Comparable(Protocol):
    status: MemoryStatus
    valid_from: datetime
    confidence: float


_STATUS_RANK: dict[MemoryStatus, int] = {
    MemoryStatus.validated: 2,
    MemoryStatus.proposed: 1,
}


def reliability_key(item: _Comparable) -> tuple[int, float, float]:
    """Sort key: validated > proposed, then more recent ``valid_from``, then confidence."""
    return (
        _STATUS_RANK.get(MemoryStatus(item.status), 0),
        item.valid_from.timestamp() if item.valid_from else 0.0,
        float(item.confidence or 0.0),
    )


def conflict_winner[T: _Comparable](a: T, b: T) -> T:
    """The most reliable of two contradicting items (ARCHITECTURE §8 « Contradiction »)."""
    return a if reliability_key(a) >= reliability_key(b) else b


# --- Kind families -------------------------------------------------------------------------------------

KIND_FAMILIES: tuple[frozenset[MemoryKind], ...] = (
    frozenset({MemoryKind.decision}),
    frozenset({MemoryKind.fact, MemoryKind.constraint, MemoryKind.requirement, MemoryKind.summary}),
    frozenset({MemoryKind.risk}),
    frozenset({MemoryKind.preference}),
    frozenset({MemoryKind.procedure}),
    frozenset({MemoryKind.action}),
)


def kind_family(kind: MemoryKind | str) -> frozenset[MemoryKind]:
    """Kinds that can relate to ``kind`` (supersession/contradiction/deduplication candidates)."""
    value = MemoryKind(kind)
    for family in KIND_FAMILIES:
        if value in family:
            return family
    return frozenset({value})


def format_similarity(value: float) -> str:
    """``0.8213 → "0,82"`` (French decimal)."""
    return f"{value:.2f}".replace(".", ",")


def join_markers(markers: Iterable[str]) -> str:
    return " · ".join(markers)

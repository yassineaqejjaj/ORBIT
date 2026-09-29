"""Personal data detection and redaction (ARCHITECTURE §3 « Données personnelles », §7 step 2).

Detected types (``app.enums.PiiType``):

* ``EMAIL``  — RFC-like addresses;
* ``PHONE``  — French numbers (``06 12 34 56 78``, ``+33 6 12 34 56 78``, ``0033…``) and
  international numbers in ``+CC`` form (8–15 digits);
* ``IBAN``   — any country, validated with the ISO 13616 mod-97 checksum;
* ``CARD``   — payment card numbers (13–19 digits, known issuer prefix, Luhn checksum);
* ``NIR``    — French social security number (sex, year, month, department incl. Corsica 2A/2B,
  commune, order, 2-digit key validated as ``97 - (n mod 97)``);
* ``IP``     — IPv4 addresses;
* ``PERSON`` — names introduced by a civility (``M.``, ``Mme``, ``Mlle``, ``Monsieur``, ``Madame``,
  ``Mademoiselle``, ``Dr``, ``Docteur``, ``Pr``) followed by capitalised words (the civility itself
  is kept in the redacted text: « Mme [PERSONNE] »).

Overlaps are resolved by priority (IBAN > CARD > NIR > EMAIL > PHONE > IP > PERSON) then length.
Redaction replaces each entity with ``app.enums.PII_LABELS`` (``[EMAIL]``, ``[TÉLÉPHONE]``…).
Entity offsets are character offsets in the analysed text.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.enums import PII_LABELS, PiiType

#: Types that make a content sensitive (classification raised to at least C2).
SENSITIVE_PII_TYPES: frozenset[PiiType] = frozenset({PiiType.IBAN, PiiType.CARD, PiiType.NIR})

_PRIORITY: dict[PiiType, int] = {
    PiiType.IBAN: 0,
    PiiType.CARD: 1,
    PiiType.NIR: 2,
    PiiType.EMAIL: 3,
    PiiType.PHONE: 4,
    PiiType.IP: 5,
    PiiType.PERSON: 6,
}


@dataclass(frozen=True, slots=True)
class PiiEntity:
    type: PiiType
    start: int
    end: int
    text: str

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type.value, "start": self.start, "end": self.end}
        if include_text:
            data["text"] = self.text
        return data


@dataclass(frozen=True, slots=True)
class PiiResult:
    entities: list[PiiEntity]
    redacted: str

    @property
    def count(self) -> int:
        return len(self.entities)

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(e.type.value for e in self.entities))

    @property
    def sensitive_types(self) -> set[PiiType]:
        return {e.type for e in self.entities if e.type in SENSITIVE_PII_TYPES}


# --- Validators ---------------------------------------------------------------------------------------


def iban_is_valid(value: str) -> bool:
    """ISO 13616 mod-97 check (spaces ignored)."""
    iban = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    expected_length = _IBAN_LENGTHS.get(iban[:2])
    if expected_length is not None and len(iban) != expected_length:
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def luhn_is_valid(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)]
    if len(digits) < 12:
        return False
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _card_issuer_ok(digits: str) -> bool:
    if digits.startswith("4"):  # Visa
        return len(digits) in (13, 16, 19)
    if re.match(r"^(5[1-5]|2(2[2-9]|[3-6]\d|7[01]|720))", digits):  # Mastercard
        return len(digits) == 16
    if re.match(r"^3[47]", digits):  # American Express
        return len(digits) == 15
    if re.match(r"^(6011|65|64[4-9]|622)", digits):  # Discover / UnionPay
        return 16 <= len(digits) <= 19
    if re.match(r"^35(2[89]|[3-8]\d)", digits):  # JCB
        return 16 <= len(digits) <= 19
    if re.match(r"^3(0[0-5]|[68])", digits):  # Diners
        return 14 <= len(digits) <= 19
    return False


def card_is_valid(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return 13 <= len(digits) <= 19 and _card_issuer_ok(digits) and luhn_is_valid(digits)


def nir_is_valid(value: str) -> bool:
    """French NIR (15 characters without spaces): 13-character number + 2-digit key."""
    compact = re.sub(r"[\s.\-]", "", value).upper()
    match = re.fullmatch(
        r"([1-478])(\d{2})(0[1-9]|1[0-2]|[2-9]\d)(\d{2}|2A|2B)(\d{3})(\d{3})(\d{2})", compact
    )
    if not match:
        return False
    number = compact[:13]
    key = int(compact[13:])
    # Corsica: 2A → 19, 2B → 18 for the checksum computation.
    number = number.replace("2A", "19").replace("2B", "18")
    if not number.isdigit():
        return False
    return 97 - (int(number) % 97) == key


def _phone_digit_count(value: str) -> int:
    return len(re.sub(r"\D", "", value))


# Expected IBAN lengths for common countries (others: generic 15–34 check).
_IBAN_LENGTHS: dict[str, int] = {
    "FR": 27, "DE": 22, "BE": 16, "ES": 24, "IT": 27, "NL": 18, "LU": 20, "CH": 21, "GB": 22,
    "IE": 22, "PT": 25, "AT": 20, "MC": 27, "PL": 28, "SE": 24, "DK": 18, "FI": 18, "NO": 15,
}  # fmt: skip


# --- Patterns ------------------------------------------------------------------------------------------

_EMAIL = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,24}(?![\w-])"
)
_PHONE_FR = re.compile(
    r"(?<![\w+])(?:(?:\+|00)33[\s.\-]?(?:\(0\)[\s.\-]?)?[1-9]|0[1-9])(?:[\s.\-]?\d{2}){4}(?![\w])"
)
_PHONE_INTL = re.compile(r"(?<![\w+])\+(?!33)[1-9]\d{0,2}(?:[\s.\-]?\(?\d{1,4}\)?){2,5}(?![\w])")
_IBAN = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?(?![A-Za-z0-9])"
)
_CARD = re.compile(r"(?<![\d\-])(?:\d[ \-]?){12,18}\d(?![\d\-])")
_NIR = re.compile(
    r"(?<![\dA-Za-z])[1-478][\s.]?\d{2}[\s.]?(?:0[1-9]|1[0-2]|[2-9]\d)[\s.]?(?:\d{2}|2[AB])[\s.]?\d{3}[\s.]?\d{3}[\s.]?\d{2}(?![\dA-Za-z])"
)
_IPV4 = re.compile(
    r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d]|\.\d)"
)
_UPPER = "A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸÆŒ"
_LOWER = "a-zàâäçéèêëîïôöùûüÿæœ"
_NAME_WORD = (
    rf"(?:[{_UPPER}][{_LOWER}]+(?:['’\-][{_UPPER}]?[{_LOWER}]+)*|[{_UPPER}]{{2,}}(?:-[{_UPPER}]{{2,}})?)"
)
_PERSON = re.compile(
    rf"(?<![\w])(?:M\.|Mme\.?|Mlle\.?|Monsieur|Madame|Mademoiselle|Dr\.?|Docteur|Pr\.?)\s+"
    rf"(?P<name>{_NAME_WORD}(?:\s+(?:(?:de|du|des|d'|le|la|van|von)\s+)?{_NAME_WORD}){{0,2}})"
)
#: Capitalised words following a civility that are not names (« Madame la Directrice » never matches).
_NOT_NAMES = frozenset({"Le", "La", "Les", "Un", "Une", "Et", "Ou", "Vous", "Nous", "Merci", "Bonjour"})


def _find_emails(text: str) -> Iterable[PiiEntity]:
    for m in _EMAIL.finditer(text):
        yield PiiEntity(PiiType.EMAIL, m.start(), m.end(), m.group())


def _find_phones(text: str) -> Iterable[PiiEntity]:
    for m in _PHONE_FR.finditer(text):
        yield PiiEntity(PiiType.PHONE, m.start(), m.end(), m.group())
    for m in _PHONE_INTL.finditer(text):
        value = m.group().rstrip(" .-")
        if 8 <= _phone_digit_count(value) <= 15:
            yield PiiEntity(PiiType.PHONE, m.start(), m.start() + len(value), value)


def _find_ibans(text: str) -> Iterable[PiiEntity]:
    for m in _IBAN.finditer(text):
        value = m.group()
        if iban_is_valid(value):
            yield PiiEntity(PiiType.IBAN, m.start(), m.end(), value)


def _find_cards(text: str) -> Iterable[PiiEntity]:
    for m in _CARD.finditer(text):
        value = m.group().strip(" -")
        if card_is_valid(value):
            start = m.start() + (len(m.group()) - len(m.group().lstrip(" -")))
            yield PiiEntity(PiiType.CARD, start, start + len(value), value)


def _find_nirs(text: str) -> Iterable[PiiEntity]:
    for m in _NIR.finditer(text):
        if nir_is_valid(m.group()):
            yield PiiEntity(PiiType.NIR, m.start(), m.end(), m.group())


def _find_ips(text: str) -> Iterable[PiiEntity]:
    for m in _IPV4.finditer(text):
        yield PiiEntity(PiiType.IP, m.start(), m.end(), m.group())


def _find_persons(text: str) -> Iterable[PiiEntity]:
    for m in _PERSON.finditer(text):
        name = m.group("name")
        words = list(re.finditer(r"\S+", name))
        if not words or words[0].group() in _NOT_NAMES:
            continue
        # Drop trailing capitalised function words (« M. Martin Le … »).
        while words and words[-1].group() in _NOT_NAMES:
            words.pop()
        if not words:
            continue
        start = m.start("name")
        end = start + words[-1].end()
        yield PiiEntity(PiiType.PERSON, start, end, text[start:end])


_FINDERS = (_find_ibans, _find_cards, _find_nirs, _find_emails, _find_phones, _find_ips, _find_persons)


def _resolve_overlaps(candidates: list[PiiEntity]) -> list[PiiEntity]:
    ordered = sorted(candidates, key=lambda e: (_PRIORITY[e.type], -(e.end - e.start), e.start))
    kept: list[PiiEntity] = []
    for entity in ordered:
        if any(entity.start < other.end and other.start < entity.end for other in kept):
            continue
        kept.append(entity)
    return sorted(kept, key=lambda e: e.start)


def detect_pii(text: str | None) -> list[PiiEntity]:
    """All non-overlapping PII entities of ``text``, sorted by offset."""
    if not text:
        return []
    candidates: list[PiiEntity] = []
    for finder in _FINDERS:
        candidates.extend(finder(text))
    return _resolve_overlaps(candidates)


def redact(text: str, entities: Sequence[PiiEntity]) -> str:
    """Replace each entity with its label (entities must not overlap; any order)."""
    if not entities:
        return text
    parts: list[str] = []
    cursor = 0
    for entity in sorted(entities, key=lambda e: e.start):
        if entity.start < cursor:
            continue
        parts.append(text[cursor : entity.start])
        parts.append(PII_LABELS[entity.type])
        cursor = entity.end
    parts.append(text[cursor:])
    return "".join(parts)


def analyze(text: str | None) -> PiiResult:
    """Detect and redact in one pass."""
    value = text or ""
    entities = detect_pii(value)
    return PiiResult(entities=entities, redacted=redact(value, entities))


def entities_in_span(entities: Sequence[PiiEntity], text: str, start: int, end: int) -> list[PiiEntity]:
    """Entities of a document overlapping ``[start, end)``, clipped and re-based on the span.

    Used to project document-level detections onto chunks: an entity cut by a chunk boundary is
    clipped so that no fragment of it can leak in the chunk's redacted text.
    """
    result: list[PiiEntity] = []
    for entity in entities:
        if entity.end <= start or entity.start >= end:
            continue
        clip_start = max(entity.start, start)
        clip_end = min(entity.end, end)
        result.append(PiiEntity(entity.type, clip_start - start, clip_end - start, text[clip_start:clip_end]))
    return result


def redacted_offsets(entities: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """Offsets of each entity's label in the redacted text (entities sorted by ``start``)."""
    offsets: list[tuple[int, int]] = []
    delta = 0
    for entity in sorted(entities, key=lambda e: int(e["start"])):
        label = PII_LABELS[PiiType(entity["type"])]
        start = int(entity["start"]) + delta
        offsets.append((start, start + len(label)))
        delta += len(label) - (int(entity["end"]) - int(entity["start"]))
    return offsets


def redact_value(value: Any) -> Any:
    """Recursively redact PII in strings of a JSON-like structure (metadata shown to viewers)."""
    if isinstance(value, str):
        return analyze(value).redacted
    if isinstance(value, Mapping):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value

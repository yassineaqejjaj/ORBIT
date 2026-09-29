"""Automatic classification C0–C3 (ARCHITECTURE §3, §7 step 3).

``level = max(source default, declared level, keyword rules, sensitive PII ⇒ ≥ C2, LLM)``.
The result never lowers the declared/source level; each contribution is explained in French in
``reasons`` (shown on the document page and in the audit trail).

Keyword rules (French) are deliberately conservative so that ordinary project documents stay at
their declared level:

* explicit markings — « Classification : C2 », « Strictement confidentiel », « Secret »,
  « Diffusion restreinte », « Document confidentiel »… in the title or as a standalone line;
* sensitive topics — salaires / rémunération, budget, contrat, marge, négociation, prix, données
  bancaires… ⇒ C2 when at least three distinct topics appear (two for HR/pay topics);
* sensitive personal data (IBAN, carte bancaire, NIR) ⇒ at least C2.

When an LLM is configured (``ORBIT_LLM_*``) it may only **raise** the level.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.enums import PiiType, classification_code, classification_label
from app.ingestion.pii import SENSITIVE_PII_TYPES, PiiEntity

logger = logging.getLogger("orbit.classifier")

LLM_MAX_CHARS = 6000

_LEVEL_WORDS = {"c0": 0, "public": 0, "c1": 1, "interne": 1, "c2": 2, "confidentiel": 2, "c3": 3, "secret": 3}

#: Explicit classification statements (« Classification : C2 », « Niveau de sensibilité : Secret »).
_EXPLICIT_LEVEL = re.compile(
    r"(?:classification|niveau\s+de\s+(?:classification|sensibilit[ée]|confidentialit[ée])|sensibilit[ée])"
    r"\s*[:=\-–]\s*(c[0-3]|public|interne|confidentiel(?:le)?|secret)\b",
    re.IGNORECASE,
)

#: Markings (checked on the title and on standalone lines only).
_MARKINGS_C3 = re.compile(
    r"^\W*(?:tr[èe]s\s+secret|secret(?:\s+d[ée]fense)?|strictement\s+confidentiel(?:le)?|"
    r"diffusion\s+tr[èe]s\s+restreinte|confidentiel(?:le)?\s+direction)\W*$",
    re.IGNORECASE,
)
_MARKINGS_C2 = re.compile(
    r"^\W*(?:confidentiel(?:le)?|document\s+confidentiel|usage\s+restreint|diffusion\s+restreinte|"
    r"ne\s+pas\s+diffuser|diffusion\s+limit[ée]e)\W*$",
    re.IGNORECASE,
)
_INLINE_MARKINGS_C3 = re.compile(
    r"\b(strictement\s+confidentiel(?:le)?|tr[èe]s\s+secret|secret\s+d[ée]fense)\b", re.I
)
_INLINE_MARKINGS_C2 = re.compile(
    r"\b(document\s+confidentiel|diffusion\s+restreinte|ne\s+pas\s+diffuser)\b", re.I
)
_TITLE_C3 = re.compile(
    r"\b(tr[èe]s\s+secret|secret\s+d[ée]fense|strictement\s+confidentiel(?:le)?)\b", re.IGNORECASE
)
_TITLE_C2 = re.compile(r"\b(confidentiel(?:le)?|restreint)\b", re.IGNORECASE)

#: Sensitive topics: label → pattern. HR/pay topics weigh double.
_TOPICS: dict[str, re.Pattern[str]] = {
    "salaire": re.compile(r"\bsalaires?\b|\bsalarial(?:e|es|aux)?\b", re.I),
    "rémunération": re.compile(r"\br[ée]mun[ée]rations?\b|\bprimes?\s+(?:annuelles?|variables?)\b", re.I),
    "budget": re.compile(r"\bbudg[ée]t(?:s|aire|aires)?\b", re.I),
    "contrat": re.compile(r"\bcontrats?\b|\bcontractuel(?:le|s|les)?\b", re.I),
    "marge": re.compile(r"\bmarges?\b(?!\s+de\s+manœuvre)", re.I),
    "négociation": re.compile(r"\bn[ée]gociations?\b|\bn[ée]gocier\b", re.I),
    "prix": re.compile(
        r"\bprix\s+(?:n[ée]goci[ée]s?|unitaires?|de\s+vente)\b|\btarifs?\s+n[ée]goci[ée]s?\b", re.I
    ),
    "données bancaires": re.compile(r"\b(?:rib|iban|coordonn[ée]es\s+bancaires)\b", re.I),
    "licenciement": re.compile(r"\blicenciements?\b|\brupture\s+conventionnelle\b|\bplan\s+social\b", re.I),
    "évaluation individuelle": re.compile(r"\b[ée]valuations?\s+(?:annuelles?|individuelles?)\b", re.I),
    "mot de passe": re.compile(r"\bmots?\s+de\s+passe\b|\bidentifiants?\s+de\s+connexion\b", re.I),
    "fusion-acquisition": re.compile(
        r"\bfusions?[\s-]acquisitions?\b|\brachat\s+de\s+la\s+soci[ée]t[ée]\b", re.I
    ),
}
_HR_TOPICS = frozenset({"salaire", "rémunération", "licenciement", "évaluation individuelle"})
TOPIC_THRESHOLD = 3


@dataclass(slots=True)
class ClassificationResult:
    level: int
    reasons: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    sensitive_pii: list[str] = field(default_factory=list)
    llm_level: int | None = None

    @property
    def code(self) -> str:
        return classification_code(self.level)


def _level_from_word(word: str) -> int | None:
    key = word.lower()
    if key.startswith("confidentiel"):
        key = "confidentiel"
    return _LEVEL_WORDS.get(key)


def keyword_level(text: str, title: str | None = None) -> tuple[int, list[str], list[str]]:
    """Level suggested by the French keyword rules, with reasons and matched keywords."""
    level = 0
    reasons: list[str] = []
    keywords: list[str] = []

    explicit = [_level_from_word(m.group(1)) for m in _EXPLICIT_LEVEL.finditer(f"{title or ''}\n{text}")]
    explicit_levels = [lvl for lvl in explicit if lvl is not None]
    if explicit_levels:
        top = max(explicit_levels)
        if top > 0:
            level = max(level, top)
            reasons.append(f"mention explicite de classification : {classification_code(top)}")

    marking_level = 0
    marking: str | None = None
    if title and _TITLE_C3.search(title):
        marking_level, marking = 3, _TITLE_C3.search(title).group(1)  # type: ignore[union-attr]
    elif title and _TITLE_C2.search(title):
        marking_level, marking = 2, _TITLE_C2.search(title).group(1)  # type: ignore[union-attr]
    for line in text.splitlines():
        stripped = line.strip().strip("*_#>").strip()
        if not stripped or len(stripped) > 60:
            continue
        if _MARKINGS_C3.match(stripped) and marking_level < 3:
            marking_level, marking = 3, stripped
        elif _MARKINGS_C2.match(stripped) and marking_level < 2:
            marking_level, marking = 2, stripped
    if marking_level < 3 and (inline := _INLINE_MARKINGS_C3.search(text)):
        marking_level, marking = 3, inline.group(1)
    if marking_level < 2 and (inline := _INLINE_MARKINGS_C2.search(text)):
        marking_level, marking = 2, inline.group(1)
    if marking_level and marking:
        level = max(level, marking_level)
        reasons.append(f"marquage « {marking.strip()} » : {classification_code(marking_level)}")
        keywords.append(marking.strip().lower())

    haystack = f"{title or ''}\n{text}"
    topics = [label for label, pattern in _TOPICS.items() if pattern.search(haystack)]
    weight = sum(2 if topic in _HR_TOPICS else 1 for topic in topics)
    if topics and weight >= TOPIC_THRESHOLD:
        level = max(level, 2)
        reasons.append(f"sujets sensibles ({', '.join(topics)}) : C2")
        keywords.extend(topics)
    return level, reasons, keywords


def pii_level(entities: Iterable[PiiEntity]) -> tuple[int, list[str]]:
    sensitive = sorted({e.type.value for e in entities if e.type in SENSITIVE_PII_TYPES})
    return (2, sensitive) if sensitive else (0, [])


_PII_NAMES = {PiiType.IBAN.value: "IBAN", PiiType.CARD.value: "carte bancaire", PiiType.NIR.value: "NIR"}

_LLM_SYSTEM = (
    "Tu es un assistant de classification documentaire. Niveaux : 0 = Public, 1 = Interne, "
    "2 = Confidentiel (données personnelles sensibles, finances, contrats, RH), 3 = Secret "
    "(stratégie, négociations, montants contractuels, fusions). Réponds uniquement en JSON : "
    '{"level": <0-3>, "reason": "<justification courte en français>"}.'
)


async def llm_level(text: str, title: str | None) -> tuple[int | None, str | None]:
    """Optional LLM opinion (``None`` when disabled or unusable)."""
    from app.llm import client as llm_client

    if not llm_client.is_enabled():
        return None, None
    excerpt = text[:LLM_MAX_CHARS]
    answer = await llm_client.complete_json(
        _LLM_SYSTEM, f"Titre : {title or '(sans titre)'}\n\nContenu :\n{excerpt}", max_tokens=200
    )
    if not isinstance(answer, dict):
        return None, None
    try:
        level = int(answer.get("level"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, None
    if not 0 <= level <= 3:
        return None, None
    reason = str(answer.get("reason") or "").strip()[:300] or None
    return level, reason


async def classify(
    text: str,
    *,
    title: str | None = None,
    source_default: int = 1,
    declared: int | None = None,
    pii_entities: Iterable[PiiEntity] = (),
    use_llm: bool = True,
) -> ClassificationResult:
    """Compute the classification (never below ``source_default`` / ``declared``)."""
    reasons = [f"défaut de la source : {classification_code(source_default)}"]
    level = int(source_default)
    if declared is not None:
        reasons.append(f"niveau déclaré : {classification_code(declared)}")
        level = max(level, int(declared))

    kw_level, kw_reasons, keywords = keyword_level(text, title)
    reasons.extend(kw_reasons)
    level = max(level, kw_level)

    entities = list(pii_entities)
    p_level, sensitive = pii_level(entities)
    if p_level:
        names = ", ".join(_PII_NAMES.get(s, s) for s in sensitive)
        reasons.append(f"données personnelles sensibles ({names}) : C2 minimum")
        level = max(level, p_level)

    result = ClassificationResult(level=level, reasons=reasons, keywords=keywords, sensitive_pii=sensitive)
    if use_llm:
        try:
            llm, why = await llm_level(text, title)
        except Exception as exc:  # the LLM is optional: never fail the ingestion because of it
            logger.warning("LLM classification failed: %s", exc)
            llm, why = None, None
        if llm is not None:
            result.llm_level = llm
            if llm > result.level:
                result.level = llm
                result.reasons.append(
                    f"analyse LLM : {classification_code(llm)} ({classification_label(llm)})"
                    + (f" — {why}" if why else "")
                )
    return result

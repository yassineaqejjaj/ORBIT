"""LLM-assisted memory extraction (F3, docs/FEATURES.md).

A structured prompt asks the optional LLM for memory « cards »::

    {"cards": [{"kind", "title", "statement", "decided_by"?, "decided_at"?, "rationale"?,
                "confidence" (0-1), "confidence_reason", "source_quote"}]}

The answer is validated with pydantic, card by card. ``source_quote`` must be a (normalized) substring
of the fragment that was sent, otherwise the card is rejected as hallucinated. Accepted cards become
extraction :class:`~app.memory.extractor.Statement` objects that are merged with the rule-based ones by
the extractor (existing deduplication).

Guardrail: a fragment classified above the ceiling is never sent (deterministic extraction only); PII
is masked before sending when ``ORBIT_LLM_REDACT_PII`` is on. Calls, tokens and skips are counted in
:class:`LLMExtractionStats` (job step ``extract_memory``).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.enums import MemoryKind, SourceKind
from app.llm import client as llm
from app.llm import guardrail
from app.models import Chunk, Document

logger = logging.getLogger("orbit.memory.llm_extraction")

LLM_MAX_CHARS = 6000
MAX_CARDS = 40
MIN_QUOTE_LENGTH = 12

SYSTEM_PROMPT = (
    "Tu extrais la mémoire d'un projet à partir d'un fragment de document (en français). "
    "Identifie uniquement les décisions, besoins utilisateurs, contraintes, risques et faits chiffrés "
    "explicitement présents dans le fragment. Pour chacun, produis une fiche :\n"
    '- "kind" : "decision" | "requirement" | "constraint" | "risk" | "fact" ;\n'
    '- "title" : titre court (≤ 90 caractères) ;\n'
    '- "statement" : l\'énoncé autonome, fidèle au texte ;\n'
    '- "decided_by" : qui a décidé (personne, rôle ou instance) si le texte le dit, sinon null ;\n'
    '- "decided_at" : date de la décision (AAAA-MM-JJ) si le texte la donne, sinon null ;\n'
    '- "rationale" : la justification donnée par le texte, sinon null ;\n'
    '- "confidence" : nombre entre 0 et 1 ; "confidence_reason" : pourquoi ce niveau ;\n'
    '- "source_quote" : passage COPIÉ MOT POUR MOT du fragment qui justifie la fiche.\n'
    "N'invente rien : chaque information doit figurer dans le fragment. "
    'Réponds uniquement en JSON : {"cards": [...]} — {"cards": []} si rien n\'est pertinent.'
)

_QUOTES = str.maketrans({"’": "'", "‘": "'", "«": '"', "»": '"', "“": '"', "”": '"', "–": "-", "—": "-"})
_EMPHASIS = re.compile(r"(\*\*|__|`|\*)")


def normalize_quote(text: str) -> str:
    """Normalization used for grounding checks: case, accents, quotes, dashes, emphasis, whitespace."""
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    folded = _EMPHASIS.sub("", folded).casefold()
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", folded) if not unicodedata.combining(ch))
    return " ".join(folded.split()).strip(" .;:")


def is_grounded(quote: str, fragment: str) -> bool:
    normalized = normalize_quote(quote)
    return len(normalized) >= MIN_QUOTE_LENGTH and normalized in normalize_quote(fragment)


class MemoryCard(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: Literal["decision", "requirement", "constraint", "risk", "fact"]
    title: str = Field(min_length=1, max_length=300)
    statement: str = Field(min_length=12, max_length=700)
    decided_by: str | None = Field(default=None, max_length=200)
    decided_at: date | None = None
    rationale: str | None = Field(default=None, max_length=1200)
    confidence: float = Field(ge=0, le=1)
    confidence_reason: str = Field(default="", max_length=400)
    source_quote: str = Field(min_length=MIN_QUOTE_LENGTH, max_length=1500)

    @field_validator("decided_by", "rationale", mode="before")
    @classmethod
    def _empty_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a", "inconnu"}:
            return None
        return value

    @field_validator("decided_at", mode="before")
    @classmethod
    def _lenient_date(cls, value: Any) -> Any:
        if isinstance(value, str):
            match = re.match(r"\s*(\d{4}-\d{2}-\d{2})", value)
            return match.group(1) if match else None
        return value


class CardsAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cards: list[dict[str, Any]] = Field(max_length=200)


@dataclass(slots=True)
class LLMExtractionStats:
    calls: int = 0
    tokens: int = 0
    skipped_guardrail: int = 0
    invalid_answers: int = 0
    rejected_cards: int = 0
    accepted_cards: int = 0

    def counters(self) -> dict[str, int]:
        return {
            "llm_calls": self.calls,
            "llm_tokens": self.tokens,
            "skipped_guardrail": self.skipped_guardrail,
            "llm_cards": self.accepted_cards,
            "llm_rejected": self.rejected_cards,
        }


def parse_cards(text: str | None, fragment: str) -> tuple[list[MemoryCard], int] | None:
    """Validated, grounded cards of an answer and the number of rejected ones (``None``: invalid JSON)."""
    data = llm.parse_json(text)
    try:
        answer = CardsAnswer.model_validate(data)
    except ValidationError:
        return None
    cards: list[MemoryCard] = []
    rejected = 0
    for raw in answer.cards[:MAX_CARDS]:
        try:
            card = MemoryCard.model_validate(raw)
        except ValidationError:
            rejected += 1
            continue
        if not is_grounded(card.source_quote, fragment):
            logger.info("LLM card rejected (quote not found in the fragment): %.80s", card.source_quote)
            rejected += 1
            continue
        cards.append(card)
    return cards, rejected


async def extract_cards(
    document: Document, chunk: Chunk, source_kind: SourceKind, stats: LLMExtractionStats
) -> list[MemoryCard] | None:
    """Cards proposed by the LLM for one fragment; ``None`` when disabled, blocked or failed."""
    if not llm.is_enabled():
        return None
    level = max(int(chunk.classification), int(document.classification))
    if not guardrail.allows(level):
        stats.skipped_guardrail += 1
        guardrail.record_skip(guardrail.REASON_CLASSIFICATION)
        return None
    fragment = guardrail.prepare(chunk.text_redacted[:LLM_MAX_CHARS])
    section = f"\nSection : {chunk.section}" if chunk.section else ""
    user = (
        f"Document : {document.title}\nType de source : {source_kind.value}{section}"
        f"\n\nFragment :\n{fragment}"
    )
    stats.calls += 1
    result = await llm.generate(SYSTEM_PROMPT, user, json_mode=True, max_tokens=1800, classification=level)
    if result is None:
        return None
    stats.tokens += result.tokens
    parsed = parse_cards(result.text, fragment)
    if parsed is None:
        stats.invalid_answers += 1
        logger.warning("LLM extraction answer is not valid card JSON (document %s)", document.id)
        return None
    cards, rejected = parsed
    stats.rejected_cards += rejected
    stats.accepted_cards += len(cards)
    return cards


def card_kind(card: MemoryCard) -> MemoryKind:
    return MemoryKind(card.kind)


__all__ = [
    "SYSTEM_PROMPT",
    "CardsAnswer",
    "LLMExtractionStats",
    "MemoryCard",
    "card_kind",
    "extract_cards",
    "is_grounded",
    "normalize_quote",
    "parse_cards",
]

"""Memory extraction from ingested documents (ARCHITECTURE §7 step 7, job ``extract_memory``).

For each active chunk of the document's current version, statements are extracted with French
rules (or with the optional LLM, falling back to the rules on any error):

* **decision** — « Décision : », « Nous avons décidé », « il est décidé », « le comité a validé »…,
  or a bullet under a « Décisions » heading;
* **requirement** — « Besoin : », « Exigence : », « En tant que … je veux … », « Les utilisateurs
  veulent / souhaitent … »;
* **constraint** — « Contrainte : », « doit », « ne doit pas », « obligatoire »…;
* **risk** — « Risque : », « risque de … », « Point de vigilance : »; field feedback complaints;
* **fact** — numeric statements (« Le site de Lyon compte 720 postes », « … est de … »).

Items are created ``proposed``, or ``validated`` when the source is a meeting record note (« compte
rendu », « CR », « comité », « réunion », « sprint review »…) and the line starts with
« Décision : ». Text comes from ``chunks.text_redacted`` (no personal data leaks into memory).
Near-duplicates of existing items (similarity > 0.93, no divergence) get an extra provenance row
instead of a new item. Each new item then goes through supersession/contradiction detection.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    MEMORY_KIND_LABELS,
    ChunkStatus,
    DocumentStatus,
    MemoryEventType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RelationType,
    SourceKind,
    SourceTrust,
)
from app.ingestion.queue import PermanentJobError, track_step
from app.memory import lifecycle, poisoning
from app.memory.conflicts import content_terms, fold, kind_family, normalize_text
from app.memory.llm_extraction import (
    LLMExtractionStats,
    MemoryCard,
    card_kind,
    extract_cards,
    normalize_quote,
)
from app.models import Chunk, Document, IngestionJob, MemoryItem, MemoryProvenance, Relation, Source
from app.schemas.memory import MemoryIn, ProvenanceIn
from app.services import audit
from app.services.audit import Actor, AuditAction

logger = logging.getLogger("orbit.memory.extractor")

DUPLICATE_SIMILARITY = 0.93
TITLE_MAX_LENGTH = 90
MIN_STATEMENT_LENGTH = 12
MAX_STATEMENT_LENGTH = 700
MAX_ITEMS_PER_DOCUMENT = 80
DEDUPE_POOL = 500
DEDUPE_SHORTLIST = 4
LLM_MAX_CHARS = 6000

# --- Rules -------------------------------------------------------------------------------------------

_BULLET = re.compile(r"^\s*(?:[-*•▪◦·>]+|\d{1,3}[.)]|[a-z][.)])\s+", re.IGNORECASE)
_EMPHASIS = re.compile(r"(\*\*|__|`)")
_HEADING = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÉÈÊÀÂÎÔÛÇ«\"(\[])")

_LABEL = re.compile(
    r"^(?P<label>d[ée]cisions?|besoins?|exigences?|user\s+story|contraintes?|risques?|"
    r"points?\s+de\s+vigilance|faits?|proc[ée]dures?|checklists?|conventions?|"
    r"d[ée]finition\s+(?:de\s+(?:termin[ée]|fini|pr[êe]t)|of\s+done)|dod|gabarits?)\s*(?:n[°o]\s*\d+\s*)?\s*[:：]\s*(?P<body>.+)$",
    re.IGNORECASE,
)
_LABEL_KINDS: tuple[tuple[str, MemoryKind], ...] = (
    ("decision", MemoryKind.decision),
    ("besoin", MemoryKind.requirement),
    ("exigence", MemoryKind.requirement),
    ("user story", MemoryKind.requirement),
    ("contrainte", MemoryKind.constraint),
    ("risque", MemoryKind.risk),
    ("point", MemoryKind.risk),
    ("fait", MemoryKind.fact),
    ("procedure", MemoryKind.procedure),
    ("checklist", MemoryKind.procedure),
    ("convention", MemoryKind.procedure),
    ("definition", MemoryKind.procedure),
    ("dod", MemoryKind.procedure),
    ("gabarit", MemoryKind.procedure),
)
_SECTION_KINDS: tuple[tuple[re.Pattern[str], MemoryKind], ...] = (
    (re.compile(r"\b(?:releve des )?decisions?\b"), MemoryKind.decision),
    (re.compile(r"\brisques?\b|\bpoints? de vigilance\b"), MemoryKind.risk),
    (
        re.compile(
            r"\bdefinitions? (?:of done|de (?:termine|fini|pret))\b|\bconventions?\b|\bchecklists?\b|"
            r"\bprocedures?\b|\bbonnes pratiques\b|\bfacons de faire\b|\bgabarits?\b"
        ),
        MemoryKind.procedure,
    ),
    (re.compile(r"\bcontraintes?\b"), MemoryKind.constraint),
    (re.compile(r"\bbesoins?\b|\bexigences?\b|\buser stories\b|\battentes\b"), MemoryKind.requirement),
)

#: Lines that are document metadata, never memory (« Date : », « Participants : »…).
_METADATA = re.compile(
    r"^(?:date|participants?|presents?|absents?|excuses?|redacteurs?|auteurs?|lieu|heure|ordre du jour|"
    r"version|statut|objet|destinataires?|diffusion|reference|copie|animateur|duree|prochaine reunion)\s*:",
)

_DECISION = re.compile(
    r"\b(?:nous avons decide|avons decide|il (?:est|a ete) decide|(?:a|ont) ete decide|"
    r"(?:le|la) (?:comite|direction|equipe|copil)\s+(?:a\s+)?(?:decide|valide|acte|arbitre|retenu)|"
    r"decision (?:a ete |est )?prise|il (?:est|a ete) acte|nous retenons|a ete retenue?)\b"
)
_DECISION_PREFIX = re.compile(
    r"^(?:nous avons décidé|avons décidé|il (?:est|a été) décidé|(?:le|la) (?:comité|direction|équipe|copil)"
    r"\s+(?:a\s+)?(?:décidé|validé|acté|arbitré|retenu)|il (?:est|a été) acté)"
    r"\s*(?:de\s+|d['’]|que\s+|qu['’]|:\s*)?",
    re.IGNORECASE,
)
_USER_STORY = re.compile(
    r"^en tant qu(?:e|['’])\s*(?P<role>[^,]{2,80}),\s*je\s+(?:veux|souhaite|voudrais|dois pouvoir|peux|"
    r"aimerais|veux pouvoir)\s+(?P<want>.+)$",
    re.IGNORECASE,
)
_WANT_END = re.compile(r"\s+(?:afin (?:de|d['’]|que)|pour (?:que|pouvoir|ne pas)|de (?:façon|manière) à)\b")
_USERS_WANT = re.compile(
    r"\b(?:les |des |nos |certains )?(?:utilisateurs?|collaborateurs?|clients?|salaries|employes|managers?|"
    r"usagers?|participants?|pilotes?)\s+(?:veulent|souhaitent|attendent|demandent|aimeraient|voudraient|"
    r"ont besoin|reclament|expriment le besoin)\b"
    r"|\bil faut (?:pouvoir|permettre)\b|\bbesoin (?:de|d')\b"
)
_RISK = re.compile(r"\brisques? (?:de|d'|que|qu'|d'une?|majeur|principal|identifie)\b|\bpoint de vigilance\b")
#: §D1 procedural statements (definitions of done, conventions, checklists, mandatory steps).
_PROCEDURE = re.compile(
    r"\b(?:est (?:consideree? |considerees? )?terminee?s? (?:quand|lorsque|si|des que)|definition of done|"
    r"definition de (?:termine|fini|pret)|par convention|la convention (?:est|veut)|"
    r"avant (?:de |chaque )(?:livrer|merger|deployer|livraison|mise en production|release)|"
    r"chaque (?:pull request|pr|merge request|livraison|user story|ticket|story) doit|"
    r"etapes? (?:a suivre|obligatoires?))\b"
)
_CONSTRAINT = re.compile(
    r"\b(?:ne doit pas|ne doivent pas|doit|doivent|obligatoire(?:ment)?|imperati(?:f|ve|vement)|interdit|"
    r"exige que|au plus tard|au maximum|au minimum|conformite|conforme (?:a|au|aux))\b"
)
_FEEDBACK_COMPLAINT = re.compile(
    r"\b(?:impossible de|n'arrive pas|ne (?:fonctionne|marche|se lit|charge|s'affiche) pas|bug|plante|"
    r"difficile de|trop (?:long|lent|compliquee?)|lent|ne trouve pas|pas pratique|galere)\b"
)
_NUMBER = re.compile(r"\d")
_DANGLING_PRONOUN = re.compile(r"^(?:il|elle|ils|elles)\s")
_FACT = re.compile(
    r"\b(?:compte(?! rendu)|comptent|dispose de|disposent de|est de|sont de|s'eleve a|s'elevent a|"
    r"totalise|represente|"
    r"atteint|contient|comporte|recense|il y a|soit)\b"
    r"|\d[\d  .,]*\s*(?:postes?|salles?|bureaux|sites?|etages?|collaborateurs?|utilisateurs?|salaries|"
    r"personnes|m2|m²|%|reservations?|badges?|places?|licences?|jours?|semaines?|mois|euros?|€|k€)\b"
)
_MEETING = re.compile(
    r"compte[- ]rendu|\bcomite\b|\breunion\b|sprint review|\bcopil\b|\batelier\b|kick-?off|retrospective"
)
_MEETING_CR = re.compile(r"(?:^|[\s(\[:])CR(?:\s|$|[-:])")


@dataclass(slots=True)
class Statement:
    """A classified sentence of a chunk."""

    kind: MemoryKind
    title: str
    content: str
    confidence: float
    explicit_decision: bool
    rule: str
    #: Memory-card fields (LLM extraction only).
    quote: str | None = None
    rationale: str | None = None
    decided_by: str | None = None
    confidence_reason: str | None = None
    #: §F1 meeting action item (owner, due date, speaker, timestamp).
    action_meta: dict[str, Any] | None = None


@dataclass(slots=True)
class Candidate:
    statement: Statement
    chunks: list[Chunk] = field(default_factory=list)
    vector: list[float] | None = None

    @property
    def text(self) -> str:
        return f"{self.statement.title}\n{self.statement.content}"


@dataclass(slots=True)
class ExtractionResult:
    created: list[MemoryItem] = field(default_factory=list)
    provenance_added: int = 0
    skipped_duplicates: int = 0
    superseded: int = 0
    conflicts: int = 0
    obsoleted: int = 0
    used_llm: bool = False
    llm: LLMExtractionStats = field(default_factory=LLMExtractionStats)

    def counters(self) -> dict[str, int]:
        by_kind = Counter(MemoryKind(item.kind).value for item in self.created)
        return {
            "created": len(self.created),
            "validated": sum(1 for item in self.created if item.status == MemoryStatus.validated),
            "provenance_added": self.provenance_added,
            "duplicates": self.skipped_duplicates,
            "superseded": self.superseded,
            "conflicts": self.conflicts,
            "obsoleted": self.obsoleted,
            **self.llm.counters(),
            **{f"kind_{kind}": count for kind, count in by_kind.items()},
        }

    def detail(self) -> str:
        if not self.created and not self.provenance_added:
            return "Aucun élément de mémoire détecté"
        by_kind = Counter(MemoryKind(item.kind) for item in self.created)
        parts = [f"{count} {MEMORY_KIND_LABELS[kind].lower()}(s)" for kind, count in by_kind.most_common()]
        summary = f"{len(self.created)} item(s) créé(s)"
        if parts:
            summary += f" ({', '.join(parts)})"
        extras = []
        if self.provenance_added:
            extras.append(f"{self.provenance_added} source(s) ajoutée(s) à des items existants")
        if self.superseded:
            extras.append(f"{self.superseded} remplacement(s)")
        if self.conflicts:
            extras.append(f"{self.conflicts} contradiction(s)")
        if self.obsoleted:
            extras.append(f"{self.obsoleted} item(s) absent(s) de la nouvelle version marqué(s) obsolète(s)")
        if self.used_llm:
            extras.append(
                f"extraction assistée par LLM ({self.llm.calls} appel(s), {self.llm.tokens} jetons"
                + (f", {self.llm.rejected_cards} fiche(s) rejetée(s)" if self.llm.rejected_cards else "")
                + ")"
            )
        if self.llm.skipped_guardrail:
            extras.append(f"{self.llm.skipped_guardrail} fragment(s) non envoyé(s) au LLM (garde-fou)")
        return " · ".join([summary, *extras])


# --- Text helpers -----------------------------------------------------------------------------------------


def _clean_line(line: str) -> str:
    line = _EMPHASIS.sub("", line)
    line = _BULLET.sub("", line)
    return " ".join(line.split()).strip()


def _capitalize(text: str) -> str:
    for index, char in enumerate(text):
        if char.isalpha():
            return text[:index] + char.upper() + text[index + 1 :]
    return text


def make_title(text: str, limit: int = TITLE_MAX_LENGTH) -> str:
    """Short, capitalised title (≤ ``limit`` characters, cut on a word boundary)."""
    title = " ".join(text.split()).strip(" .;:,-–—")
    if len(title) > limit:
        cut = title[: limit - 1]
        if " " in cut[limit // 2 :]:
            cut = cut[: cut.rfind(" ")]
        title = cut.rstrip(" ,;:-–—(") + "…"
    return _capitalize(title)


def _story_title(body: str) -> str | None:
    match = _USER_STORY.match(body.strip())
    if not match:
        return None
    want = match.group("want").strip().rstrip(".")
    end = _WANT_END.search(want)
    if end:
        want = want[: end.start()]
    role = match.group("role").strip()
    return make_title(f"{want} ({role})")


def _logical_lines(text: str) -> Iterator[str]:
    """Raw lines with hard-wrapped paragraphs re-joined: a line starting in lower case (or with a digit)
    continues the previous one when that one does not end a sentence. Table rows are skipped."""
    pending: str | None = None
    for raw_line in (text or "").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("|"):
            stripped = ""  # Markdown table row: cells are not statements
        continuation = (
            pending is not None
            and stripped
            and (stripped[0].islower() or stripped[0].isdigit())
            and not _BULLET.match(stripped)
            and not pending.rstrip().endswith((".", "!", "?", ":", ";"))
        )
        if continuation:
            pending = f"{pending.rstrip()} {stripped}"
            continue
        if pending is not None:
            yield pending
        pending = raw_line if stripped else None
        if not stripped:
            yield ""
    if pending is not None:
        yield pending


def iter_sentences(text: str, initial_section: str | None = None) -> Iterator[tuple[str, MemoryKind | None]]:
    """Yield ``(sentence, section_kind)`` for each sentence of ``text`` (Markdown aware)."""
    section_kind = _section_kind(initial_section) if initial_section else None
    for raw_line in _logical_lines(text):
        heading = _HEADING.match(raw_line)
        if heading:
            section_kind = _section_kind(heading.group("title"))
            continue
        line = _clean_line(raw_line)
        if not line:
            continue
        if line.endswith(":") and len(line) <= 60:
            section_kind = _section_kind(line[:-1])
            continue
        for sentence in _SENTENCE_SPLIT.split(line):
            sentence = sentence.strip()
            if sentence:
                yield sentence, section_kind


def _section_kind(title: str | None) -> MemoryKind | None:
    if not title:
        return None
    folded = fold(_clean_line(title))
    for pattern, kind in _SECTION_KINDS:
        if pattern.search(folded):
            return kind
    return None


def _label_kind(label: str) -> MemoryKind:
    folded = fold(label)
    for prefix, kind in _LABEL_KINDS:
        if folded.startswith(prefix):
            return kind
    return MemoryKind.fact


def classify_sentence(
    sentence: str, *, section_kind: MemoryKind | None = None, source_kind: SourceKind | None = None
) -> Statement | None:
    """Rule-based classification of one sentence (``None`` when it is not memory-worthy)."""
    text = sentence.strip()
    if len(text) < MIN_STATEMENT_LENGTH or len(text) > MAX_STATEMENT_LENGTH:
        return None
    folded = fold(text)
    if _METADATA.match(folded) or text.endswith("?"):
        return None

    label = _LABEL.match(text)
    if label:
        kind = _label_kind(label.group("label"))
        body = label.group("body").strip()
        if len(body) < 4:
            return None
        title = _story_title(body) if kind == MemoryKind.requirement else None
        return Statement(
            kind=kind,
            title=title or make_title(body),
            content=text,
            confidence=0.8,
            explicit_decision=kind == MemoryKind.decision,
            rule=f"label:{kind.value}",
        )

    if source_kind == SourceKind.agent_trace:
        return None  # agent traces are activity logs: only explicitly labelled statements are memory
    story_title = _story_title(text)
    if story_title:
        return Statement(MemoryKind.requirement, story_title, text, 0.72, False, "user_story")
    if _DECISION.search(folded):
        body = _DECISION_PREFIX.sub("", text).strip() or text
        return Statement(MemoryKind.decision, make_title(body), text, 0.75, False, "decision_phrase")
    if _DANGLING_PRONOUN.match(folded):
        return None  # « Il confirme… », « Elle valide… »: meaningless out of their paragraph
    if section_kind is not None:
        return Statement(section_kind, make_title(text), text, 0.7, False, f"section:{section_kind.value}")
    if _PROCEDURE.search(folded):
        return Statement(MemoryKind.procedure, make_title(text), text, 0.65, False, "procedure_phrase")
    if _USERS_WANT.search(folded):
        return Statement(MemoryKind.requirement, make_title(text), text, 0.68, False, "users_want")
    if _RISK.search(folded):
        return Statement(MemoryKind.risk, make_title(text), text, 0.65, False, "risk_phrase")
    if _CONSTRAINT.search(folded):
        return Statement(MemoryKind.constraint, make_title(text), text, 0.6, False, "modal")
    if source_kind == SourceKind.feedback and _FEEDBACK_COMPLAINT.search(folded):
        return Statement(MemoryKind.risk, make_title(text), text, 0.5, False, "feedback")
    if _NUMBER.search(text) and _FACT.search(folded):
        return Statement(MemoryKind.fact, make_title(text), text, 0.65, False, "numeric_fact")
    return None


def is_meeting_record(document: Document, first_text: str = "") -> bool:
    """Meeting minutes: « compte rendu », « CR », « comité », « réunion », « sprint review »…"""
    head = f"{document.title}\n{first_text[:600]}"
    return bool(_MEETING.search(fold(head)) or _MEETING_CR.search(head))


_TRUST_CONFIDENCE_DELTA: dict[SourceTrust, float] = {
    SourceTrust.high: 0.0,
    SourceTrust.medium: 0.0,
    SourceTrust.low: -0.1,
}
_SOURCE_CONFIDENCE_DELTA: dict[SourceKind, float] = {
    SourceKind.agent_trace: -0.15,
    SourceKind.url: -0.1,
    SourceKind.feedback: -0.05,
    SourceKind.crm: -0.05,
}


def extract_statements(
    text: str, *, section: str | None = None, source_kind: SourceKind | None = None
) -> list[Statement]:
    """All memory-worthy statements of a text (rules only)."""
    statements: list[Statement] = []
    for sentence, section_kind in iter_sentences(text, section):
        statement = classify_sentence(sentence, section_kind=section_kind, source_kind=source_kind)
        if statement is not None:
            statements.append(statement)
    return statements


# --- LLM path (F3: validated memory cards, see app.memory.llm_extraction) --------------------------------


def _card_statement(card: MemoryCard) -> Statement | None:
    content = " ".join(card.statement.split())
    if not MIN_STATEMENT_LENGTH <= len(content) <= MAX_STATEMENT_LENGTH:
        return None
    kind = card_kind(card)
    explicit = kind == MemoryKind.decision and fold(card.source_quote).lstrip("*_ -").startswith("decision")
    return Statement(
        kind=kind,
        title=make_title(card.title) or make_title(content),
        content=content,
        confidence=round(max(0.3, min(0.95, card.confidence)), 2),
        explicit_decision=explicit,
        rule="llm",
        quote=" ".join(card.source_quote.split()),
        rationale=card.rationale,
        decided_by=card.decided_by,
        confidence_reason=card.confidence_reason or None,
    )


def _covered_by_card(rule: Statement, cards: Sequence[Statement]) -> bool:
    """A rule-based statement whose sentence is (part of) a card's quote is merged into that card."""
    text = normalize_quote(rule.content)
    for card in cards:
        if kind_family(card.kind) != kind_family(rule.kind) or not card.quote:
            continue
        quote = normalize_quote(card.quote)
        if text and (text in quote or quote in text):
            return True
    return False


def merge_statements(cards: Sequence[Statement], rules: Sequence[Statement]) -> list[Statement]:
    """LLM cards first, then the rule-based statements they do not already cover."""
    return [*cards, *(rule for rule in rules if not _covered_by_card(rule, cards))]


# --- Extraction job ----------------------------------------------------------------------------------------


async def _load(session: AsyncSession, job: IngestionJob) -> tuple[Document, Source, list[Chunk]] | None:
    if job.document_id is None:
        raise PermanentJobError("Job d'extraction mémoire sans document")
    document = await session.get(Document, job.document_id)
    if document is None:
        raise PermanentJobError("Document introuvable pour l'extraction mémoire")
    source = await session.get(Source, document.source_id)
    if source is None:
        raise PermanentJobError("Source du document introuvable")
    if document.status == DocumentStatus.forgotten:
        return None
    chunks = list(
        await session.scalars(
            select(Chunk)
            .where(
                Chunk.document_id == document.id,
                Chunk.version == document.current_version,
                Chunk.status == ChunkStatus.active,
                Chunk.quarantined.is_(False),
            )
            .order_by(Chunk.ordinal)
        )
    )
    return document, source, chunks


async def _collect_candidates(
    document: Document, source: Source, chunks: Sequence[Chunk], result: ExtractionResult
) -> list[Candidate]:
    source_kind = SourceKind(source.kind)
    transcript = (document.metadata_ or {}).get("meeting")
    transcript = transcript if isinstance(transcript, dict) and transcript.get("turns") is not None else None
    meeting = transcript is not None or (
        source_kind == SourceKind.note and is_meeting_record(document, chunks[0].text if chunks else "")
    )
    turn_state = None
    if transcript is not None:  # §F1: speaker-attributed decisions and action items
        from app.memory import meeting_extraction

        turn_state = meeting_extraction.TurnState()
        speakers = [str(s) for s in transcript.get("speakers") or []]
        meeting_date = meeting_extraction.parse_meeting_date(transcript.get("date"))
    trust = source.effective_trust
    # §A3: low-trust sources lower the confidence and are never promoted to validated automatically.
    delta = _SOURCE_CONFIDENCE_DELTA.get(source_kind, 0.0) + _TRUST_CONFIDENCE_DELTA[trust]
    candidates: list[Candidate] = []
    by_text: dict[str, Candidate] = {}
    for chunk in chunks:
        if turn_state is not None:
            rules = meeting_extraction.extract_meeting_statements(
                chunk.text_redacted, speakers, turn_state, meeting_date
            )
        else:
            rules = extract_statements(chunk.text_redacted, section=chunk.section, source_kind=source_kind)
        cards = await extract_cards(document, chunk, source_kind, result.llm)
        card_statements = [st for st in (_card_statement(card) for card in cards or []) if st is not None]
        if cards is not None:
            result.used_llm = True
        statements = merge_statements(card_statements, rules)
        for statement in statements:
            validated = meeting and statement.explicit_decision and trust != SourceTrust.low
            statement.confidence = round(
                max(0.3, min(0.95, statement.confidence + delta + (0.1 if validated else 0))), 2
            )
            key = f"{statement.kind.value}:{normalize_text(statement.content)}"
            existing = by_text.get(key)
            if existing is not None:
                if chunk not in existing.chunks:
                    existing.chunks.append(chunk)
                continue
            candidate = Candidate(statement=statement, chunks=[chunk])
            candidate.statement.explicit_decision = validated
            by_text[key] = candidate
            candidates.append(candidate)
            if len(candidates) >= MAX_ITEMS_PER_DOCUMENT:
                return candidates
    return candidates


def _merge_internal_duplicates(candidates: list[Candidate]) -> list[Candidate]:
    """Merge near-identical statements of the same document (e.g. repeated in two sections)."""
    kept: list[Candidate] = []
    for candidate in candidates:
        family = kind_family(candidate.statement.kind)
        twin = None
        for other in kept:
            if other.statement.kind not in family:
                continue
            duplicate, _score = lifecycle.is_duplicate(
                candidate.statement.content,
                other.statement.content,
                candidate.vector,
                other.vector,
                DUPLICATE_SIMILARITY,
            )
            if duplicate:
                twin = other
                break
        if twin is None:
            kept.append(candidate)
        else:
            twin.chunks.extend(c for c in candidate.chunks if c not in twin.chunks)
    return kept


async def _find_existing(
    session: AsyncSession, document: Document, candidates: Sequence[Candidate]
) -> dict[int, MemoryItem]:
    """Map candidate index → existing near-duplicate item of the project (lineage similarity > 0.93)."""
    pool = list(
        await session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.project_id == document.project_id,
                MemoryItem.is_current.is_(True),
                MemoryItem.status != MemoryStatus.forgotten,
                MemoryItem.scope.in_(lifecycle.RELATABLE_SCOPES),
            )
            .order_by(MemoryItem.updated_at.desc())
            .limit(DEDUPE_POOL)
        )
    )
    if not pool:
        return {}
    exact = {(MemoryKind(item.kind), normalize_text(item.content)): item for item in pool}
    matches: dict[int, MemoryItem] = {}
    shortlist: dict[int, list[MemoryItem]] = {}
    needed: dict[Any, MemoryItem] = {}
    for index, candidate in enumerate(candidates):
        statement = candidate.statement
        hit = exact.get((statement.kind, normalize_text(statement.content)))
        if hit is not None:
            matches[index] = hit
            continue
        family = kind_family(statement.kind)
        terms = content_terms(statement.content)
        scored = []
        for item in pool:
            if MemoryKind(item.kind) not in family:
                continue
            other_terms = content_terms(item.content)
            if not terms or not other_terms:
                continue
            overlap = 2 * len(terms & other_terms) / (len(terms) + len(other_terms))
            if overlap >= 0.5:
                scored.append((overlap, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        shortlist[index] = [item for _score, item in scored[:DEDUPE_SHORTLIST]]
        for item in shortlist[index]:
            needed[item.id] = item
    vectors: dict[Any, list[float]] = {}
    if needed and any(c.vector for c in candidates):
        items = list(needed.values())
        computed = await lifecycle.embed_texts([lifecycle.embedding_text(item) for item in items])
        if computed:
            vectors = {item.id: vector for item, vector in zip(items, computed, strict=True)}
    for index, items in shortlist.items():
        candidate = candidates[index]
        best: tuple[float, MemoryItem] | None = None
        for item in items:
            duplicate, score = lifecycle.is_duplicate(
                candidate.text,
                lifecycle.embedding_text(item),
                candidate.vector,
                vectors.get(item.id),
                DUPLICATE_SIMILARITY,
            )
            if duplicate and (best is None or score > best[0]):
                best = (score, item)
        if best is not None:
            matches[index] = best[1]
    return matches


async def _add_provenance(
    session: AsyncSession, item: MemoryItem, document: Document, candidate: Candidate
) -> int:
    linked = set(
        await session.scalars(
            select(MemoryProvenance.chunk_id).where(
                MemoryProvenance.memory_item_id == item.id, MemoryProvenance.chunk_id.is_not(None)
            )
        )
    )
    added = 0
    for chunk in candidate.chunks:
        if chunk.id in linked:
            continue
        session.add(
            MemoryProvenance(
                memory_item_id=item.id,
                document_id=document.id,
                chunk_id=chunk.id,
                source_label=_source_label(document, chunk),
                excerpt=candidate.statement.content,
            )
        )
        added += 1
    if added and item.project_id is not None:
        exists = await session.scalar(
            select(Relation.id).where(
                Relation.src_id == item.id,
                Relation.rel_type == RelationType.derived_from,
                Relation.dst_id == document.id,
            )
        )
        if exists is None:
            session.add(
                Relation(
                    project_id=item.project_id,
                    src_type="memory",
                    src_id=item.id,
                    rel_type=RelationType.derived_from,
                    dst_type="document",
                    dst_id=document.id,
                    confidence=1.0,
                    detail="Provenance",
                )
            )
    return added


def _source_label(document: Document, chunk: Chunk) -> str:
    label = f"{document.title} · §{chunk.ordinal + 1}"
    if chunk.section:
        label += f" ({chunk.section[:60]})"
    return label


async def _obsolete_missing_from_new_version(
    session: AsyncSession, document: Document, kept_item_ids: set[Any], actor: Actor
) -> int:
    """Proposed items derived only from previous versions of the document and not restated in the new
    one become obsolete (validated items are kept: a human vouched for them)."""
    if document.current_version <= 1:
        return 0
    rows = await session.execute(
        select(MemoryItem, Chunk.version)
        .join(MemoryProvenance, MemoryProvenance.memory_item_id == MemoryItem.id)
        .join(Chunk, Chunk.id == MemoryProvenance.chunk_id)
        .where(
            Chunk.document_id == document.id,
            MemoryItem.is_current.is_(True),
            MemoryItem.status == MemoryStatus.proposed,
        )
    )
    versions: dict[Any, tuple[MemoryItem, set[int]]] = {}
    for item, version in rows.tuples():
        versions.setdefault(item.id, (item, set()))[1].add(int(version))
    count = 0
    for item_id, (item, chunk_versions) in versions.items():
        if item_id in kept_item_ids or document.current_version in chunk_versions:
            continue
        other_sources = await session.scalar(
            select(MemoryProvenance.id)
            .outerjoin(Chunk, Chunk.id == MemoryProvenance.chunk_id)
            .where(
                MemoryProvenance.memory_item_id == item_id,
                (Chunk.document_id.is_(None)) | (Chunk.document_id != document.id),
            )
            .limit(1)
        )
        if other_sources is not None:
            continue
        await lifecycle.obsolete(
            session,
            item,
            actor,
            f"Absent de la nouvelle version (v{document.current_version}) de « {document.title} »",
        )
        count += 1
    return count


async def extract_from_document(session: AsyncSession, job: IngestionJob) -> dict[str, int]:
    """Handler of ``extract_memory`` jobs: extract, deduplicate, create, detect relations.

    Records the ``extract_memory`` job step and returns counters. Flushes, never commits.
    """
    result = ExtractionResult()
    async with track_step(session, job, "extract_memory") as step:
        # Serialize extractions per project: concurrent workers would otherwise not see each other's
        # uncommitted items and create duplicates (e.g. a document and its forwarded copy).
        # Transaction-scoped lock, released when the worker commits the job.
        await session.execute(
            select(
                func.pg_advisory_xact_lock(func.hashtextextended(f"orbit:extract-memory:{job.project_id}", 0))
            )
        )
        loaded = await _load(session, job)
        if loaded is None:
            step.skip("Document oublié : extraction ignorée")
            return result.counters()
        document, source, chunks = loaded
        if not chunks:
            step.skip("Aucun fragment actif à analyser")
            return result.counters()
        started = time.perf_counter()
        actor = Actor.system()

        candidates = await _collect_candidates(document, source, chunks, result)
        vectors = await lifecycle.embed_texts([c.text for c in candidates]) if candidates else []
        if vectors:
            for candidate, vector in zip(candidates, vectors, strict=True):
                candidate.vector = vector
        candidates = _merge_internal_duplicates(candidates)
        existing = await _find_existing(session, document, candidates)

        kept_ids: set[Any] = set()
        for index, candidate in enumerate(candidates):
            item = existing.get(index)
            if item is None:
                continue
            kept_ids.add(item.id)
            added = await _add_provenance(session, item, document, candidate)
            result.provenance_added += added
            if not added:
                result.skipped_duplicates += 1

        for index, candidate in enumerate(candidates):
            if index in existing:
                continue
            statement = candidate.statement
            status = MemoryStatus.validated if statement.explicit_decision else MemoryStatus.proposed
            data = MemoryIn(
                scope=MemoryScope.project,
                kind=statement.kind,
                title=statement.title,
                content=statement.content,
                status=status.value,
                confidence=statement.confidence,
                valid_from=document.source_updated_at,
                tags=["extraction-auto", "extraction-llm"]
                if statement.rule == "llm"
                else ["extraction-auto"],
                provenance=[
                    ProvenanceIn(
                        chunk_id=chunk.id,
                        document_id=document.id,
                        excerpt=statement.quote or statement.content,
                        source_label=_source_label(document, chunk),
                    )
                    for chunk in candidate.chunks[:10]
                ],
            )
            item = await lifecycle.create_item(
                session,
                project_id=document.project_id,
                data=data,
                actor=actor,
                vector=candidate.vector,
                detect=False,
                audit_entry=False,
                refresh_index=False,
            )
            if statement.rule == "llm":
                item.rationale = statement.rationale
                item.decided_by = statement.decided_by
                item.confidence_reason = statement.confidence_reason
            elif statement.decided_by:
                item.decided_by = statement.decided_by
            if statement.action_meta:
                item.action_meta = statement.action_meta
            result.created.append(item)

        for item in result.created:
            relations = await lifecycle.detect_relations(session, item)
            result.superseded += sum(1 for r in relations if r.rel_type == RelationType.supersedes)
            result.conflicts += sum(1 for r in relations if r.rel_type == RelationType.contradicts)

        result.obsoleted = await _obsolete_missing_from_new_version(
            session, document, kept_ids | {item.id for item in result.created}, actor
        )

        if result.created or result.provenance_added:
            await audit.record(
                session,
                document.project_id,
                actor,
                AuditAction.memory_create,
                "document",
                document.id,
                summary=f"Extraction mémoire depuis « {document.title} » : {result.detail()}",
                details=result.counters(),
            )
        await session.flush()
        if result.created:
            signals = await poisoning.check_and_record(session, document.project_id)  # §A3
            if signals:
                await session.flush()
        step.detail = result.detail()
        logger.info(
            "Memory extraction for document %s: %s in %.0f ms",
            document.id,
            result.counters(),
            (time.perf_counter() - started) * 1000,
        )
    return result.counters()


__all__ = [
    "ExtractionResult",
    "Statement",
    "classify_sentence",
    "extract_from_document",
    "extract_statements",
    "is_meeting_record",
    "iter_sentences",
    "make_title",
]

# Keep ``MemoryEventType`` importable for type checkers of callers that inspect events.
_ = MemoryEventType

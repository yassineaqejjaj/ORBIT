"""« Demander à ORBIT » (F4, docs/FEATURES.md).

1. The question goes through **the existing context engine** (:func:`assemble_context`): same ACL,
   clearance, private user memory, PII redaction and audit as any context request (intent inferred).
2. The answer is generated from the governed items only:

   * **LLM mode** when an LLM is configured — items above the guardrail ceiling are removed from what is
     sent (and reported in ``warnings``); every line of the answer must cite an item sent (``[S1]``),
     uncited lines are dropped, and an answer without any valid citation falls back to:
   * **extractive mode** — the most relevant sentences of the items, grouped by decision / need /
     constraint / risk, each one cited.

   Never a claim without a citation; « Je ne trouve pas d'information validée sur ce point » when nothing
   relevant was retrieved.
3. Conversations and messages are persisted (private to the asker); feedback goes to ``context_feedback``.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import persistence
from app.context.assembler import assemble_context
from app.db import utcnow
from app.deps import ProjectAccess
from app.enums import CandidateType, MemoryKind, PrincipalKind
from app.errors import not_found
from app.features.ask.schemas import (
    AskConversationDetail,
    AskConversationSummary,
    AskFeedbackIn,
    AskIn,
    AskMessageOut,
    AskOut,
)
from app.llm import client as llm
from app.llm import guardrail
from app.memory.conflicts import content_terms
from app.memory.extractor import classify_sentence, iter_sentences
from app.models.features_ask import AskConversation, AskMessage
from app.schemas.context import ContextItem, ContextRequestIn, FeedbackIn
from app.services import audit

logger = logging.getLogger("orbit.ask")

NOT_FOUND = "Je ne trouve pas d'information validée sur ce point."
DEFAULT_TOKEN_BUDGET = 3000
MAX_SENTENCES = 6
MAX_SENTENCES_PER_ITEM = 2
MAX_LLM_SOURCES = 12
TITLE_LENGTH = 80
AUDIT_ACTION = "ask.question"

#: Question words that say *what kind* of answer is expected, not *what about*.
_META_TERMS = content_terms(
    "pourquoi comment quoi quel quelle quels quelles qui quand combien est-ce avons avez ont sait "
    "choisi choix choisir décidé décider décision décisions retenu retenue projet orbit "
    "information informations sujet concernant propos dit prévu"
)
_CITATION = re.compile(r"\[S(\d+)\]")
_GROUPS: list[tuple[MemoryKind | None, str]] = [
    (MemoryKind.decision, "Décisions"),
    (MemoryKind.requirement, "Besoins"),
    (MemoryKind.constraint, "Contraintes"),
    (MemoryKind.risk, "Risques"),
    (None, "Autres éléments"),
]
_GROUPED_KINDS = {kind for kind, _ in _GROUPS if kind is not None}

LLM_SYSTEM = (
    "Tu es ORBIT, l'assistant mémoire d'un projet. Réponds en français, en Markdown concis, UNIQUEMENT à "
    "partir des sources fournies. Chaque phrase ou puce doit se terminer par la ou les citations des "
    "sources utilisées, au format [S1], [S2]… N'invente rien et ne cite jamais une source absente. "
    f"Si les sources ne permettent pas de répondre, réponds exactement : « {NOT_FOUND} ». "
    'Réponds en JSON : {"answer": "<markdown cité>", "follow_ups": ["<question de relance>", …]} '
    "(au plus 3 relances courtes)."
)


@dataclass(slots=True)
class Answer:
    text: str
    cited: list[ContextItem]
    mode: str
    follow_ups: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tokens: int = 0
    relevance: float = 0.0


# --- Relevance ---------------------------------------------------------------------------------------------


def question_terms(question: str) -> set[str]:
    terms = content_terms(question)
    focused = terms - _META_TERMS
    return focused or terms


@dataclass(slots=True)
class _Sentence:
    item: ContextItem
    text: str
    score: float
    overlap: float
    kind: MemoryKind | None


def _relevant_sentences(question: str, items: list[ContextItem]) -> list[_Sentence]:
    terms = question_terms(question)
    if not terms:
        return []
    found: list[_Sentence] = []
    for item in items:
        title_terms = content_terms(item.title)
        title_overlap = len(terms & title_terms) / len(terms)
        per_item: list[_Sentence] = []
        for sentence, _section in iter_sentences(item.excerpt):
            text = " ".join(sentence.split()).strip(" -•*")
            if len(text) < 12:
                continue
            overlap = len(terms & content_terms(text)) / len(terms)
            if overlap == 0 and title_overlap < 0.5:
                continue
            relevance = max(overlap, title_overlap * 0.8)
            if relevance < 0.34:
                continue
            kind = item.memory_kind if item.memory_kind in _GROUPED_KINDS else None
            if kind is None:
                statement = classify_sentence(text)
                kind = statement.kind if statement and statement.kind in _GROUPED_KINDS else None
            score = relevance + 0.3 * float(item.scores.final or 0) + (0.15 if item.memory_kind else 0)
            per_item.append(_Sentence(item, text, score, relevance, kind))
        per_item.sort(key=lambda s: s.score, reverse=True)
        found.extend(per_item[:MAX_SENTENCES_PER_ITEM])
    found.sort(key=lambda s: s.score, reverse=True)
    return found[:MAX_SENTENCES]


# --- Extractive answer -------------------------------------------------------------------------------------


def extractive_answer(question: str, items: list[ContextItem]) -> Answer:
    sentences = _relevant_sentences(question, items)
    if not sentences:
        return Answer(NOT_FOUND, [], "extractive")
    lines: list[str] = []
    for kind, label in _GROUPS:
        group = [s for s in sentences if s.kind == kind]
        if not group:
            continue
        lines.append(f"**{label}**")
        lines.extend(f"- {_ensure_period(s.text)} [{s.item.citation}]" for s in group)
        lines.append("")
    cited = _unique_items(s.item for s in sentences)
    best = max(s.overlap for s in sentences)
    return Answer("\n".join(lines).strip(), cited, "extractive", relevance=best)


_LABEL_PREFIX = re.compile(r"^(?:d[ée]cision|contrainte|besoin|risque|r[èe]gle)\s*:\s*", re.IGNORECASE)


def _ensure_period(text: str) -> str:
    text = _LABEL_PREFIX.sub("", text)
    text = text[:1].upper() + text[1:]
    return text if text[-1:] in ".!?…»)" else f"{text}."


def _unique_items(items: Any) -> list[ContextItem]:
    seen: dict[str, ContextItem] = {}
    for item in items:
        seen.setdefault(item.citation, item)
    return sorted(seen.values(), key=lambda i: int(i.citation[1:]) if i.citation[1:].isdigit() else 0)


# --- LLM answer -------------------------------------------------------------------------------------------


def _source_block(item: ContextItem) -> str:
    nature = (
        item.memory_kind.value if item.memory_kind else (item.source_kind.value if item.source_kind else "")
    )
    return f"[{item.citation}] ({nature}) {item.title}\n{item.excerpt}"


def ground_llm_answer(text: str, allowed: dict[str, ContextItem]) -> tuple[str, list[ContextItem]] | None:
    """Keep only cited lines with valid citations; ``None`` when nothing grounded remains."""
    if NOT_FOUND.rstrip(".") in text:
        return NOT_FOUND, []
    kept: list[str] = []
    cited: list[ContextItem] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        refs = [f"S{n}" for n in _CITATION.findall(stripped)]
        valid = [ref for ref in refs if ref in allowed]
        if not valid:
            # Headings without claims may stay; any other uncited line is dropped.
            if re.fullmatch(r"(#{1,4}\s+.{1,80}|\*\*[^*]{1,80}\*\*:?)", stripped):
                kept.append(line)
            continue
        line = _CITATION.sub(lambda m: m.group(0) if f"S{m.group(1)}" in allowed else "", line)
        kept.append(line)
        cited.extend(allowed[ref] for ref in valid)
    if not cited:
        return None
    answer = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return answer, _unique_items(cited)


async def llm_answer(question: str, history: list[str], items: list[ContextItem]) -> Answer | None:
    """LLM answer grounded in the items the guardrail allows; ``None`` → extractive fallback."""
    if not llm.is_enabled():
        return None
    allowed_items = [item for item in items if guardrail.allows(item.classification)][:MAX_LLM_SOURCES]
    withheld = sum(1 for item in items if not guardrail.allows(item.classification))
    warnings: list[str] = []
    if withheld:
        guardrail.record_skip(guardrail.REASON_CLASSIFICATION, withheld)
        warnings.append(
            f"{withheld} source(s) classée(s) au-dessus du plafond LLM (C{guardrail.ceiling()}) "
            "n'ont pas été envoyées au modèle."
        )
    if not allowed_items:
        return None
    previous = "".join(f"- {q}\n" for q in history[-3:])
    user = (
        (f"Questions précédentes de la conversation :\n{previous}\n" if previous else "")
        + f"Question : {question}\n\nSources :\n\n"
        + "\n\n".join(_source_block(item) for item in allowed_items)
    )
    level = max(int(item.classification) for item in allowed_items)
    result = await llm.generate(LLM_SYSTEM, user, json_mode=True, max_tokens=1200, classification=level)
    if result is None:
        return None
    data = llm.parse_json(result.text)
    if not isinstance(data, dict) or not isinstance(data.get("answer"), str):
        logger.warning("Ask: LLM answer is not valid JSON, extractive fallback")
        return None
    grounded = ground_llm_answer(data["answer"], {item.citation: item for item in allowed_items})
    if grounded is None:
        logger.info("Ask: LLM answer without valid citation, extractive fallback")
        return None
    text, cited = grounded
    follow_ups = [str(q).strip()[:200] for q in data.get("follow_ups") or [] if str(q).strip()][:3]
    return Answer(text, cited, "llm", follow_ups, warnings, result.tokens, relevance=1.0 if cited else 0.0)


# --- Confidence & follow-ups ------------------------------------------------------------------------------


def confidence_of(answer: Answer) -> str:
    if not answer.cited:
        return "low"
    memory = [i for i in answer.cited if i.candidate_type == CandidateType.memory]
    if len(answer.cited) >= 2 and memory and answer.relevance >= 0.5:
        return "high"
    if answer.relevance >= 0.5 or memory:
        return "medium"
    return "low"


def _topic(answer: Answer, question: str) -> str:
    if answer.cited:
        title = answer.cited[0].title.strip().rstrip(".")
        return title if len(title) <= 60 else title[:57].rstrip() + "…"
    return question.strip().rstrip("?").strip()[:60]


def default_follow_ups(answer: Answer, question: str) -> list[str]:
    if not answer.cited:
        return [
            "Quelles décisions ont été validées récemment ?",
            "Quels sont les principaux risques du projet ?",
        ]
    topic = _topic(answer, question)
    kinds = {i.memory_kind for i in answer.cited}
    suggestions: list[str] = []
    if MemoryKind.decision not in kinds:
        suggestions.append(f"Qu'a-t-on décidé à propos de « {topic} » ?")
    if MemoryKind.risk not in kinds:
        suggestions.append(f"Quels risques sont associés à « {topic} » ?")
    if MemoryKind.constraint not in kinds:
        suggestions.append(f"Quelles contraintes s'appliquent à « {topic} » ?")
    suggestions.append(f"Qui a validé « {topic} » et quand ?")
    return suggestions[:3]


# --- Persistence ------------------------------------------------------------------------------------------


def _owner_filter(access: ProjectAccess) -> Any:
    principal = access.principal
    if principal.is_agent:
        return AskConversation.agent_id == principal.agent_id
    return AskConversation.user_id == principal.user_id


async def get_conversation(
    session: AsyncSession, access: ProjectAccess, conversation_id: uuid.UUID
) -> AskConversation:
    conversation = await session.scalar(
        select(AskConversation).where(
            AskConversation.id == conversation_id,
            AskConversation.project_id == access.project_id,
            _owner_filter(access),
        )
    )
    if conversation is None:
        raise not_found("Conversation introuvable")
    return conversation


async def _previous_questions(session: AsyncSession, conversation: AskConversation) -> list[str]:
    rows = await session.scalars(
        select(AskMessage.content)
        .where(AskMessage.conversation_id == conversation.id, AskMessage.role == "user")
        .order_by(AskMessage.created_at.desc())
        .limit(3)
    )
    return list(reversed(list(rows)))


def _task(question: str, history: list[str]) -> str:
    """Short follow-ups (« et pour le mobile ? ») inherit the previous question's topic."""
    if history and len(question_terms(question)) <= 2 and len(question.split()) <= 6:
        return f"{history[-1]}\n{question}"
    return question


async def ask(
    session: AsyncSession,
    access: ProjectAccess,
    body: AskIn,
    *,
    channel: str = "web",
    external_id: str | None = None,
) -> AskOut:
    """Answer a question with citations, persist the exchange and audit it (commits)."""
    principal = access.principal
    question = " ".join(body.question.split())
    history: list[str] = []
    conversation: AskConversation | None = None
    if body.conversation_id is not None:
        conversation = await get_conversation(session, access, body.conversation_id)
        history = await _previous_questions(session, conversation)

    package = await assemble_context(
        session,
        access,
        ContextRequestIn(
            task=_task(question, history)[:8000],
            token_budget=body.token_budget or DEFAULT_TOKEN_BUDGET,
            scopes=body.scopes,
        ),
    )
    items = list(package.items)

    answer = await llm_answer(question, history, items) or extractive_answer(question, items)
    if answer.mode == "extractive" and llm.is_enabled():
        withheld = sum(1 for item in items if not guardrail.allows(item.classification))
        if withheld and not answer.warnings:
            answer.warnings.append(
                f"{withheld} source(s) au-dessus du plafond LLM : réponse extractive, sans envoi au modèle."
            )
    confidence = confidence_of(answer)
    follow_ups = answer.follow_ups or default_follow_ups(answer, question)

    if conversation is None:
        conversation = AskConversation(
            project_id=access.project_id,
            user_id=principal.user_id,
            agent_id=principal.agent_id,
            title=question if len(question) <= TITLE_LENGTH else question[: TITLE_LENGTH - 1].rstrip() + "…",
            channel=channel,
        )
        session.add(conversation)
        await session.flush()
    conversation.updated_at = utcnow()
    session.add(
        AskMessage(conversation_id=conversation.id, role="user", content=question, external_id=external_id)
    )
    message = AskMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=answer.text,
        request_id=package.request_id,
        mode=answer.mode,
        confidence=confidence,
        citations=[item.model_dump(mode="json") for item in answer.cited],
        follow_ups=follow_ups,
        warnings=answer.warnings,
        llm_tokens=answer.tokens,
    )
    session.add(message)
    await session.flush()
    await audit.record(
        session,
        access.project_id,
        principal,
        AUDIT_ACTION,
        target_type="ask_conversation",
        target_id=conversation.id,
        summary=f"Question à ORBIT : « {question[:120]} » ({answer.mode}, {len(answer.cited)} source(s))",
        details={
            "request_id": str(package.request_id),
            "mode": answer.mode,
            "citations": [item.citation for item in answer.cited],
            "channel": channel,
            "llm_tokens": answer.tokens,
        },
    )
    await session.commit()
    return AskOut(
        answer=answer.text,
        citations=answer.cited,
        confidence=confidence,  # type: ignore[arg-type]
        follow_ups=follow_ups,
        request_id=package.request_id,
        conversation_id=conversation.id,
        message_id=message.id,
        mode=answer.mode,  # type: ignore[arg-type]
        warnings=answer.warnings,
    )


async def list_conversations(
    session: AsyncSession, access: ProjectAccess, *, limit: int = 50
) -> list[AskConversationSummary]:
    counts = (
        select(AskMessage.conversation_id, func.count().label("n"))
        .group_by(AskMessage.conversation_id)
        .subquery()
    )
    rows = await session.execute(
        select(AskConversation, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.conversation_id == AskConversation.id)
        .where(AskConversation.project_id == access.project_id, _owner_filter(access))
        .order_by(AskConversation.updated_at.desc())
        .limit(limit)
    )
    out = []
    for conversation, count in rows.tuples():
        summary = AskConversationSummary.model_validate(conversation)
        summary.message_count = int(count)
        out.append(summary)
    return out


def message_out(message: AskMessage) -> AskMessageOut:
    return AskMessageOut(
        id=message.id,
        role=message.role,  # type: ignore[arg-type]
        content=message.content,
        citations=[ContextItem.model_validate(c) for c in message.citations or []],
        confidence=message.confidence,  # type: ignore[arg-type]
        mode=message.mode,  # type: ignore[arg-type]
        follow_ups=list(message.follow_ups or []),
        warnings=list(message.warnings or []),
        request_id=message.request_id,
        rating=message.rating,
        created_at=message.created_at,
    )


async def conversation_detail(
    session: AsyncSession, access: ProjectAccess, conversation_id: uuid.UUID
) -> AskConversationDetail:
    conversation = await get_conversation(session, access, conversation_id)
    messages = list(
        await session.scalars(
            select(AskMessage)
            .where(AskMessage.conversation_id == conversation.id)
            .order_by(AskMessage.created_at, AskMessage.role.desc())
        )
    )
    summary = AskConversationSummary.model_validate(conversation)
    return AskConversationDetail(
        **summary.model_dump(exclude={"message_count"}),
        message_count=len(messages),
        messages=[message_out(m) for m in messages],
    )


async def delete_conversation(
    session: AsyncSession, access: ProjectAccess, conversation_id: uuid.UUID
) -> None:
    conversation = await get_conversation(session, access, conversation_id)
    await session.delete(conversation)
    await session.commit()


async def send_feedback(
    session: AsyncSession, access: ProjectAccess, message_id: uuid.UUID, body: AskFeedbackIn
) -> AskMessageOut:
    """👍/👎 on an answer → ``context_feedback`` of the underlying context request (commits)."""
    message = await session.get(AskMessage, message_id)
    if message is None or message.role != "assistant":
        raise not_found("Réponse introuvable")
    await get_conversation(session, access, message.conversation_id)  # ownership (404 otherwise)
    if message.request_id is None:
        raise not_found("Requête de contexte introuvable pour cette réponse")
    request = await persistence.get_request(session, access.project_id, message.request_id)
    rating = 5 if body.rating == "up" else 1
    principal = access.principal
    feedback = await persistence.record_feedback(
        session,
        request,
        FeedbackIn(rating=rating, comment=body.comment),
        actor=principal,
        actor_kind=PrincipalKind.agent if principal.is_agent else PrincipalKind.user,
    )
    message.rating = rating
    message.feedback_id = feedback.id
    await audit.record(
        session,
        access.project_id,
        principal,
        audit.AuditAction.context_feedback,
        target_type="context_request",
        target_id=request.id,
        summary=f"Évaluation {'👍' if rating == 5 else '👎'} d'une réponse de « Demander à ORBIT »",
        details={"feedback_id": feedback.id, "rating": rating, "ask_message_id": str(message.id)},
    )
    await session.commit()
    return message_out(message)

"""``compress`` stage (ARCHITECTURE §9.7): per-item extractive compression to fit the allowances.

Each included item received a token allowance from the budget filler. When its text is longer, the
most useful sentences are kept (query-term overlap + position + sentence/query embedding similarity
when an embedder answers fast enough), in their original order, gaps marked with « … ».

PII safety: chunk candidates only ever carry ``text_redacted`` (see ``retrieval.chunk_candidate``),
so compressed excerpts never contain raw personal data.

Optional LLM summarisation (``app.llm.client``, OpenAI-compatible) is used for heavily compressed
source extracts when an LLM is configured; any failure falls back to the extractive excerpt.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import replace

from app.context import packaging
from app.context.selection import Decision
from app.context.textutils import cosine, split_sentences, term_overlap, words
from app.enums import CandidateType
from app.search.tokens import estimate_tokens, truncate_to_tokens

logger = logging.getLogger("orbit.context.compression")

GAP = " … "
SENTENCE_EMBED_TIMEOUT_SECONDS = 0.5
#: Bounded batch: the embedder serialises inference, a large batch would delay the next requests.
MAX_SENTENCES_TO_EMBED = 64
#: LLM summaries only for items compressed below this ratio of their original size.
LLM_RATIO_THRESHOLD = 0.5
LLM_MAX_ITEMS = 4
LLM_TIMEOUT_SECONDS = 6.0
LLM_SYSTEM_PROMPT = (
    "Tu résumes fidèlement des extraits de documents d'entreprise pour un agent IA. "
    "Réponds uniquement par le résumé, en français, sans introduction, sans ajouter d'information, "
    "en conservant les chiffres, dates, noms de produits et décisions. Ne rétablis jamais les "
    "données masquées entre crochets (ex. [EMAIL])."
)


def clean(text: str) -> str:
    """Single-line, citation-safe text (exactly what ends up in the Markdown bullet)."""
    return packaging.sanitize(text)


def _sentence_score(index: int, sentence: str, query_terms: Sequence[str], similarity: float | None) -> float:
    overlap = term_overlap(query_terms, sentence)
    position = 1.0 / (1.0 + index)
    if similarity is None:
        score = 0.7 * overlap + 0.3 * position
    else:
        score = 0.55 * overlap + 0.2 * position + 0.25 * max(0.0, similarity)
    if len(words(sentence)) < 4:
        score *= 0.5
    return score


def _join(selected: Sequence[tuple[int, str]]) -> str:
    parts: list[str] = []
    previous: int | None = None
    for index, sentence in selected:
        if previous is not None:
            parts.append(GAP if index != previous + 1 else " ")
        elif index > 0:
            parts.append("… ")
        parts.append(sentence)
        previous = index
    return "".join(parts)


def compress_text(
    text: str,
    allowance: int,
    query_terms: Sequence[str],
    sentence_similarities: Sequence[float] | None = None,
) -> str:
    """Extractive compression of ``text`` to at most ``allowance`` tokens."""
    full = clean(text)
    if allowance <= 0 or not full:
        return ""
    if estimate_tokens(full) <= allowance:
        return full
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        return truncate_to_tokens(full, allowance)
    sims = (
        list(sentence_similarities)
        if sentence_similarities and len(sentence_similarities) == len(sentences)
        else None
    )
    ranked = sorted(
        range(len(sentences)),
        key=lambda i: _sentence_score(i, sentences[i], query_terms, sims[i] if sims else None),
        reverse=True,
    )
    chosen: list[int] = []
    for index in ranked:
        trial = sorted([*chosen, index])
        candidate = clean(_join([(i, sentences[i]) for i in trial]))
        if estimate_tokens(candidate) <= allowance:
            chosen = trial
    if not chosen:
        return truncate_to_tokens(clean(sentences[ranked[0]]), allowance)
    return truncate_to_tokens(clean(_join([(i, sentences[i]) for i in chosen])), allowance)


async def _sentence_similarities(
    decisions: Sequence[Decision], query_vector: Sequence[float] | None
) -> dict[int, list[float]]:
    """Sentence/query cosine similarities for items that need compression (best effort, time-boxed)."""
    if not query_vector:
        return {}
    batches: list[tuple[int, list[str]]] = []
    total = 0
    for d in decisions:
        if d.candidate.tokens <= d.allowance:
            continue
        sentences = split_sentences(d.candidate.text)
        if len(sentences) <= 1:
            continue
        if total + len(sentences) > MAX_SENTENCES_TO_EMBED:
            continue
        batches.append((id(d), sentences))
        total += len(sentences)
    if not batches:
        return {}
    try:
        from app.search.embeddings import get_embedder

        embedder = get_embedder()
        flat = [s for _, sentences in batches for s in sentences]
        vectors = await asyncio.wait_for(
            embedder.embed_documents(flat), timeout=SENTENCE_EMBED_TIMEOUT_SECONDS
        )
    except Exception as exc:  # NotImplementedError, timeout, model errors: extractive scoring only
        logger.debug("Sentence embeddings skipped: %s", exc)
        return {}
    result: dict[int, list[float]] = {}
    offset = 0
    for key, sentences in batches:
        sims = [cosine(vectors[offset + i], query_vector) or 0.0 for i in range(len(sentences))]
        result[key] = sims
        offset += len(sentences)
    return result


async def _llm_summaries(decisions: Sequence[Decision]) -> dict[int, str]:
    from app.llm import client as llm_client

    if not llm_client.is_enabled():
        return {}
    targets = [
        d
        for d in decisions
        if d.candidate.candidate_type == CandidateType.chunk
        and d.candidate.tokens > 0
        and d.allowance / d.candidate.tokens < LLM_RATIO_THRESHOLD
    ][:LLM_MAX_ITEMS]
    if not targets:
        return {}

    async def _one(d: Decision) -> tuple[int, str | None]:
        prompt = (
            f"Résume l'extrait ci-dessous en au plus {max(20, int(d.allowance * 0.9))} mots environ.\n\n"
            f"Titre : {d.candidate.title}\n\nExtrait :\n{d.candidate.text[:6000]}"
        )
        answer = await llm_client.complete(
            LLM_SYSTEM_PROMPT,
            prompt,
            max_tokens=d.allowance * 2 + 32,
            timeout_seconds=LLM_TIMEOUT_SECONDS,
            classification=d.candidate.classification,
        )
        return id(d), answer

    try:
        answers = await asyncio.wait_for(
            asyncio.gather(*(_one(d) for d in targets)), timeout=LLM_TIMEOUT_SECONDS + 1
        )
    except Exception as exc:
        logger.warning("LLM summaries skipped: %s", exc)
        return {}
    return {key: answer for key, answer in answers if answer}


async def compress(
    decisions: Sequence[Decision],
    *,
    query_terms: Sequence[str],
    query_vector: Sequence[float] | None,
) -> None:
    """Fill ``excerpt`` / ``tokens`` of every included decision (in place)."""
    similarities, summaries = await asyncio.gather(
        _sentence_similarities(decisions, query_vector), _llm_summaries(decisions)
    )
    for d in decisions:
        summary = summaries.get(id(d))
        excerpt = ""
        if summary:
            excerpt = truncate_to_tokens(clean(summary), d.allowance)
            if excerpt:
                d.verdict = replace(d.verdict, reason_detail=f"{d.verdict.reason_detail} · résumé LLM")
        if not excerpt:
            excerpt = compress_text(d.candidate.text, d.allowance, query_terms, similarities.get(id(d)))
        if not excerpt:
            excerpt = truncate_to_tokens(clean(d.candidate.title), d.allowance)
        d.excerpt = excerpt
        d.tokens = estimate_tokens(excerpt)

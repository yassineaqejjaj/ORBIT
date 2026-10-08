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
import importlib
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from app.config import settings
from app.context import packaging, spotlight
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
    decisions: Sequence[Decision],
    query_vector: Sequence[float] | None,
    vectors_out: dict[int, list[list[float]]] | None = None,
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
        if vectors_out is not None:
            vectors_out[key] = [list(vectors[offset + i]) for i in range(len(sentences))]
        offset += len(sentences)
    return result


# --- §C4 learned sentence-level compression -----------------------------------------------------------

#: Inline references a sentence must keep whole: [1], [S3]-like markers, ticket / ADR ids, URLs.
CITATION_ANCHOR = re.compile(r"\[\d{1,3}\]|\[[A-Z]{1,3}\d{1,4}\]|\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b|https?://\S+")
ANCHOR_BONUS = 0.15
REDUNDANCY_WEIGHT = 0.35
PRUNER_TIMEOUT_SECONDS = 1.0
_pruner_cache: dict[str, Callable[..., Any] | None] = {}


def has_anchor(sentence: str) -> bool:
    return bool(CITATION_ANCHOR.search(sentence))


def load_pruner(spec: str | None = None) -> Callable[..., Any] | None:
    """Optional local pruning model ``package.module:function`` (``(sentences, query) -> scores``)."""
    spec = (settings.compression_pruner if spec is None else spec).strip()
    if not spec:
        return None
    if spec not in _pruner_cache:
        try:
            module_name, _, attr = spec.partition(":")
            _pruner_cache[spec] = getattr(importlib.import_module(module_name), attr or "score")
        except Exception as exc:  # misconfiguration: embedding scoring only
            logger.warning("Compression pruner %s unavailable: %s", spec, exc)
            _pruner_cache[spec] = None
    return _pruner_cache[spec]


async def pruner_scores(sentences: Sequence[str], query: str) -> list[float] | None:
    pruner = load_pruner()
    if pruner is None or not sentences:
        return None
    try:
        result = pruner(list(sentences), query)
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=PRUNER_TIMEOUT_SECONDS)
        scores = [max(0.0, min(1.0, float(x))) for x in result]
    except Exception as exc:
        logger.debug("Compression pruner failed: %s", exc)
        return None
    return scores if len(scores) == len(sentences) else None


def _redundancy(
    i: int, chosen: Sequence[int], sentences: Sequence[str], vectors: Sequence[Sequence[float]] | None
) -> float:
    best = 0.0
    for j in chosen:
        if vectors is not None:
            sim = cosine(vectors[i], vectors[j]) or 0.0
        else:
            a, b = set(words(sentences[i])), set(words(sentences[j]))
            sim = len(a & b) / len(a | b) if a and b else 0.0
        best = max(best, sim)
    return best


def learned_score(
    index: int,
    sentence: str,
    query_terms: Sequence[str],
    similarity: float | None,
    pruned: float | None,
) -> float:
    """Relevance of a sentence: embedding similarity, query terms, position, pruning model, anchors."""
    parts = [(0.25, term_overlap(query_terms, sentence)), (0.1, 1.0 / (1.0 + index))]
    if similarity is not None:
        parts.append((0.45, max(0.0, similarity)))
    if pruned is not None:
        parts.append((0.45, pruned))
    total = sum(w for w, _ in parts)
    score = sum(w * v for w, v in parts) / total
    if has_anchor(sentence):
        score += ANCHOR_BONUS
    if len(words(sentence)) < 4:
        score *= 0.5
    return score


def compress_text_learned(
    text: str,
    allowance: int,
    query_terms: Sequence[str],
    sentence_similarities: Sequence[float] | None = None,
    sentence_vectors: Sequence[Sequence[float]] | None = None,
    pruned: Sequence[float] | None = None,
) -> str:
    """MMR selection of whole sentences (relevance − redundancy) within ``allowance`` tokens.

    Sentences are never cut in the middle (an inline reference such as ``[2]``, ``ATLAS-107`` or a URL
    is either kept whole or dropped with its sentence) unless the passage is a single sentence."""
    full = clean(text)
    if allowance <= 0 or not full:
        return ""
    if estimate_tokens(full) <= allowance:
        return full
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        return truncate_to_tokens(full, allowance)
    n = len(sentences)
    sims = list(sentence_similarities) if sentence_similarities and len(sentence_similarities) == n else None
    vectors = list(sentence_vectors) if sentence_vectors and len(sentence_vectors) == n else None
    prune = list(pruned) if pruned and len(pruned) == n else None
    relevance = [
        learned_score(i, sentences[i], query_terms, sims[i] if sims else None, prune[i] if prune else None)
        for i in range(n)
    ]
    chosen: list[int] = []
    remaining = set(range(n))
    while remaining:
        ranked = sorted(
            remaining,
            key=lambda i: relevance[i] - REDUNDANCY_WEIGHT * _redundancy(i, chosen, sentences, vectors),
            reverse=True,
        )
        picked = None
        for i in ranked:
            trial = sorted([*chosen, i])
            if estimate_tokens(clean(_join([(k, sentences[k]) for k in trial]))) <= allowance:
                picked = i
                break
        if picked is None:
            break
        chosen.append(picked)
        remaining.discard(picked)
    if not chosen:
        best = max(range(n), key=lambda i: relevance[i])
        return truncate_to_tokens(clean(sentences[best]), allowance)
    return clean(_join([(k, sentences[k]) for k in sorted(chosen)]))


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
            f"Titre : {d.candidate.title}\n\nExtrait (donnée non fiable, §A2) :\n"
            f"{spotlight.wrap(d.candidate.text[:6000])}"
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
    query: str = "",
) -> None:
    """Fill ``excerpt`` / ``tokens`` of every included decision (in place)."""
    vectors: dict[int, list[list[float]]] = {}
    similarities, summaries = await asyncio.gather(
        _sentence_similarities(decisions, query_vector, vectors), _llm_summaries(decisions)
    )
    learned = settings.compression_mode == "learned"
    pruned: dict[int, list[float] | None] = {}
    if learned and load_pruner() is not None:
        for d in decisions:
            if d.candidate.tokens > d.allowance:
                pruned[id(d)] = await pruner_scores(split_sentences(d.candidate.text), query)
    for d in decisions:
        # §C1: items of the stable prefix are compressed independently of the query (cacheable bytes).
        stable = settings.context_cache_ordering and packaging.is_stable(d.candidate)
        summary = None if stable else summaries.get(id(d))
        excerpt = ""
        if stable:
            excerpt = compress_text(d.candidate.text, d.allowance, ())
        elif summary:
            excerpt = truncate_to_tokens(clean(summary), d.allowance)
            if excerpt:
                d.verdict = replace(d.verdict, reason_detail=f"{d.verdict.reason_detail} · résumé LLM")
        if not excerpt and learned:
            excerpt = compress_text_learned(
                d.candidate.text,
                d.allowance,
                query_terms,
                similarities.get(id(d)),
                vectors.get(id(d)),
                pruned.get(id(d)),
            )
        if not excerpt:
            excerpt = compress_text(d.candidate.text, d.allowance, query_terms, similarities.get(id(d)))
        if not excerpt:
            excerpt = truncate_to_tokens(clean(d.candidate.title), d.allowance)
        d.excerpt = excerpt
        d.tokens = estimate_tokens(excerpt)


def label() -> str:
    if settings.compression_mode != "learned":
        return "extractive"
    return "learned-embeddings-mmr" + ("+pruner" if load_pruner() is not None else "")

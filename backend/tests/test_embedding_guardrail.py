"""LLM guardrail applied to remote embeddings (NOV-78): C2/C3 content never reaches an external embedder.

Fictitious data only; no network (fake embedders)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.ingestion import pipeline
from app.llm import guardrail
from app.memory import lifecycle
from app.search import embeddings
from app.search.embeddings import HashEmbedder, OpenAIEmbedder


class RecordingRemote:
    """Stands for any external provider: records every text that would leave ORBIT."""

    model_name = "remote-test"
    dim = 4
    remote = True

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.sent.extend(texts)
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.sent.append(text)
        return [1.0, 0.0, 0.0, 0.0]


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> Iterator[RecordingRemote]:
    monkeypatch.setattr(settings, "llm_local", False)
    monkeypatch.setattr(settings, "llm_max_classification", 1)
    fake = RecordingRemote()
    embeddings.set_embedder(fake)
    yield fake
    embeddings.set_embedder(None)


async def test_remote_embedder_gets_only_chunks_within_the_ceiling(remote: RecordingRemote) -> None:
    before = guardrail.skip_count(guardrail.REASON_EMBEDDING)
    vectors = await pipeline.embed_texts(["public a", "SYNTHETIC C3 budget", "interne b"], [0, 3, 1])
    assert [v is not None for v in vectors] == [True, False, True]
    assert remote.sent == ["public a", "interne b"]  # the C3 text was never sent
    assert guardrail.skip_count(guardrail.REASON_EMBEDDING) == before + 1


async def test_remote_embedder_unknown_level_is_c3_and_c2_is_blocked(remote: RecordingRemote) -> None:
    vectors = await pipeline.embed_texts(["unknown level", "SYNTHETIC C2 contract"], [None, 2])
    assert vectors == [None, None] and remote.sent == []
    assert await pipeline.embed_texts(["no levels given"]) == [None]  # fail-closed default
    assert remote.sent == []


async def test_remote_embedder_gets_everything_when_the_ceiling_is_lifted(
    remote: RecordingRemote, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "llm_local", True)
    vectors = await pipeline.embed_texts(["SYNTHETIC C3 budget"], [3])
    assert vectors[0] is not None and remote.sent == ["SYNTHETIC C3 budget"]


async def test_local_embedder_is_never_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_local", False)
    monkeypatch.setattr(settings, "llm_max_classification", 0)
    embeddings.set_embedder(HashEmbedder(settings.embedding_dim))
    try:
        before = guardrail.skip_count(guardrail.REASON_EMBEDDING)
        vectors = await pipeline.embed_texts(["SYNTHETIC C3 budget"], [3])
        assert vectors[0] is not None and len(vectors[0]) == settings.embedding_dim
        assert guardrail.skip_count(guardrail.REASON_EMBEDDING) == before
    finally:
        embeddings.set_embedder(None)


async def test_openai_embedder_makes_no_request_for_a_c3_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_local", False)
    monkeypatch.setattr(settings, "llm_max_classification", 1)
    embedder = OpenAIEmbedder("http://embeddings.invalid", "m", 4)
    posts: list[list[str]] = []

    async def fake_post(inputs: list[str]) -> list[list[float]]:
        posts.append(inputs)
        return [[1.0, 0.0, 0.0, 0.0] for _ in inputs]

    monkeypatch.setattr(embedder, "_post", fake_post)
    assert embedder.remote is True
    vectors = await embeddings.embed_documents_guarded(embedder, ["SYNTHETIC C3 budget"], [3])
    assert vectors == [None] and posts == []
    assert await embeddings.embed_query_guarded(embedder, "SYNTHETIC C3 budget", 3) is None
    assert posts == []
    vectors = await embeddings.embed_documents_guarded(embedder, ["public"], [0])
    assert vectors[0] is not None and posts == [["public"]]


async def test_query_uses_the_requester_clearance(remote: RecordingRemote) -> None:
    before = guardrail.skip_count(guardrail.REASON_EMBEDDING)
    assert await embeddings.embed_query_guarded(remote, "délai de réponse", 1) is not None
    assert await embeddings.embed_query_guarded(remote, "délai de réponse", 2) is None
    assert await embeddings.embed_query_guarded(remote, "délai de réponse", None) is None
    assert remote.sent == ["délai de réponse"]
    assert guardrail.skip_count(guardrail.REASON_EMBEDDING) == before + 2


async def test_understanding_skips_dense_retrieval_above_the_ceiling(remote: RecordingRemote) -> None:
    from app.context.understanding import embed_query

    vector, model = await embed_query("SYNTHETIC task", 3)
    assert vector is None and model is None and remote.sent == []
    vector, model = await embed_query("SYNTHETIC task", 1)
    assert vector is not None and model == "remote-test"


async def test_memory_embeddings_follow_the_same_rule(remote: RecordingRemote) -> None:
    vectors = await lifecycle.embed_texts(["decision interne", "SYNTHETIC C3 plan"], [1, 3])
    assert vectors is not None and [v is not None for v in vectors] == [True, False]
    assert remote.sent == ["decision interne"]
    assert await lifecycle.embed_texts(["no level"]) == [None]


def test_production_refuses_an_external_embedder_with_a_ceiling_above_c1() -> None:
    base = {"jwt_secret": "x" * 40, "embedding_provider": "openai", "embedding_base_url": "http://e.invalid"}
    with pytest.raises(ValidationError, match="ORBIT_LLM_LOCAL"):
        Settings(env="production", llm_max_classification=2, llm_local=False, **base)
    Settings(env="production", llm_max_classification=1, llm_local=False, **base)  # C1 ceiling: fine
    Settings(env="production", llm_max_classification=3, llm_local=True, **base)  # self-hosted: fine
    Settings(env="development", llm_max_classification=2, llm_local=False, **base)  # warning only
    Settings(env="production", jwt_secret="x" * 40, llm_max_classification=3)  # local fastembed: fine

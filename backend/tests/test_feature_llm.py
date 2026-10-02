"""F3 — LLM providers, guardrail and LLM-assisted memory extraction (fake LLM via httpx.MockTransport)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import DocumentStatus, JobKind, SourceKind
from app.llm import client as llm
from app.llm import guardrail
from app.memory import llm_extraction
from app.memory.extractor import extract_from_document
from app.models import Chunk, Document, IngestionJob, MemoryItem, MemoryProvenance, Source

DECISION = (
    "Décision : l'équipe Atlas retient une PWA plutôt qu'une application native, "
    "afin de limiter les coûts de maintenance. Validé par le comité produit le 12 mars 2026."
)


class FakeLLM:
    """Records every request; ``reply`` builds the provider-specific answer text."""

    def __init__(self, reply: Callable[[str], str]) -> None:
        self.reply = reply
        self.requests: list[httpx.Request] = []

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if request.url.path.endswith("/v1/messages"):
            prompt = body["messages"][-1]["content"]
            return httpx.Response(
                200,
                json={
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "", "signature": "x"},
                        {"type": "text", "text": self.reply(prompt)},
                    ],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 120, "output_tokens": 30},
                },
            )
        prompt = body["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": self.reply(prompt)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., FakeLLM]]:
    def _install(reply: Callable[[str], str], *, provider: str = "anthropic", **overrides: Any) -> FakeLLM:
        fake = FakeLLM(reply)
        monkeypatch.setattr(settings, "llm_provider", provider)
        monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-a-real-key")
        if provider == "openai":
            monkeypatch.setattr(settings, "llm_base_url", "http://fake-llm.test/v1")
            monkeypatch.setattr(settings, "llm_model", "fake-model")
        else:
            monkeypatch.setattr(settings, "llm_base_url", "")
            monkeypatch.setattr(settings, "llm_model", "")
        for key, value in overrides.items():
            monkeypatch.setattr(settings, key, value)
        llm.use_transport(httpx.MockTransport(fake.handler))
        return fake

    yield _install
    llm.use_transport(None)


# --- Providers --------------------------------------------------------------------------------------------


async def test_anthropic_provider_messages_api(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(lambda _prompt: "Bonjour")
    assert llm.is_enabled()
    assert llm.model_label() == "claude-sonnet-5"
    result = await llm.generate("Système", "Question", classification=0)
    assert result is not None and result.text == "Bonjour" and result.tokens == 150
    request = fake.requests[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-test-not-a-real-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = fake.bodies()[0]
    assert body["model"] == "claude-sonnet-5"
    assert body["system"] == "Système"
    assert "temperature" not in body
    assert body["messages"] == [{"role": "user", "content": "Question"}]


async def test_anthropic_refusal_and_http_error_fall_back(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(lambda _prompt: "x")

    def refusal(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        return httpx.Response(200, json={"content": [], "stop_reason": "refusal", "usage": {}})

    llm.use_transport(httpx.MockTransport(refusal))
    assert await llm.generate("s", "u", classification=0) is None
    llm.use_transport(httpx.MockTransport(lambda _r: httpx.Response(529, json={"error": {}})))
    assert await llm.complete("s", "u", classification=0) is None


async def test_openai_provider(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(lambda _prompt: '{"ok": true}', provider="openai")
    assert await llm.complete_json("s", "u", classification=1) == {"ok": True}
    assert fake.requests[0].url.path == "/v1/chat/completions"
    assert fake.requests[0].headers["authorization"] == "Bearer sk-test-not-a-real-key"


def test_disabled_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert not llm.is_enabled()
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_base_url", "")
    assert not llm.is_enabled()


# --- Guardrail --------------------------------------------------------------------------------------------


def test_guardrail_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_local", False)
    monkeypatch.setattr(settings, "llm_max_classification", 1)
    assert guardrail.allows(0) and guardrail.allows(1)
    assert not guardrail.allows(2) and not guardrail.allows(3) and not guardrail.allows(None)
    monkeypatch.setattr(settings, "llm_local", True)
    assert guardrail.allows(3)


async def test_guardrail_blocks_above_ceiling_and_redacts_pii(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(lambda _prompt: "ok", llm_max_classification=1, llm_local=False, llm_redact_pii=True)
    before = guardrail.skip_count()
    assert await llm.generate("s", "Contenu secret C3", classification=3) is None
    assert fake.requests == []
    assert guardrail.skip_count() == before + 1

    await llm.generate("s", "Écrire à jeanne.martin@example.com pour valider.", classification=1)
    sent = fake.bodies()[0]["messages"][0]["content"]
    assert "jeanne.martin@example.com" not in sent


# --- Card validation --------------------------------------------------------------------------------------


def _card(**overrides: Any) -> dict[str, Any]:
    card = {
        "kind": "decision",
        "title": "Choix d'une PWA",
        "statement": "L'équipe Atlas retient une PWA plutôt qu'une application native.",
        "decided_by": "Comité produit",
        "decided_at": "2026-03-12",
        "rationale": "Limiter les coûts de maintenance",
        "confidence": 0.9,
        "confidence_reason": "Décision explicite et datée",
        "source_quote": "l’équipe Atlas retient une **PWA** plutôt qu'une application native",
    }
    card.update(overrides)
    return card


def test_parse_cards_validates_and_grounds() -> None:
    answer = json.dumps(
        {
            "cards": [
                _card(),
                _card(source_quote="L'équipe a choisi Flutter pour toutes les plateformes"),  # hallucinated
                _card(confidence=3),  # invalid
                {"kind": "decision"},  # incomplete
            ]
        }
    )
    parsed = llm_extraction.parse_cards(answer, DECISION)
    assert parsed is not None
    cards, rejected = parsed
    assert [c.title for c in cards] == ["Choix d'une PWA"]
    assert rejected == 3
    assert cards[0].decided_at is not None and cards[0].decided_by == "Comité produit"


def test_parse_cards_invalid_json() -> None:
    assert llm_extraction.parse_cards("Voici les décisions : PWA !", DECISION) is None
    assert llm_extraction.parse_cards('{"items": "x"}', DECISION) is None
    assert llm_extraction.parse_cards('```json\n{"cards": []}\n```', DECISION) == ([], 0)


# --- Extraction job ---------------------------------------------------------------------------------------


async def _document(
    session: AsyncSession, project_id: uuid.UUID, title: str, text: str, level: int
) -> Document:
    source = Source(project_id=project_id, name=f"Source {title}", kind=SourceKind.document)
    session.add(source)
    await session.flush()
    document = Document(
        project_id=project_id,
        source_id=source.id,
        title=title,
        uri=f"https://wiki.example/{uuid.uuid4().hex[:6]}",
        status=DocumentStatus.indexed,
        classification=level,
    )
    session.add(document)
    await session.flush()
    session.add(
        Chunk(
            project_id=project_id,
            document_id=document.id,
            version=document.current_version,
            ordinal=0,
            text=text,
            text_redacted=text,
            token_count=len(text.split()),
            classification=level,
            acl_principals=list(document.acl_principals),
        )
    )
    await session.flush()
    return document


async def _extract(session: AsyncSession, document: Document) -> dict[str, int]:
    job = IngestionJob(project_id=document.project_id, document_id=document.id, kind=JobKind.extract_memory)
    session.add(job)
    await session.flush()
    counters = await extract_from_document(session, job)
    await session.commit()
    return counters


async def test_extraction_merges_llm_cards_with_rules(
    fake_llm: Callable[..., FakeLLM], db_session: AsyncSession, project: dict[str, Any]
) -> None:
    hallucinated = _card(title="Flutter", source_quote="Atlas sera développé en Flutter natif")
    fake = fake_llm(lambda _prompt: json.dumps({"cards": [_card(), hallucinated]}))
    project_id = uuid.UUID(str(project["id"]))
    document = await _document(db_session, project_id, "Comité produit Atlas", DECISION, 1)

    counters = await _extract(db_session, document)
    assert counters["llm_calls"] == 1
    assert counters["llm_tokens"] == 150
    assert counters["llm_rejected"] == 1
    assert counters["skipped_guardrail"] == 0
    assert len(fake.requests) == 1

    items = list(
        await db_session.scalars(
            select(MemoryItem)
            .join(MemoryProvenance, MemoryProvenance.memory_item_id == MemoryItem.id)
            .where(MemoryProvenance.document_id == document.id)
        )
    )
    llm_items = [i for i in items if "extraction-llm" in i.tags]
    assert len(llm_items) == 1
    card = llm_items[0]
    assert card.rationale == "Limiter les coûts de maintenance"
    assert card.decided_by == "Comité produit"
    assert card.confidence_reason == "Décision explicite et datée"
    assert not any("Flutter" in i.title for i in items)
    # The rule-based sentence covered by the card is merged into it (no duplicate decision).
    assert len([i for i in items if i.kind == "decision"]) == 1


async def test_extraction_guardrail_keeps_c3_deterministic(
    fake_llm: Callable[..., FakeLLM], db_session: AsyncSession, project: dict[str, Any]
) -> None:
    fake = fake_llm(
        lambda _prompt: json.dumps({"cards": [_card()]}), llm_max_classification=1, llm_local=False
    )
    project_id = uuid.UUID(str(project["id"]))
    document = await _document(db_session, project_id, "Audit confidentiel Atlas", DECISION, 3)
    before = guardrail.skip_count()

    counters = await _extract(db_session, document)
    assert fake.requests == []  # C3 content never reaches the external LLM
    assert counters["skipped_guardrail"] == 1
    assert counters["llm_calls"] == 0
    assert guardrail.skip_count() == before + 1
    items = list(
        await db_session.scalars(
            select(MemoryItem)
            .join(MemoryProvenance, MemoryProvenance.memory_item_id == MemoryItem.id)
            .where(MemoryProvenance.document_id == document.id)
        )
    )
    assert items, "deterministic extraction still runs"
    assert all("extraction-llm" not in i.tags for i in items)


async def test_extraction_invalid_json_falls_back_to_rules(
    fake_llm: Callable[..., FakeLLM], db_session: AsyncSession, project: dict[str, Any]
) -> None:
    fake_llm(lambda _prompt: "Je pense qu'il y a une décision sur la PWA.")
    project_id = uuid.UUID(str(project["id"]))
    document = await _document(db_session, project_id, "Note Atlas", DECISION, 0)
    counters = await _extract(db_session, document)
    assert counters["llm_calls"] == 1 and counters["llm_cards"] == 0
    assert counters["created"] >= 1

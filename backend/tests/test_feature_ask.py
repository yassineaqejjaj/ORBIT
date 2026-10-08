"""F4 — « Demander à ORBIT »: governed, cited answers (extractive and LLM), conversations, feedback."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import retrieval
from app.features.ask.service import NOT_FOUND
from app.llm import guardrail
from app.models import AuditLog, ContextFeedback
from tests.conftest import UserInfo
from tests.test_feature_ask_support import PRIVATE_TEXT, SECRET_TEXT, add_member, seed_atlas
from tests.test_feature_llm import FakeLLM, fake_llm  # noqa: F401  (fixture)

QUESTION = "Pourquoi a-t-on choisi une PWA ?"


@pytest.fixture(autouse=True)
def _fulltext_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unavailable(*_args: Any, **_kwargs: Any) -> list[retrieval.IndexHit]:
        raise retrieval.RetrievalUnavailable("tests: index désactivé")

    monkeypatch.setattr(retrieval, "search_index", _unavailable)


@pytest.fixture
async def world(
    admin_client: httpx.AsyncClient,
    project: dict[str, Any],
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
    db_session: AsyncSession,
) -> dict[str, Any]:
    slug = str(project["slug"])
    viewer = await make_user(clearance=1, name="Vera Viewer")
    cleared = await make_user(clearance=3, name="Claire Habilitée")
    bob = await make_user(clearance=1, name="Bob Membre")
    for user in (viewer, cleared, bob):
        await add_member(admin_client, slug, user)
    ids = await seed_atlas(db_session, project, bob.id)
    return {
        "slug": slug,
        "ids": ids,
        "viewer": await client_for(viewer),
        "cleared": await client_for(cleared),
        "bob": await client_for(bob),
    }


async def _ask(client: httpx.AsyncClient, slug: str, **body: Any) -> dict[str, Any]:
    response = await client.post(f"/api/v1/projects/{slug}/ask", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def test_extractive_answer_is_cited_governed_and_persisted(
    world: dict[str, Any], db_session: AsyncSession
) -> None:
    slug, viewer = world["slug"], world["viewer"]
    out = await _ask(viewer, slug, question=QUESTION)
    assert out["mode"] == "extractive"
    assert out["citations"], out
    cited = {c["citation"] for c in out["citations"]}
    assert set(re.findall(r"\[(S\d+)\]", out["answer"])) == cited
    for line in out["answer"].splitlines():
        if line.startswith("- "):
            assert re.search(r"\[S\d+\]$", line), line  # never a claim without a citation
    assert "**Décisions**" in out["answer"]
    assert "PWA" in out["answer"]
    assert SECRET_TEXT not in json.dumps(out) and PRIVATE_TEXT not in json.dumps(out)
    assert all(c["classification"] <= 1 for c in out["citations"])
    assert out["confidence"] in {"high", "medium"}
    assert out["follow_ups"]

    conversations = (await viewer.get(f"/api/v1/projects/{slug}/ask/conversations")).json()
    assert [c["id"] for c in conversations] == [out["conversation_id"]]
    assert conversations[0]["message_count"] == 2
    detail = (await viewer.get(f"/api/v1/projects/{slug}/ask/conversations/{out['conversation_id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["request_id"] == out["request_id"]
    assert detail["messages"][1]["citations"] == out["citations"]

    # Follow-up in the same conversation.
    again = await _ask(
        viewer,
        slug,
        question="Qu'a-t-on décidé sur l'authentification ?",
        conversation_id=out["conversation_id"],
    )
    assert again["conversation_id"] == out["conversation_id"]
    assert "OIDC" in again["answer"]

    entries = list(await db_session.scalars(select(AuditLog).where(AuditLog.action == "ask.question")))
    assert any(str(e.target_id) == out["conversation_id"] for e in entries)


async def test_not_found_answer(world: dict[str, Any]) -> None:
    out = await _ask(world["viewer"], world["slug"], question="Quelle est la couleur du chat du voisin ?")
    # §C5: the context is insufficient → « je ne sais pas » assumed, with what is missing.
    assert out["answer"].startswith("Je ne sais pas") or out["answer"] == NOT_FOUND
    assert out["sufficiency"]["verdict"] == "insufficient"
    assert out["citations"] == []
    assert out["confidence"] == "low"


async def test_conversations_are_private(world: dict[str, Any]) -> None:
    slug = world["slug"]
    out = await _ask(world["viewer"], slug, question=QUESTION)
    bob = world["bob"]
    assert (await bob.get(f"/api/v1/projects/{slug}/ask/conversations")).json() == []
    response = await bob.get(f"/api/v1/projects/{slug}/ask/conversations/{out['conversation_id']}")
    assert response.status_code == 404
    response = await bob.post(
        f"/api/v1/projects/{slug}/ask", json={"question": QUESTION, "conversation_id": out["conversation_id"]}
    )
    assert response.status_code == 404
    response = await bob.post(
        f"/api/v1/projects/{slug}/ask/messages/{out['message_id']}/feedback", json={"rating": "up"}
    )
    assert response.status_code == 404


async def test_user_memory_stays_private(world: dict[str, Any]) -> None:
    viewer_out = await _ask(world["viewer"], world["slug"], question="Que pense-t-on de la PWA Atlas ?")
    assert PRIVATE_TEXT not in json.dumps(viewer_out)
    bob_out = await _ask(world["bob"], world["slug"], question="Que pense-t-on de la PWA Atlas trop lente ?")
    assert any(c["memory_item_id"] == str(world["ids"]["private"]) for c in bob_out["citations"])


async def test_feedback_is_linked_to_context_feedback(
    world: dict[str, Any], db_session: AsyncSession
) -> None:
    slug, viewer = world["slug"], world["viewer"]
    out = await _ask(viewer, slug, question=QUESTION)
    response = await viewer.post(
        f"/api/v1/projects/{slug}/ask/messages/{out['message_id']}/feedback",
        json={"rating": "down", "comment": "Il manque le budget"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rating"] == 1
    feedback = await db_session.scalar(
        select(ContextFeedback).where(ContextFeedback.request_id == uuid.UUID(out["request_id"]))
    )
    assert feedback is not None and feedback.rating == 1 and feedback.comment == "Il manque le budget"
    detail = (await viewer.get(f"/api/v1/projects/{slug}/ask/conversations/{out['conversation_id']}")).json()
    assert detail["messages"][1]["rating"] == 1


def _citing_reply(extra_line: str = "Phrase inventée sans aucune source.") -> Callable[[str], str]:
    def reply(prompt: str) -> str:
        refs = re.findall(r"^\[(S\d+)\]", prompt, re.MULTILINE)
        answer = f"Atlas est une PWA pour réduire les coûts de maintenance [{refs[0]}] [S99].\n{extra_line}"
        return json.dumps({"answer": answer, "follow_ups": ["Et le mode hors ligne ?"]})

    return reply


async def test_llm_answer_respects_guardrail(
    world: dict[str, Any],
    fake_llm: Callable[..., FakeLLM],  # noqa: F811
) -> None:
    fake = fake_llm(_citing_reply(), llm_max_classification=1, llm_local=False)
    before = guardrail.skip_count()
    out = await _ask(world["cleared"], world["slug"], question="La PWA Atlas et son service worker ?")
    assert out["mode"] == "llm", out
    assert len(fake.requests) == 1
    sent = fake.requests[0].content.decode()
    assert "faille XSS" not in sent  # C3 item withheld from the external LLM
    assert "Bob pense" not in sent  # another user's private memory never retrieved
    assert "Phrase inventée" not in out["answer"]  # uncited line dropped
    assert "[S99]" not in out["answer"]  # unknown citation removed
    assert out["citations"] and all(c["classification"] <= 1 for c in out["citations"])
    assert out["follow_ups"] == ["Et le mode hors ligne ?"]
    assert any("plafond" in w for w in out["warnings"])
    assert guardrail.skip_count() > before


async def test_llm_uncited_or_invalid_falls_back_to_extractive(
    world: dict[str, Any],
    fake_llm: Callable[..., FakeLLM],  # noqa: F811
) -> None:
    fake_llm(lambda _prompt: json.dumps({"answer": "Atlas est une PWA, sans citation."}))
    out = await _ask(world["viewer"], world["slug"], question=QUESTION)
    assert out["mode"] == "extractive" and out["citations"]

    fake_llm(lambda _prompt: "pas du JSON")
    out = await _ask(world["viewer"], world["slug"], question=QUESTION)
    assert out["mode"] == "extractive" and out["citations"]


async def test_llm_not_called_when_everything_is_above_ceiling(
    world: dict[str, Any],
    fake_llm: Callable[..., FakeLLM],  # noqa: F811
) -> None:
    fake = fake_llm(_citing_reply(), llm_max_classification=0, llm_local=False)
    out = await _ask(world["viewer"], world["slug"], question=QUESTION)
    assert fake.requests == []
    assert out["mode"] == "extractive" and out["citations"]
    assert out["warnings"]

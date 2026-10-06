"""§A2 spotlighting in *Demander à ORBIT*: LLM prompt wrapped as untrusted data, notice in the output."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.context import spotlight
from tests.test_feature_ask import _ask, _citing_reply, _fulltext_retrieval, world  # noqa: F401
from tests.test_feature_llm import FakeLLM, fake_llm  # noqa: F401


async def test_ask_prompt_and_output_are_spotlighted(
    world: dict[str, Any],  # noqa: F811
    fake_llm: Callable[..., FakeLLM],  # noqa: F811
) -> None:
    fake = fake_llm(_citing_reply(), llm_max_classification=1, llm_local=False)
    out = await _ask(world["cleared"], world["slug"], question="La PWA Atlas et son service worker ?")
    assert out["mode"] == "llm", out
    sent = fake.requests[0].content.decode()
    assert spotlight.OPEN in sent and spotlight.CLOSE in sent
    assert "données non" in sent  # system instruction of the spotlight
    assert out["untrusted_content_notice"] == spotlight.MCP_NOTICE

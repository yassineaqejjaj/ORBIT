"""Token estimation."""

from __future__ import annotations

from app.search.tokens import estimate_tokens, truncate_to_tokens


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("x" * 38) == 10
    assert estimate_tokens("x" * 39) == 11


def test_truncate_to_tokens() -> None:
    text = "La décision validée impose une application web progressive pour le parcours client. " * 20
    cut = truncate_to_tokens(text, 30)
    assert estimate_tokens(cut) <= 30
    assert cut.endswith("…")
    assert not cut[:-1].endswith(" ")
    assert truncate_to_tokens("court", 10) == "court"
    assert truncate_to_tokens(text, 0) == ""
    for budget in range(1, 60):
        assert estimate_tokens(truncate_to_tokens(text, budget)) <= budget

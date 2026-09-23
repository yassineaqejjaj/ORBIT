"""Token estimation without a tokenizer dependency.

French text averages ≈ 3.8 characters per token with common BPE tokenizers; the estimate is used
for chunking windows, context budgets and cost estimation. It never returns 0 for non-empty text.
"""

from __future__ import annotations

import math

CHARS_PER_TOKEN = 3.8
ELLIPSIS = "…"


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def max_chars_for_tokens(max_tokens: int) -> int:
    return max(0, math.floor(max_tokens * CHARS_PER_TOKEN))


def truncate_to_tokens(text: str | None, max_tokens: int, *, ellipsis: str = ELLIPSIS) -> str:
    """Cut ``text`` so that ``estimate_tokens(result) <= max_tokens``, preferring a word boundary.

    An ellipsis is appended when the text was shortened (and fits in the budget).
    """
    if not text or max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    limit = max_chars_for_tokens(max_tokens)
    suffix = ellipsis if limit > len(ellipsis) + 1 else ""
    room = limit - len(suffix)
    cut = text[:room]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary >= int(room * 0.8):
        cut = cut[:boundary]
    result = cut.rstrip(" \t\n,;:") + suffix
    while result and estimate_tokens(result) > max_tokens:  # defensive, rounding edge cases
        result = result[:-2] + suffix if len(result) > len(suffix) + 1 else ""
    return result


def fits(text: str | None, budget: int) -> bool:
    return estimate_tokens(text) <= budget

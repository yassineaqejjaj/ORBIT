"""Anthropic Messages API provider (``ORBIT_LLM_PROVIDER=anthropic``).

Raw HTTP over the shared ``httpx`` client (no extra dependency): ``POST {base}/v1/messages`` with the
``x-api-key`` and ``anthropic-version`` headers. Only ``text`` content blocks are read (adaptive-thinking
blocks are ignored); a ``refusal`` stop reason or an empty answer is treated as a failure so that callers
fall back to the deterministic path.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
#: Headroom for adaptive thinking, which shares ``max_tokens`` with the visible answer.
THINKING_HEADROOM = 2000
#: Models accepting ``output_config.effort`` (current Opus/Sonnet/Fable generations).
_EFFORT_MODELS = re.compile(r"^claude-(?:opus|sonnet|fable|mythos)-(?:[5-9]|4-[6-9])")


class AnthropicError(Exception):
    """Unusable answer (refusal, truncated or empty)."""


def headers(api_key: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": API_VERSION}


def build_body(model: str, system: str, user: str, *, max_tokens: int, json_mode: bool) -> dict[str, Any]:
    if json_mode:
        system = f"{system}\n\nRéponds uniquement avec un objet JSON valide, sans texte autour."
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens + THINKING_HEADROOM,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if _EFFORT_MODELS.match(model):
        # Extraction / grounded answers are routine tasks: low effort keeps latency and cost down.
        body["output_config"] = {"effort": "low"}
    return body


def parse_response(payload: dict[str, Any]) -> tuple[str, int, int]:
    """``(text, input_tokens, output_tokens)`` of a Messages API response."""
    if payload.get("stop_reason") == "refusal":
        raise AnthropicError("refusal")
    blocks = payload.get("content") or []
    text = "".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if not text:
        raise AnthropicError(f"empty answer (stop_reason={payload.get('stop_reason')})")
    usage = payload.get("usage") or {}
    return text, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


async def create_message(
    client: httpx.AsyncClient,
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    json_mode: bool,
    timeout_seconds: float,
) -> tuple[str, int, int]:
    response = await client.post(
        "/v1/messages",
        json=build_body(model, system, user, max_tokens=max_tokens, json_mode=json_mode),
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return parse_response(response.json())

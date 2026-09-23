"""Optional OpenAI-compatible chat client (vLLM, Ollama, LiteLLM, OpenAI…).

ORBIT works fully without an LLM (deterministic rules + extraction). When ``ORBIT_LLM_BASE_URL`` and
``ORBIT_LLM_MODEL`` are set, callers may use :func:`complete` / :func:`complete_json` to improve
classification, memory extraction or compression. Every failure (timeout, HTTP error, malformed
answer) is logged and returns ``None`` so that callers fall back to the deterministic path.

``ORBIT_LLM_BASE_URL`` is the API root including the version segment, e.g.
``http://ollama:11434/v1`` or ``https://api.openai.com/v1``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("orbit.llm")

_client: httpx.AsyncClient | None = None
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def is_enabled() -> bool:
    return settings.llm_enabled


def model_label() -> str | None:
    """Model name shown in ``/meta`` and context packages (``None`` when disabled)."""
    return settings.llm_model if is_enabled() else None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        _client = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            headers=headers,
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=5.0),
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def complete(
    system: str,
    user: str,
    json_mode: bool = False,
    *,
    temperature: float = 0.1,
    max_tokens: int = 800,
    timeout_seconds: float | None = None,
) -> str | None:
    """Single-turn chat completion. Returns the assistant text, or ``None`` if disabled/failed."""
    if not is_enabled():
        return None
    body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    started = time.perf_counter()
    try:
        response = await _get_client().post(
            "/chat/completions",
            json=body,
            timeout=timeout_seconds if timeout_seconds is not None else settings.llm_timeout_seconds,
        )
        if response.status_code == 400 and json_mode:
            # Some servers reject response_format: retry once without it.
            body.pop("response_format", None)
            response = await _get_client().post("/chat/completions", json=body)
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("LLM call failed after %.0f ms: %s", (time.perf_counter() - started) * 1000, exc)
        return None
    if not isinstance(content, str):
        return None
    logger.debug("LLM call ok in %.0f ms", (time.perf_counter() - started) * 1000)
    return content.strip()


def parse_json(text: str | None) -> Any | None:
    """Lenient JSON parsing of an LLM answer (strips Markdown fences, extracts the first object)."""
    if not text:
        return None
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except ValueError:
                continue
    return None


async def complete_json(system: str, user: str, **kwargs: Any) -> Any | None:
    """:func:`complete` in JSON mode, parsed. ``None`` if disabled, failed or not valid JSON."""
    return parse_json(await complete(system, user, json_mode=True, **kwargs))

"""Optional LLM client: OpenAI-compatible chat completions or the Anthropic Messages API.

ORBIT works fully without an LLM (deterministic rules + extraction). The provider is chosen with
``ORBIT_LLM_PROVIDER``:

* ``openai`` (default) — OpenAI-compatible ``/chat/completions`` (vLLM, Ollama, LiteLLM, OpenAI…), enabled
  when ``ORBIT_LLM_BASE_URL`` (API root including the version segment, e.g. ``http://ollama:11434/v1``)
  and ``ORBIT_LLM_MODEL`` are set;
* ``anthropic`` — native Messages API, enabled when ``ORBIT_LLM_API_KEY`` is set (``ORBIT_LLM_MODEL``
  defaults to ``claude-sonnet-5``, ``ORBIT_LLM_BASE_URL`` to ``https://api.anthropic.com``).

Every call goes through the guardrail (:mod:`app.llm.guardrail`): pass ``classification`` and content
above the ceiling is never sent (``None`` is returned and the skip counted); PII is masked when
``ORBIT_LLM_REDACT_PII`` is on. Every failure (timeout, HTTP error, malformed answer) is logged and returns
``None`` so that callers fall back to the deterministic path.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.llm import anthropic, guardrail

logger = logging.getLogger("orbit.llm")

_client: httpx.AsyncClient | None = None
_transport: httpx.AsyncBaseTransport | None = None
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


@dataclass(slots=True)
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def provider() -> str:
    return settings.llm_provider


def _model() -> str:
    if provider() == "anthropic":
        return settings.llm_model or anthropic.DEFAULT_MODEL
    return settings.llm_model


def _base_url() -> str:
    if provider() == "anthropic":
        return settings.llm_base_url or anthropic.DEFAULT_BASE_URL
    return settings.llm_base_url


def is_enabled() -> bool:
    if provider() == "anthropic":
        return bool(settings.llm_api_key)
    return settings.llm_enabled


def model_label() -> str | None:
    """Model name shown in ``/meta`` and context packages (``None`` when disabled)."""
    return _model() if is_enabled() else None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        if provider() == "anthropic":
            headers = anthropic.headers(settings.llm_api_key)
        else:
            headers = {"Content-Type": "application/json"}
            if settings.llm_api_key:
                headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        _client = httpx.AsyncClient(
            base_url=_base_url(),
            headers=headers,
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=5.0),
            transport=_transport,
        )
    return _client


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Route LLM calls through ``transport`` (tests: ``httpx.MockTransport``). Resets the client."""
    global _client, _transport
    _transport = transport
    _client = None


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def _data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


async def _openai(
    system: str,
    user: str,
    *,
    json_mode: bool,
    temperature: float,
    max_tokens: int,
    timeout_seconds: float,
    images: Sequence[tuple[bytes, str]] = (),
) -> LLMResult | None:
    content: Any = user
    if images:
        # Vision (§B5): OpenAI-compatible multimodal content parts.
        content = [
            {"type": "image_url", "image_url": {"url": _data_url(data, mime)}} for data, mime in images
        ] + [{"type": "text", "text": user}]
    body: dict[str, Any] = {
        "model": _model(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    response = await _get_client().post("/chat/completions", json=body, timeout=timeout_seconds)
    if response.status_code == 400 and json_mode:
        # Some servers reject response_format: retry once without it.
        body.pop("response_format", None)
        response = await _get_client().post("/chat/completions", json=body, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        return None
    usage = payload.get("usage") or {}
    return LLMResult(
        content.strip(), int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    )


async def generate(
    system: str,
    user: str,
    json_mode: bool = False,
    *,
    temperature: float = 0.1,
    max_tokens: int = 800,
    timeout_seconds: float | None = None,
    classification: int | None = None,
    images: Sequence[tuple[bytes, str]] = (),
) -> LLMResult | None:
    """Single-turn completion with token usage. ``None`` if disabled, blocked by the guardrail or failed.

    ``classification``: highest level of the content in ``user``. Above the guardrail ceiling nothing
    is sent. Callers that omit it are responsible for checking :func:`guardrail.allows` themselves.
    """
    if not is_enabled():
        return None
    if classification is not None and not guardrail.allows(classification):
        guardrail.record_skip(guardrail.REASON_CLASSIFICATION)
        return None
    user = guardrail.prepare(user)
    timeout = timeout_seconds if timeout_seconds is not None else settings.llm_timeout_seconds
    started = time.perf_counter()
    try:
        if provider() == "anthropic":
            text, tokens_in, tokens_out = await anthropic.create_message(
                _get_client(),
                model=_model(),
                system=system,
                user=user,
                max_tokens=max_tokens,
                json_mode=json_mode,
                timeout_seconds=timeout,
                images=images,
            )
            result: LLMResult | None = LLMResult(text, tokens_in, tokens_out)
        else:
            result = await _openai(
                system,
                user,
                json_mode=json_mode,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout,
                images=images,
            )
    except (httpx.HTTPError, anthropic.AnthropicError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("LLM call failed after %.0f ms: %s", (time.perf_counter() - started) * 1000, exc)
        return None
    logger.debug("LLM call ok in %.0f ms", (time.perf_counter() - started) * 1000)
    return result


async def describe_image(
    system: str,
    user: str,
    image: bytes,
    mime_type: str,
    *,
    classification: int,
    max_tokens: int = 400,
    timeout_seconds: float | None = None,
) -> str | None:
    """Vision completion on one image (``ORBIT_LLM_MODEL`` must be multimodal). Same guardrail as
    :func:`generate`; ``None`` if disabled, blocked or failed."""
    result = await generate(
        system,
        user,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        classification=classification,
        images=[(image, mime_type)],
    )
    return result.text if result is not None else None


async def complete(
    system: str,
    user: str,
    json_mode: bool = False,
    *,
    temperature: float = 0.1,
    max_tokens: int = 800,
    timeout_seconds: float | None = None,
    classification: int | None = None,
) -> str | None:
    """Single-turn chat completion. Returns the assistant text, or ``None`` if disabled/blocked/failed."""
    result = await generate(
        system,
        user,
        json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        classification=classification,
    )
    return result.text if result is not None else None


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

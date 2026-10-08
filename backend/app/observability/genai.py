"""OpenTelemetry GenAI semantic conventions (docs/AI_CONTEXT_ENGINEERING.md §E6).

Attribute names follow the *development* GenAI and MCP semantic conventions as shipped with
``opentelemetry-semantic-conventions`` 0.65b0 (``gen_ai.*``, ``mcp.*``); they are written as plain strings
so that a renamed incubating constant cannot break ORBIT.

* LLM calls (``app.llm.client``): span ``chat {model}`` (client) — ``gen_ai.operation.name=chat``,
  ``gen_ai.provider.name`` (+ legacy ``gen_ai.system``), ``gen_ai.request.model`` / ``max_tokens`` /
  ``temperature``, ``gen_ai.output.type``, ``gen_ai.response.model``, ``gen_ai.usage.input_tokens`` /
  ``output_tokens``, ``error.type``; prompt/answer contents only with ``ORBIT_OTEL_GENAI_CAPTURE_CONTENT``;
* retrieval (``context.retrieve`` stage): ``gen_ai.operation.name=retrieval``, ``gen_ai.data_source.id``,
  ``gen_ai.retrieval.query.text`` (content capture only), ``gen_ai.request.top_k`` and the hit counts;
* MCP: the SDK server span (``tools/call {tool}``, ``prompts/get``…) already carries ``mcp.method.name``,
  ``mcp.protocol.version``, ``gen_ai.operation.name=execute_tool`` and ``gen_ai.tool.name``; ORBIT adds
  ``mcp.resource.uri`` (resources/read) and the calling agent (``gen_ai.agent.id`` / ``gen_ai.agent.name``);
* LLM judge (§E3): ``gen_ai.evaluation.name`` / ``score.value`` / ``score.label`` / ``explanation``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind

from app.config import settings

OPERATION = "gen_ai.operation.name"
PROVIDER = "gen_ai.provider.name"
SYSTEM = "gen_ai.system"
REQUEST_MODEL = "gen_ai.request.model"
REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
REQUEST_TEMPERATURE = "gen_ai.request.temperature"
REQUEST_TOP_K = "gen_ai.request.top_k"
RESPONSE_MODEL = "gen_ai.response.model"
OUTPUT_TYPE = "gen_ai.output.type"
USAGE_INPUT = "gen_ai.usage.input_tokens"
USAGE_OUTPUT = "gen_ai.usage.output_tokens"
DATA_SOURCE = "gen_ai.data_source.id"
RETRIEVAL_QUERY = "gen_ai.retrieval.query.text"
AGENT_ID = "gen_ai.agent.id"
AGENT_NAME = "gen_ai.agent.name"
INPUT_MESSAGES = "gen_ai.input.messages"
OUTPUT_MESSAGES = "gen_ai.output.messages"
EVALUATION_NAME = "gen_ai.evaluation.name"
EVALUATION_SCORE = "gen_ai.evaluation.score.value"
EVALUATION_LABEL = "gen_ai.evaluation.score.label"
EVALUATION_EXPLANATION = "gen_ai.evaluation.explanation"
MCP_RESOURCE_URI = "mcp.resource.uri"
ERROR_TYPE = "error.type"


def capture_content() -> bool:
    return settings.otel_genai_capture_content


@contextmanager
def chat_span(
    *, provider: str, model: str, max_tokens: int, temperature: float, json_mode: bool
) -> Iterator[Span]:
    """Client span of one LLM chat completion."""
    from app.observability.tracing import setup_tracing

    setup_tracing()
    with trace.get_tracer("orbit.genai").start_as_current_span(
        f"chat {model}",
        kind=SpanKind.CLIENT,
        attributes={
            OPERATION: "chat",
            PROVIDER: provider,
            SYSTEM: provider,
            REQUEST_MODEL: model,
            REQUEST_MAX_TOKENS: max_tokens,
            REQUEST_TEMPERATURE: temperature,
            OUTPUT_TYPE: "json" if json_mode else "text",
        },
    ) as span:
        yield span


def record_chat_result(
    span: Span, *, model: str, input_tokens: int, output_tokens: int, system: str, user: str, text: str | None
) -> None:
    span.set_attribute(RESPONSE_MODEL, model)
    span.set_attribute(USAGE_INPUT, int(input_tokens))
    span.set_attribute(USAGE_OUTPUT, int(output_tokens))
    if capture_content():
        import json

        span.set_attribute(
            INPUT_MESSAGES,
            json.dumps(
                [
                    {"role": "system", "parts": [{"type": "text", "content": system}]},
                    {"role": "user", "parts": [{"type": "text", "content": user}]},
                ],
                ensure_ascii=False,
            ),
        )
        if text is not None:
            span.set_attribute(
                OUTPUT_MESSAGES,
                json.dumps(
                    [{"role": "assistant", "parts": [{"type": "text", "content": text}]}], ensure_ascii=False
                ),
            )


def retrieval_attributes(span: Span, *, data_source: str, query: str, top_k: int, hits: int) -> None:
    span.set_attribute(OPERATION, "retrieval")
    span.set_attribute(DATA_SOURCE, data_source)
    span.set_attribute(REQUEST_TOP_K, int(top_k))
    span.set_attribute("orbit.retrieval.hits", int(hits))
    if capture_content():
        span.set_attribute(RETRIEVAL_QUERY, query)


def agent_attributes(agent: Any) -> None:
    """Tag the current span (MCP server span) with the calling agent."""
    span = trace.get_current_span()
    if agent is None or not span.is_recording():
        return
    span.set_attribute(AGENT_ID, str(agent.id))
    span.set_attribute(AGENT_NAME, str(agent.name))


def evaluation_attributes(
    span: Span, *, name: str, score: float | None, label: str | None, explanation: str
) -> None:
    span.set_attribute(EVALUATION_NAME, name)
    if score is not None:
        span.set_attribute(EVALUATION_SCORE, float(score))
    if label:
        span.set_attribute(EVALUATION_LABEL, label)
    if explanation:
        span.set_attribute(EVALUATION_EXPLANATION, explanation[:500])


class McpResourceMiddleware:
    """MCP server middleware: ``mcp.resource.uri`` on ``resources/read`` spans (SDK span is current)."""

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if ctx.method == "resources/read" and ctx.params:
            uri = ctx.params.get("uri")
            span = trace.get_current_span()
            if isinstance(uri, str) and span.is_recording():
                span.set_attribute(MCP_RESOURCE_URI, uri)
        return await call_next(ctx)


__all__ = [
    "McpResourceMiddleware",
    "agent_attributes",
    "chat_span",
    "evaluation_attributes",
    "record_chat_result",
    "retrieval_attributes",
]

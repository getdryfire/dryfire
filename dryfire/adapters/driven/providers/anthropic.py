"""Anthropic Messages API adapter (SPEC §3.1, §3.3).

Two responsibilities only — `to_wire` and `from_wire` — plus a thin gateway that
times the call. No loop, retry, or assertion logic (SPEC §3.1).

The `anthropic` SDK is an optional extra: this module imports it lazily inside
`AnthropicGateway.__init__`, so `import dryfire` works without it. `to_wire`
and `from_wire` are pure module functions (no SDK), tested offline against real
recorded payloads.
"""

from __future__ import annotations

import json
import time
from typing import Any

from dryfire.application.ports.model_gateway import CompletionRequest
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.stop_reason import map_stop_reason
from dryfire.domain.model.tooling import ToolCall

# Anthropic requires max_tokens; used when the request leaves it unset.
_DEFAULT_MAX_TOKENS = 4096

_INSTALL_HINT = (
    "the Anthropic provider needs the 'anthropic' package. "
    "Install it with: pip install 'dryfire[anthropic]'  (or: uv sync --extra anthropic)"
)


def from_wire(raw: dict[str, Any], latency_ms: int) -> ModelResponse:
    """Translate an Anthropic Messages response (``model_dump()``) into a neutral
    ModelResponse. Anthropic returns parsed tool input, so there are never
    malformed arguments here (SPIKE-001)."""
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in raw.get("content", []):
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            calls.append(
                ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {})
            )
    usage = raw.get("usage") or {}
    return ModelResponse(
        text="".join(text_parts) or None,
        tool_calls=calls,
        stop_reason=map_stop_reason("anthropic", raw.get("stop_reason") or ""),
        usage=Usage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
        ),
        latency_ms=latency_ms,
        raw=raw,
    )


def to_wire(request: CompletionRequest) -> dict[str, Any]:
    """Translate a neutral CompletionRequest into an Anthropic Messages payload."""
    params = request.params
    wire_messages: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "assistant":
            wire_messages.append(_assistant_message(message))
        elif message.tool_results:
            # Tool results are tool_result blocks inside a USER message; N parallel
            # results become one message with N blocks, in call order.
            wire_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.call_id,
                            "content": (
                                result.content
                                if isinstance(result.content, str)
                                else json.dumps(result.content)
                            ),
                            "is_error": result.is_error,
                        }
                        for result in message.tool_results
                    ],
                }
            )
        else:
            wire_messages.append({"role": "user", "content": message.content})

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": wire_messages,
        "max_tokens": params.max_tokens if params.max_tokens is not None else _DEFAULT_MAX_TOKENS,
    }
    if request.system:
        payload["system"] = request.system
    if params.temperature is not None:
        payload["temperature"] = params.temperature
    if params.top_p is not None:
        payload["top_p"] = params.top_p
    if params.stop_sequences:
        payload["stop_sequences"] = params.stop_sequences
    if request.tools:
        payload["tools"] = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.input_schema,
            }
            for tool in request.tools
        ]
    return payload


def _assistant_message(message: Any) -> dict[str, Any]:
    # Anthropic validates tool_use ids in a replayed assistant turn against what it
    # issued and rejects reconstructions — so echo `raw` verbatim when present.
    if message.raw is not None:
        return {"role": "assistant", "content": message.raw["content"]}
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    for call in message.tool_calls:
        blocks.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
        )
    return {"role": "assistant", "content": blocks}


class AnthropicGateway:
    """ModelGateway backed by the Anthropic Messages API."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
            raise RuntimeError(_INSTALL_HINT) from exc
        self._client = AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        payload = to_wire(request)
        start = time.monotonic()
        raw = (await self._client.messages.create(**payload)).model_dump()
        latency_ms = int((time.monotonic() - start) * 1000)
        return from_wire(raw, latency_ms)

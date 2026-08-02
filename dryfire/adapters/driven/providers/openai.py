"""OpenAI Chat Completions adapter (SPEC §3.1, §3.3; DF-201, SPIKE-001).

Mirrors the Anthropic adapter exactly — two pure functions `to_wire` / `from_wire`
plus a thin gateway that times the call — which is the whole point of DF-201: if
the `ModelGateway` port is right, a second provider changes nothing above it and
`application/loop.py` does not move.

Three OpenAI-specific facts, settled in SPIKE-001:
  - Tool results are **separate messages** with `role: "tool"`: N parallel results
    become N messages (Anthropic packs them into one message with N blocks).
  - `function.arguments` is a **JSON string** that can be truncated. Parse
    defensively — on failure, `arguments={}` and the raw string is preserved in
    `malformed_arguments`. Never raise.
  - There is **no `is_error` flag**. A tool error is encoded into the result text
    behind `OPENAI_ERROR_PREFIX` (a named constant, not an invented field).

The `openai` SDK is an optional extra, imported lazily inside the gateway so
`import dryfire` needs no provider SDK. `to_wire`/`from_wire` are SDK-free.
"""

from __future__ import annotations

import json
import time
from typing import Any

from dryfire.application.ports.model_gateway import CompletionRequest
from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.stop_reason import map_stop_reason
from dryfire.domain.model.tooling import ToolCall

# OpenAI has no is_error flag; a tool error is encoded into the result content
# behind this prefix (SPEC §3.1 obligation 5). Lossy by design and documented.
OPENAI_ERROR_PREFIX = "[tool_error] "

_INSTALL_HINT = (
    "the OpenAI provider needs the 'openai' package. "
    "Install it with: pip install 'dryfire[openai]'  (or: uv sync --extra openai)"
)


def from_wire(raw: dict[str, Any], latency_ms: int) -> ModelResponse:
    """Translate an OpenAI Chat Completions response (``model_dump()``) into a
    neutral ModelResponse. Malformed tool arguments are preserved, never raised."""
    choice = (raw.get("choices") or [{}])[0]
    message = choice.get("message") or {}

    calls: list[ToolCall] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments, malformed = _parse_arguments(function.get("arguments"))
        calls.append(
            ToolCall(
                id=call.get("id", ""),
                name=function.get("name", ""),
                arguments=arguments,
                malformed_arguments=malformed,
            )
        )

    usage = raw.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return ModelResponse(
        text=message.get("content"),
        tool_calls=calls,
        stop_reason=map_stop_reason("openai", choice.get("finish_reason") or ""),
        usage=Usage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cache_read_tokens=details.get("cached_tokens", 0),
        ),
        latency_ms=latency_ms,
        raw=raw,
    )


def _parse_arguments(raw_args: Any) -> tuple[dict[str, Any], str | None]:
    """OpenAI sends tool arguments as a JSON string that can be truncated. Return
    the parsed dict, or ``({}, raw)`` when it is unparseable or not an object."""
    if raw_args is None:
        return {}, None
    if not isinstance(raw_args, str):
        return {}, json.dumps(raw_args)
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError:
        return {}, raw_args
    if not isinstance(parsed, dict):
        return {}, raw_args
    return parsed, None


def to_wire(request: CompletionRequest) -> dict[str, Any]:
    """Translate a neutral CompletionRequest into an OpenAI Chat Completions payload."""
    wire: list[dict[str, Any]] = []
    if request.system:
        wire.append({"role": "system", "content": request.system})
    for message in request.messages:
        if message.role == "assistant":
            wire.append(_assistant_message(message))
        elif message.tool_results:
            # Each result is its own message with role="tool" — N parallel results
            # become N messages, in call order.
            for result in message.tool_results:
                content = (
                    result.content
                    if isinstance(result.content, str)
                    else json.dumps(result.content)
                )
                if result.is_error:
                    content = f"{OPENAI_ERROR_PREFIX}{content}"
                wire.append({"role": "tool", "tool_call_id": result.call_id, "content": content})
        else:
            wire.append({"role": "user", "content": message.content})

    params = request.params
    payload: dict[str, Any] = {"model": request.model, "messages": wire}
    if params.temperature is not None:
        payload["temperature"] = params.temperature
    if params.top_p is not None:
        payload["top_p"] = params.top_p
    if params.max_tokens is not None:
        payload["max_tokens"] = params.max_tokens
    if params.stop_sequences:
        payload["stop"] = params.stop_sequences
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
            for tool in request.tools
        ]
    return payload


def _assistant_message(message: Message) -> dict[str, Any]:
    entry: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        entry["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    return entry


class OpenAIGateway:
    """ModelGateway backed by the OpenAI Chat Completions API."""

    name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
            raise RuntimeError(_INSTALL_HINT) from exc
        self._client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        payload = to_wire(request)
        start = time.monotonic()
        raw = (await self._client.chat.completions.create(**payload)).model_dump()
        latency_ms = int((time.monotonic() - start) * 1000)
        return from_wire(raw, latency_ms)

    def is_retryable(self, exc: Exception) -> bool:
        from dryfire.adapters.driven.providers.retrying import default_retryable

        return default_retryable(exc)

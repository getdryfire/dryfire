"""Gemini native `generateContent` adapter (#77; wire settled by the #76 spike).

Like the other adapters, two pure functions `to_wire` / `from_wire` plus a thin gateway
that times the call — no loop, retry, or assertion logic. `application/loop.py` does not
move: the `thoughtSignature` echo reuses the existing `Message.raw` passthrough seam, the
same one Anthropic uses (ARCHITECTURE §9.3).

Unlike `anthropic`/`openai`, this adapter talks to the REST API over **httpx** (already a
core dependency) rather than a vendor SDK — so Gemini needs **no optional extra** and works
out of the box. The REST surface is tiny and gives the raw response dict directly, which the
verbatim-echo requirement needs.

Load-bearing facts from the #76 spike (do not rediscover):
  - `functionCall` carries `{name, args, id}` — note `args`, not `arguments`. `id` is present
    on the current API; `functionResponse.id` is optional (name/order also matches) but we
    thread it.
  - Every part carries an opaque **`thoughtSignature`**; omitting it on the echoed model turn
    is a hard 400. So an assistant turn is echoed verbatim from `Message.raw`.
  - **`finishReason` is `STOP` even for tool calls** → infer `tool_use` from functionCall parts.
  - `functionResponse` needs the tool **name**, not just the id — built from an id→name map
    over the assistant turns' `tool_calls`.
  - Roles are `user`/`model` only; tool results go in a `user` turn.
"""

from __future__ import annotations

import time
from typing import Any, cast

import httpx

from dryfire.application.ports.model_gateway import CompletionRequest
from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.stop_reason import map_stop_reason
from dryfire.domain.model.tooling import ToolCall

_BASE_URL = "https://generativelanguage.googleapis.com"
_DEFAULT_TIMEOUT = 600.0

# A tool error has no dedicated field in a Gemini functionResponse (like OpenAI). We encode
# it into the response object behind a named key rather than inventing a wire field.
GEMINI_ERROR_KEY = "error"


def from_wire(raw: dict[str, Any], latency_ms: int) -> ModelResponse:
    """Translate a Gemini `generateContent` response into a neutral ModelResponse.

    A blocked/empty response (no candidates) never raises — it yields an empty response
    whose stop reason maps from `promptFeedback.blockReason` (or `error` when absent)."""
    candidates = raw.get("candidates") or []
    if not candidates:
        block = (raw.get("promptFeedback") or {}).get("blockReason")
        return ModelResponse(
            text=None, tool_calls=[],
            stop_reason="refusal" if block else "error",
            usage=_usage(raw), latency_ms=latency_ms, raw=raw,
        )

    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []

    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for part in parts:
        if "text" in part:
            text_parts.append(part["text"])
        elif "functionCall" in part:
            fn = part["functionCall"]
            calls.append(
                ToolCall(
                    id=fn.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=fn.get("args") or {},
                )
            )

    # finishReason is STOP even for tool calls — infer tool_use from the calls themselves.
    stop_reason = (
        "tool_use" if calls else map_stop_reason("gemini", candidate.get("finishReason") or "")
    )
    return ModelResponse(
        text="".join(text_parts) or None,
        tool_calls=calls,
        stop_reason=stop_reason,
        usage=_usage(raw),
        latency_ms=latency_ms,
        raw=raw,
    )


def _usage(raw: dict[str, Any]) -> Usage:
    """Map `usageMetadata`. Thinking models bill thoughts as output, so output tokens are
    `candidatesTokenCount + thoughtsTokenCount` — keeping input + output == totalTokenCount."""
    um = raw.get("usageMetadata") or {}
    return Usage(
        input_tokens=um.get("promptTokenCount", 0),
        output_tokens=um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0),
        cache_read_tokens=um.get("cachedContentTokenCount", 0),
    )


def to_wire(request: CompletionRequest) -> dict[str, Any]:
    """Translate a neutral CompletionRequest into a Gemini `generateContent` payload."""
    name_by_id = {
        call.id: call.name for msg in request.messages for call in msg.tool_calls
    }

    contents: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "assistant":
            contents.append(_model_content(message))
        elif message.tool_results:
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {"functionResponse": _function_response(result, name_by_id)}
                        for result in message.tool_results
                    ],
                }
            )
        else:
            contents.append({"role": "user", "parts": [{"text": message.content}]})

    payload: dict[str, Any] = {"contents": contents}
    if request.system:
        payload["systemInstruction"] = {"parts": [{"text": request.system}]}
    if request.tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.input_schema,
                    }
                    for tool in request.tools
                ]
            }
        ]
    generation = _generation_config(request)
    if generation:
        payload["generationConfig"] = generation
    return payload


def _model_content(message: Message) -> dict[str, Any]:
    """The echoed assistant turn. Gemini rejects a tool turn whose functionCall parts lack
    their `thoughtSignature`, so echo the original model content verbatim from `raw` when
    present; only fall back to a reconstruction when there is none (a turn with no tool call)."""
    if message.raw is not None:
        candidates = message.raw.get("candidates") or [{}]
        content = candidates[0].get("content")
        if content is not None:
            return cast(dict[str, Any], content)
    parts: list[dict[str, Any]] = []
    if message.content:
        parts.append({"text": message.content})
    for call in message.tool_calls:
        fn: dict[str, Any] = {"name": call.name, "args": call.arguments}
        if call.id:
            fn["id"] = call.id
        parts.append({"functionCall": fn})
    return {"role": "model", "parts": parts}


def _function_response(result: Any, name_by_id: dict[str, str]) -> dict[str, Any]:
    """A functionResponse part. `response` must be an object; a scalar/string result is
    wrapped, an error is encoded under GEMINI_ERROR_KEY (Gemini has no is_error flag)."""
    content = result.content
    if result.is_error:
        response: dict[str, Any] = {GEMINI_ERROR_KEY: content}
    elif isinstance(content, dict):
        response = content
    else:
        response = {"result": content}
    fr: dict[str, Any] = {"name": name_by_id.get(result.call_id, ""), "response": response}
    if result.call_id:
        fr["id"] = result.call_id
    return fr


def _generation_config(request: CompletionRequest) -> dict[str, Any]:
    params = request.params
    config: dict[str, Any] = {}
    if params.temperature is not None:
        config["temperature"] = params.temperature
    if params.top_p is not None:
        config["topP"] = params.top_p
    if params.max_tokens is not None:
        config["maxOutputTokens"] = params.max_tokens
    if params.stop_sequences:
        config["stopSequences"] = params.stop_sequences
    return config


class GeminiGateway:
    """ModelGateway backed by the Gemini `generateContent` REST API (over httpx)."""

    name = "gemini"

    def __init__(self, api_key: str, *, base_url: str = _BASE_URL) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            timeout=_DEFAULT_TIMEOUT,
        )

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        payload = to_wire(request)
        start = time.monotonic()
        response = await self._client.post(
            f"/v1beta/models/{request.model}:generateContent", json=payload
        )
        response.raise_for_status()
        raw = response.json()
        latency_ms = int((time.monotonic() - start) * 1000)
        return from_wire(raw, latency_ms)

    def is_retryable(self, exc: Exception) -> bool:
        """Retry a 429, any 5xx, or a transport/timeout failure — never a 4xx-other. httpx
        raises `HTTPStatusError` (with `.response.status_code`) and transport/timeout classes,
        so classification is httpx-shaped rather than the SDK-shaped `default_retryable`."""
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            return code == 429 or 500 <= code < 600
        return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))

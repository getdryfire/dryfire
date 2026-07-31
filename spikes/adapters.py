"""SPIKE-001 — minimal wire adapters for Anthropic and OpenAI.

Each adapter does exactly two things:
  to_wire(...)   neutral -> vendor request payload
  from_wire(...) vendor response -> neutral ModelResponse

No loop logic, no retries, no assertions. If either adapter needs to reach
outside this contract, the abstraction in SPEC §3 is wrong.
"""

from __future__ import annotations

import json
from typing import Any

from neutral import Message, ModelResponse, ToolCall, ToolDef, ToolResult, Usage


# ==========================================================================
# Anthropic — Messages API
# ==========================================================================


class AnthropicAdapter:
    name = "anthropic"

    ANTHROPIC_STOP = {
        "end_turn": "end_turn",
        "tool_use": "tool_use",
        "max_tokens": "max_tokens",
        "stop_sequence": "stop_sequence",
        "refusal": "refusal",
        "pause_turn": "end_turn",     # long-running server tools; treat as a stop
    }

    def to_wire(self, *, system, messages: list[Message], tools: list[ToolDef], params):
        wire: list[dict] = []
        for m in messages:
            if m.role == "assistant":
                # Echo the assistant turn verbatim when we have it: Anthropic
                # validates tool_use ids against what it issued.
                if m.raw is not None:
                    wire.append({"role": "assistant", "content": m.raw["content"]})
                else:
                    blocks: list[dict] = []
                    if m.content:
                        blocks.append({"type": "text", "text": m.content})
                    for c in m.tool_calls:
                        blocks.append({
                            "type": "tool_use", "id": c.id,
                            "name": c.name, "input": c.arguments,
                        })
                    wire.append({"role": "assistant", "content": blocks})
            elif m.tool_results:
                # Anthropic: tool results are blocks inside a USER message.
                wire.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.call_id,
                            "content": r.content if isinstance(r.content, str)
                            else json.dumps(r.content),
                            "is_error": r.is_error,
                        }
                        for r in m.tool_results
                    ],
                })
            else:
                wire.append({"role": "user", "content": m.content})

        payload: dict[str, Any] = {"messages": wire, **params}
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description or "",
                 "input_schema": t.input_schema}
                for t in tools
            ]
        return payload

    def from_wire(self, resp: dict) -> ModelResponse:
        text_parts, calls = [], []
        for block in resp.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                calls.append(ToolCall(id=block["id"], name=block["name"],
                                      arguments=block.get("input") or {}))
        u = resp.get("usage", {})
        return ModelResponse(
            text="".join(text_parts) or None,
            tool_calls=calls,
            stop_reason=self.ANTHROPIC_STOP.get(resp.get("stop_reason"), "error"),
            usage=Usage(
                input_tokens=u.get("input_tokens", 0),
                output_tokens=u.get("output_tokens", 0),
                cache_read_tokens=u.get("cache_read_input_tokens", 0),
                cache_write_tokens=u.get("cache_creation_input_tokens", 0),
            ),
            raw=resp,
        )


# ==========================================================================
# OpenAI — Chat Completions API
# ==========================================================================


class OpenAIAdapter:
    name = "openai"

    OPENAI_STOP = {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "length": "max_tokens",
        "content_filter": "refusal",   # NOT semantically equal -- see FINDINGS Q1
        "function_call": "tool_use",   # legacy
    }

    def to_wire(self, *, system, messages: list[Message], tools: list[ToolDef], params):
        wire: list[dict] = []
        if system:
            wire.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": m.content}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id, "type": "function",
                            "function": {"name": c.name,
                                         "arguments": json.dumps(c.arguments)},
                        }
                        for c in m.tool_calls
                    ]
                wire.append(entry)
            elif m.tool_results:
                # OpenAI: each result is its own message with role="tool".
                for r in m.tool_results:
                    content = r.content if isinstance(r.content, str) \
                        else json.dumps(r.content)
                    # LOSSY: OpenAI has no is_error flag. Encode into the text.
                    if r.is_error:
                        content = f"ERROR: {content}"
                    wire.append({"role": "tool", "tool_call_id": r.call_id,
                                 "content": content})
            else:
                wire.append({"role": "user", "content": m.content})

        payload: dict[str, Any] = {"messages": wire, **params}
        if tools:
            payload["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description or "",
                              "parameters": t.input_schema}}
                for t in tools
            ]
        return payload

    def from_wire(self, resp: dict) -> ModelResponse:
        choice = resp["choices"][0]
        msg = choice["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            raw_args = tc["function"].get("arguments") or "{}"
            try:
                parsed, malformed = json.loads(raw_args), None
                if not isinstance(parsed, dict):
                    parsed, malformed = {}, raw_args
            except json.JSONDecodeError:
                parsed, malformed = {}, raw_args
            calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"],
                                  arguments=parsed, malformed_arguments=malformed))
        u = resp.get("usage") or {}
        return ModelResponse(
            text=msg.get("content"),
            tool_calls=calls,
            stop_reason=self.OPENAI_STOP.get(choice.get("finish_reason"), "error"),
            usage=Usage(
                input_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("completion_tokens", 0),
                cache_read_tokens=(u.get("prompt_tokens_details") or {})
                .get("cached_tokens", 0),
            ),
            raw=resp,
        )


ADAPTERS = {"anthropic": AnthropicAdapter(), "openai": OpenAIAdapter()}

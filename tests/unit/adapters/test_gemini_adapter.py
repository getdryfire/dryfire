"""#77 — Gemini native adapter, tested offline against real captured payloads.

Fixtures in tests/fixtures/gemini/ were captured live during the #76 spike (see that dir's
README). These tests pin the Gemini-specific translations settled there: `functionCall`
{name, args, id}, `finishReason: STOP` even for tool calls, the mandatory `thoughtSignature`
echo (via `Message.raw`), and `functionResponse` needing the tool *name*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from dryfire.adapters.driven.providers.gemini import (
    GEMINI_ERROR_KEY,
    GeminiGateway,
    from_wire,
    to_wire,
)
from dryfire.application.ports.model_gateway import CompletionRequest, ModelGateway, ModelParams
from dryfire.domain.model.message import Message
from dryfire.domain.model.tooling import ToolCall, ToolDef, ToolResult

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "gemini"


def _fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_FIXTURES / f"{name}.json").read_text("utf-8")))


def _request(*messages: Message, tools: Any = None, params: Any = None) -> CompletionRequest:
    return CompletionRequest(
        model="gemini-flash-latest", system="be brief", messages=list(messages),
        tools=tools or [], params=params or ModelParams(),
    )


class TestFromWire:
    def test_single_tool_call_infers_tool_use_despite_stop(self) -> None:
        raw = _fixture("single_tool_call")
        resp = from_wire(raw, latency_ms=42)
        # finishReason is STOP, but a functionCall part means tool_use.
        assert raw["candidates"][0]["finishReason"] == "STOP"
        assert resp.stop_reason == "tool_use"
        assert resp.text is None
        assert [c.name for c in resp.tool_calls] == ["lookup_order"]
        assert resp.tool_calls[0].arguments == {"order_id": "A-991"}
        # The id is present on the current API and threaded verbatim.
        expected_id = raw["candidates"][0]["content"]["parts"][0]["functionCall"]["id"]
        assert resp.tool_calls[0].id == expected_id != ""

    def test_parallel_tool_calls_preserve_order_and_ids(self) -> None:
        raw = _fixture("parallel_tool_calls")
        resp = from_wire(raw, latency_ms=0)
        assert resp.stop_reason == "tool_use"
        assert [c.arguments["order_id"] for c in resp.tool_calls] == ["A-991", "B-222"]
        wire_ids = [
            p["functionCall"]["id"]
            for p in raw["candidates"][0]["content"]["parts"]
            if "functionCall" in p
        ]
        assert [c.id for c in resp.tool_calls] == wire_ids

    def test_text_only(self) -> None:
        resp = from_wire(_fixture("text_only"), latency_ms=1)
        assert resp.text == "It arrived on Tuesday."
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"

    def test_max_tokens(self) -> None:
        assert from_wire(_fixture("max_tokens"), latency_ms=1).stop_reason == "max_tokens"

    def test_text_after_tool_result(self) -> None:
        resp = from_wire(_fixture("final_after_tool"), latency_ms=1)
        assert resp.stop_reason == "end_turn"
        assert resp.text and "A-991" in resp.text

    def test_usage_folds_thoughts_into_output(self) -> None:
        # input + output must equal totalTokenCount (thoughts are billed output).
        raw = _fixture("single_tool_call")
        um = raw["usageMetadata"]
        resp = from_wire(raw, latency_ms=0)
        assert resp.usage.input_tokens == um["promptTokenCount"]
        assert resp.usage.output_tokens == um["candidatesTokenCount"] + um["thoughtsTokenCount"]

    def test_unknown_finish_reason_maps_to_error(self) -> None:
        raw = {"candidates": [{"content": {"role": "model", "parts": [{"text": "x"}]},
                               "finishReason": "banana"}]}
        assert from_wire(raw, latency_ms=0).stop_reason == "error"

    def test_blocked_prompt_never_raises(self) -> None:
        raw = {"promptFeedback": {"blockReason": "SAFETY"}}
        resp = from_wire(raw, latency_ms=0)
        assert resp.stop_reason == "refusal"
        assert resp.tool_calls == []


class TestToWire:
    def test_system_then_user(self) -> None:
        payload = to_wire(_request(Message(role="user", content="hi")))
        assert payload["systemInstruction"] == {"parts": [{"text": "be brief"}]}
        assert payload["contents"][0] == {"role": "user", "parts": [{"text": "hi"}]}

    def test_tools_become_function_declarations(self) -> None:
        tools = [ToolDef(name="lookup", description="d", input_schema={"type": "object"})]
        payload = to_wire(_request(Message(role="user", content="hi"), tools=tools))
        decl = payload["tools"][0]["functionDeclarations"][0]
        assert decl == {"name": "lookup", "description": "d", "parameters": {"type": "object"}}

    def test_generation_config_maps_param_names(self) -> None:
        payload = to_wire(_request(
            Message(role="user", content="hi"),
            params=ModelParams(temperature=0.5, top_p=0.9, max_tokens=256, stop_sequences=["STOP"]),
        ))
        assert payload["generationConfig"] == {
            "temperature": 0.5, "topP": 0.9, "maxOutputTokens": 256, "stopSequences": ["STOP"],
        }

    def test_assistant_turn_is_echoed_verbatim_with_thought_signature(self) -> None:
        raw = _fixture("single_tool_call")
        call = raw["candidates"][0]["content"]["parts"][0]["functionCall"]
        assistant = Message(
            role="assistant", raw=raw,
            tool_calls=[ToolCall(id=call["id"], name=call["name"], arguments=call["args"])],
        )
        contents = to_wire(_request(Message(role="user", content="hi"), assistant))["contents"]
        echoed = contents[1]
        assert echoed["role"] == "model"
        # The opaque thoughtSignature must survive verbatim, or the next tool turn 400s.
        assert "thoughtSignature" in echoed["parts"][0]
        assert echoed["parts"][0]["functionCall"]["id"] == call["id"]

    def test_reconstructed_assistant_turn_without_raw(self) -> None:
        assistant = Message(
            role="assistant", content=None,
            tool_calls=[ToolCall(id="c1", name="lookup", arguments={"q": 1})],
        )
        content = to_wire(_request(Message(role="user", content="hi"), assistant))["contents"][1]
        assert content == {"role": "model", "parts": [{"functionCall": {
            "name": "lookup", "args": {"q": 1}, "id": "c1"}}]}

    def test_tool_result_resolves_name_from_call_id(self) -> None:
        assistant = Message(
            role="assistant",
            tool_calls=[ToolCall(id="c1", name="lookup_order", arguments={"order_id": "A-1"})],
        )
        tool = Message(role="tool", tool_results=[
            ToolResult(call_id="c1", content={"total": 780.0, "status": "delivered"}),
        ])
        req = _request(Message(role="user", content="hi"), assistant, tool)
        contents = to_wire(req)["contents"]
        fr = contents[2]["parts"][0]["functionResponse"]
        assert contents[2]["role"] == "user"
        assert fr["name"] == "lookup_order"  # resolved from the id→name map
        assert fr["id"] == "c1"
        assert fr["response"] == {"total": 780.0, "status": "delivered"}

    def test_scalar_tool_result_is_wrapped(self) -> None:
        assistant = Message(role="assistant",
                            tool_calls=[ToolCall(id="c1", name="ping", arguments={})])
        tool = Message(role="tool", tool_results=[ToolResult(call_id="c1", content="pong")])
        fr = to_wire(_request(assistant, tool))["contents"][1]["parts"][0]["functionResponse"]
        assert fr["response"] == {"result": "pong"}

    def test_error_tool_result_encoded_under_error_key(self) -> None:
        assistant = Message(role="assistant",
                            tool_calls=[ToolCall(id="c1", name="ping", arguments={})])
        tool = Message(role="tool",
                       tool_results=[ToolResult(call_id="c1", content="boom", is_error=True)])
        fr = to_wire(_request(assistant, tool))["contents"][1]["parts"][0]["functionResponse"]
        assert fr["response"] == {GEMINI_ERROR_KEY: "boom"}


class TestGateway:
    def test_conforms_to_the_model_gateway_port(self) -> None:
        gateway = GeminiGateway(api_key="not-used")
        assert isinstance(gateway, ModelGateway)
        assert gateway.name == "gemini"

    def test_is_retryable_classification(self) -> None:
        import httpx

        gateway = GeminiGateway(api_key="x")
        req = httpx.Request("POST", "https://example.test")

        def status_error(code: int) -> httpx.HTTPStatusError:
            resp = httpx.Response(code, request=req)
            return httpx.HTTPStatusError("boom", request=req, response=resp)

        assert gateway.is_retryable(status_error(429)) is True
        assert gateway.is_retryable(status_error(503)) is True
        assert gateway.is_retryable(status_error(400)) is False
        assert gateway.is_retryable(httpx.ConnectTimeout("t")) is True
        assert gateway.is_retryable(httpx.ConnectError("c")) is True
        assert gateway.is_retryable(ValueError("nope")) is False

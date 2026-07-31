"""AC-007 — Anthropic adapter, tested offline against REAL recorded payloads
(captured via spikes/probe.py; see SPIKE-001)."""

import inspect
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agentcheck.adapters.driven.providers import anthropic as anthropic_mod
from agentcheck.adapters.driven.providers.anthropic import AnthropicGateway, from_wire, to_wire
from agentcheck.application.ports.model_gateway import (
    CompletionRequest,
    ModelGateway,
    ModelParams,
)
from agentcheck.domain.model.message import Message
from agentcheck.domain.model.tooling import ToolDef, ToolResult


def _accepts_gateway(gateway: ModelGateway) -> ModelGateway:
    return gateway


def _request(*messages: Message, tools: Any = None, params: Any = None) -> CompletionRequest:
    return CompletionRequest(
        model="claude-sonnet-4-6",
        system="be brief",
        messages=list(messages),
        tools=tools or [],
        params=params or ModelParams(),
    )

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "anthropic"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class TestFromWire:
    def test_single_tool_call(self) -> None:
        resp = from_wire(_fixture("single_tool_call"), latency_ms=42)
        assert resp.stop_reason == "tool_use"
        assert resp.text is None  # the real single-call response carries no text block
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "lookup_order"
        assert resp.tool_calls[0].arguments == {"order_id": "A-991"}
        assert resp.tool_calls[0].malformed_arguments is None  # Anthropic parses input
        assert resp.latency_ms == 42

    def test_parallel_tool_calls_preserve_order(self) -> None:
        resp = from_wire(_fixture("parallel_tool_calls"), latency_ms=0)
        assert resp.stop_reason == "tool_use"
        assert [c.name for c in resp.tool_calls] == ["lookup_order", "check_inventory"]

    def test_text_only_response(self) -> None:
        resp = from_wire(_fixture("text_only"), latency_ms=0)
        assert resp.stop_reason == "end_turn"
        assert resp.tool_calls == []
        assert resp.text is not None and resp.text != ""

    def test_max_tokens_truncation(self) -> None:
        resp = from_wire(_fixture("max_tokens"), latency_ms=0)
        assert resp.stop_reason == "max_tokens"

    def test_usage_and_raw_populated(self) -> None:
        raw = _fixture("single_tool_call")
        resp = from_wire(raw, latency_ms=0)
        assert resp.usage.input_tokens == raw["usage"]["input_tokens"]
        assert resp.usage.output_tokens == raw["usage"]["output_tokens"]
        assert resp.usage.cache_read_tokens == raw["usage"]["cache_read_input_tokens"]
        assert resp.usage.cache_write_tokens == raw["usage"]["cache_creation_input_tokens"]
        assert resp.raw == raw

    def test_unknown_stop_reason_maps_to_error_without_raising(self) -> None:
        raw = _fixture("single_tool_call") | {"stop_reason": "some_new_reason"}
        resp = from_wire(raw, latency_ms=0)
        assert resp.stop_reason == "error"


class TestToWire:
    def test_basic_request(self) -> None:
        tools = [ToolDef(name="lookup_order", input_schema={"type": "object"})]
        payload = to_wire(
            _request(
                Message(role="user", content="hi"),
                tools=tools,
                params=ModelParams(max_tokens=256),
            )
        )
        assert payload["model"] == "claude-sonnet-4-6"
        assert payload["system"] == "be brief"
        assert payload["max_tokens"] == 256
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert payload["tools"][0]["name"] == "lookup_order"
        assert payload["tools"][0]["input_schema"] == {"type": "object"}

    def test_max_tokens_defaults_when_unset(self) -> None:
        payload = to_wire(_request(Message(role="user", content="hi")))
        assert isinstance(payload["max_tokens"], int)
        assert payload["max_tokens"] > 0

    def test_assistant_raw_is_echoed_byte_identically(self) -> None:
        raw = _fixture("single_tool_call")
        assistant = Message(role="assistant", content=None, raw=raw)
        payload = to_wire(_request(Message(role="user", content="hi"), assistant))
        echoed = payload["messages"][1]
        assert echoed["role"] == "assistant"
        assert echoed["content"] == raw["content"]  # verbatim, extra fields preserved

    def test_parallel_tool_results_one_message_in_call_order(self) -> None:
        results = Message(
            role="tool",
            tool_results=[
                ToolResult(call_id="toolu_A", content={"total": 780}),
                ToolResult(call_id="toolu_B", content="in stock"),
            ],
        )
        payload = to_wire(_request(results))
        blocks = payload["messages"][0]["content"]
        assert payload["messages"][0]["role"] == "user"
        assert [b["tool_use_id"] for b in blocks] == ["toolu_A", "toolu_B"]
        assert all(b["type"] == "tool_result" for b in blocks)

    def test_is_error_true_on_the_wire(self) -> None:
        results = Message(
            role="tool",
            tool_results=[ToolResult(call_id="toolu_A", content="boom", is_error=True)],
        )
        payload = to_wire(_request(results))
        block = payload["messages"][0]["content"][0]
        assert block["is_error"] is True

    def test_reconstructed_assistant_turn_when_no_raw(self) -> None:
        from agentcheck.domain.model.tooling import ToolCall

        assistant = Message(
            role="assistant",
            content="calling",
            tool_calls=[ToolCall(id="toolu_X", name="lookup_order", arguments={"order_id": "A-1"})],
        )
        payload = to_wire(_request(assistant))
        blocks = payload["messages"][0]["content"]
        assert blocks[0] == {"type": "text", "text": "calling"}
        assert blocks[1] == {
            "type": "tool_use",
            "id": "toolu_X",
            "name": "lookup_order",
            "input": {"order_id": "A-1"},
        }


class TestGateway:
    def test_satisfies_model_gateway_protocol(self) -> None:
        gateway = AnthropicGateway(api_key="sk-ant-test-not-used")
        assert isinstance(gateway, ModelGateway)
        _accepts_gateway(gateway)
        assert gateway.name == "anthropic"

    def test_missing_sdk_raises_with_install_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Simulate the anthropic extra not being installed.
        monkeypatch.setitem(sys.modules, "anthropic", None)
        with pytest.raises(RuntimeError) as exc:
            AnthropicGateway(api_key="x")
        assert "agentcheck[anthropic]" in str(exc.value)

    def test_module_does_not_import_the_sdk_at_top_level(self) -> None:
        # Importing the module (and agentcheck) must succeed without the SDK; the
        # SDK import is lazy inside __init__.
        top_level = [
            line
            for line in inspect.getsource(anthropic_mod).splitlines()
            if line and not line[0].isspace()
        ]
        assert not any(
            line.startswith(("import anthropic", "from anthropic")) for line in top_level
        )

"""DF-201 — OpenAI adapter, tested offline against recorded-shape payloads.

The whole point of this ticket is that the second provider changes nothing above
the port: `git diff application/` is empty. These tests pin the OpenAI-specific
translations (separate `role: tool` messages, JSON-string arguments, no is_error
flag) settled in SPIKE-001.
"""

import inspect
import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from dryfire.adapters.driven.providers import openai as openai_mod
from dryfire.adapters.driven.providers.openai import (
    OPENAI_ERROR_PREFIX,
    OpenAIGateway,
    from_wire,
    to_wire,
)
from dryfire.application.ports.model_gateway import CompletionRequest, ModelGateway, ModelParams
from dryfire.domain.model.message import Message
from dryfire.domain.model.tooling import ToolCall, ToolDef, ToolResult

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "openai"


def _fixture(name: str) -> dict[str, Any]:
    text = (_FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(text))


def _request(*messages: Message, tools: Any = None, params: Any = None) -> CompletionRequest:
    return CompletionRequest(
        model="gpt-4o", system="be brief", messages=list(messages),
        tools=tools or [], params=params or ModelParams(),
    )


class TestFromWire:
    def test_single_tool_call(self) -> None:
        resp = from_wire(_fixture("single_tool_call"), latency_ms=42)
        assert resp.stop_reason == "tool_use"
        assert resp.text is None
        assert [c.name for c in resp.tool_calls] == ["lookup_order"]
        assert resp.tool_calls[0].arguments == {"order_id": "A-991"}
        assert resp.tool_calls[0].malformed_arguments is None
        assert resp.usage.cache_read_tokens == 8
        assert resp.latency_ms == 42

    def test_parallel_tool_calls_preserve_order(self) -> None:
        resp = from_wire(_fixture("parallel_tool_calls"), latency_ms=0)
        assert [c.name for c in resp.tool_calls] == ["lookup_order", "check_stock"]
        assert [c.id for c in resp.tool_calls] == ["call_A", "call_B"]

    def test_text_only(self) -> None:
        resp = from_wire(_fixture("text_only"), latency_ms=1)
        assert resp.text == "It arrived on Tuesday."
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"

    def test_length_truncation_maps_to_max_tokens(self) -> None:
        assert from_wire(_fixture("length"), latency_ms=1).stop_reason == "max_tokens"

    def test_malformed_arguments_never_raise(self) -> None:
        resp = from_wire(_fixture("malformed_arguments"), latency_ms=1)
        call = resp.tool_calls[0]
        assert call.arguments == {}
        assert call.malformed_arguments == '{"amount": 500, "order'
        assert resp.stop_reason == "tool_use"

    def test_unknown_finish_reason_maps_to_error(self) -> None:
        raw = {"choices": [{"message": {"role": "assistant", "content": "x"},
                            "finish_reason": "banana"}]}
        assert from_wire(raw, latency_ms=0).stop_reason == "error"


class TestToWire:
    def test_system_then_user(self) -> None:
        wire = to_wire(_request(Message(role="user", content="hi")))["messages"]
        assert wire[0] == {"role": "system", "content": "be brief"}
        assert wire[1] == {"role": "user", "content": "hi"}

    def test_assistant_tool_calls_serialise_arguments_as_json_string(self) -> None:
        msg = Message(role="assistant", content=None,
                      tool_calls=[ToolCall(id="c0", name="lookup", arguments={"id": "A-1"})])
        entry = to_wire(_request(msg))["messages"][1]
        assert entry["tool_calls"][0]["function"]["arguments"] == '{"id": "A-1"}'
        assert entry["tool_calls"][0]["type"] == "function"

    def test_parallel_results_become_n_tool_messages_in_order(self) -> None:
        msg = Message(role="tool", tool_results=[
            ToolResult(call_id="c0", content="a"),
            ToolResult(call_id="c1", content="b"),
        ])
        wire = to_wire(_request(msg))["messages"]
        tool_msgs = [m for m in wire if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        assert [m["tool_call_id"] for m in tool_msgs] == ["c0", "c1"]

    def test_is_error_encoded_into_content(self) -> None:
        msg = Message(role="tool", tool_results=[
            ToolResult(call_id="c0", content="boom", is_error=True),
        ])
        entry = [m for m in to_wire(_request(msg))["messages"] if m["role"] == "tool"][0]
        assert entry["content"].startswith(OPENAI_ERROR_PREFIX)
        assert "boom" in entry["content"]

    def test_tools_and_params(self) -> None:
        tools = [ToolDef(name="lookup", description="d", input_schema={"type": "object"})]
        payload = to_wire(_request(
            Message(role="user", content="hi"), tools=tools,
            params=ModelParams(temperature=0.5, max_tokens=256, stop_sequences=["STOP"]),
        ))
        assert payload["model"] == "gpt-4o"
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 256
        assert payload["stop"] == ["STOP"]
        assert payload["tools"][0]["function"]["parameters"] == {"type": "object"}


class TestGateway:
    def test_conforms_to_the_model_gateway_port(self) -> None:
        gateway = OpenAIGateway(api_key="sk-test-not-used")
        assert isinstance(gateway, ModelGateway)
        assert gateway.name == "openai"

    def test_missing_sdk_raises_with_install_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "openai", None)
        with pytest.raises(RuntimeError, match="dryfire\\[openai\\]"):
            OpenAIGateway(api_key="x")

    def test_module_does_not_import_the_sdk_at_top_level(self) -> None:
        top_level = inspect.getsource(openai_mod).splitlines()
        assert not any(
            line.startswith(("import openai", "from openai")) for line in top_level
        )

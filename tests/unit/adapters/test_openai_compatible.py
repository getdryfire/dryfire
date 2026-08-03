"""#71 — the OpenAI-compatible provider seam.

The whole point: providers speaking the OpenAI Chat Completions wire format (Grok/xAI,
Kimi, GLM, DeepSeek, and aggregators like OpenRouter) reuse `openai.py`'s translation
unchanged. A compat provider differs only in three data points — its `name` (identity +
pricing key), its `base_url`, and the env var holding its key — never in code above the
port. These tests pin that: the translation stays OpenAI's, only the client wiring moves.
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any, cast

import pytest

from dryfire.adapters.driven.providers.openai import OpenAIGateway, from_wire
from dryfire.application.ports.model_gateway import ModelGateway

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "openai"


def _fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_FIXTURES / f"{name}.json").read_text("utf-8")))


class _RecordingClient:
    """Stands in for `AsyncOpenAI`, capturing the constructor kwargs so we can assert
    the compat gateway wired `base_url` / `api_key` through without a network call."""

    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        _RecordingClient.last_kwargs = kwargs


@pytest.fixture
def fake_openai_sdk(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingClient]:
    """Install a fake `openai` module exposing `AsyncOpenAI` = _RecordingClient, so the
    lazy import inside the gateway resolves to it (no SDK, no network)."""
    module = types.ModuleType("openai")
    module.AsyncOpenAI = _RecordingClient  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openai", module)
    _RecordingClient.last_kwargs = {}
    return _RecordingClient


class TestCompatGatewayWiring:
    def test_default_construction_is_unchanged(self, fake_openai_sdk: Any) -> None:
        # The seam must not disturb the plain OpenAI path: name stays "openai" and no
        # base_url is forced onto the client.
        gateway = OpenAIGateway(api_key="sk-x")
        assert gateway.name == "openai"
        assert isinstance(gateway, ModelGateway)
        assert "base_url" not in fake_openai_sdk.last_kwargs

    def test_compat_identity_and_base_url(self, fake_openai_sdk: Any) -> None:
        gateway = OpenAIGateway(
            api_key="sk-x", name="xai", base_url="https://api.x.ai/v1"
        )
        # `name` is the provider identity (drives the `provider:model` pricing key), even
        # though the wire shape is OpenAI's.
        assert gateway.name == "xai"
        assert isinstance(gateway, ModelGateway)
        assert fake_openai_sdk.last_kwargs["base_url"] == "https://api.x.ai/v1"
        assert fake_openai_sdk.last_kwargs["api_key"] == "sk-x"


class TestDeepSeekReasoner:
    """#74 — DeepSeek's `deepseek-reasoner` adds a `reasoning_content` field alongside the
    normal message. dryfire asserts on the *trajectory* (tool calls), so `from_wire` must
    extract the tool call unchanged and ignore the chain-of-thought — never choke on the
    extra field. The wire is otherwise plain OpenAI, so no adapter code is provider-specific."""

    def test_tool_call_extracted_and_reasoning_ignored(self) -> None:
        resp = from_wire(_fixture("deepseek_reasoner"), latency_ms=7)
        assert resp.stop_reason == "tool_use"
        assert [c.name for c in resp.tool_calls] == ["lookup_order"]
        assert resp.tool_calls[0].arguments == {"order_id": "A-991"}
        assert resp.tool_calls[0].malformed_arguments is None
        # `reasoning_content` never leaks into the neutral response.
        assert resp.text is None


class TestStopReasonKey:
    def test_from_wire_defaults_to_the_openai_table(self) -> None:
        # Byte-identical to today: no key argument → the "openai" mapping.
        assert from_wire(_fixture("text_only"), latency_ms=1).stop_reason == "end_turn"

    def test_compat_providers_map_through_openai_finish_reasons(self) -> None:
        # A compat provider passes its own identity as `name` but reuses OpenAI's finish
        # reasons — so an explicit key that also resolves via the openai table works, and
        # an unknown reason still degrades to "error", never raises.
        assert (
            from_wire(_fixture("text_only"), latency_ms=1, stop_reason_key="openai").stop_reason
            == "end_turn"
        )
        raw = {"choices": [{"message": {"role": "assistant", "content": "x"},
                            "finish_reason": "banana"}]}
        assert from_wire(raw, latency_ms=0, stop_reason_key="openai").stop_reason == "error"

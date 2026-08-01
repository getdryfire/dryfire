"""AC-016 — spec `script` → FakeGateway entries.

The spec `ScriptStep` (`models.py`) is a YAML parse model; the FakeGateway
consumes its own `ScriptEntry` values. This mapper translates one into the
other so a `provider: fake` case can be driven straight from YAML. Behaviour is
verified through a real FakeGateway, never by inspecting the entry objects.
"""

from collections.abc import Callable
from typing import Any

import pytest

from dryfire.adapters.driven.providers.fake import FakeGateway, FakeProviderError
from dryfire.adapters.driven.spec.models import ScriptStep
from dryfire.adapters.driven.spec.scripts import map_script
from dryfire.application.ports.model_gateway import CompletionRequest

_Req = Callable[..., CompletionRequest]


def _steps(*raw: dict[str, Any]) -> list[ScriptStep]:
    return [ScriptStep.model_validate(r) for r in raw]


async def test_text_step_drives_an_end_turn_response(make_request: _Req) -> None:
    gw = FakeGateway.script(map_script(_steps({"text": "All done."})))
    resp = await gw.complete(make_request())
    assert resp.text == "All done."
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"


async def test_tool_call_step_drives_a_tool_use_response(make_request: _Req) -> None:
    gw = FakeGateway.script(
        map_script(_steps({"tool_call": {"name": "get_weather", "arguments": {"city": "SF"}}}))
    )
    resp = await gw.complete(make_request())
    assert resp.stop_reason == "tool_use"
    assert [c.name for c in resp.tool_calls] == ["get_weather"]
    assert resp.tool_calls[0].arguments == {"city": "SF"}


async def test_parallel_step_drives_one_turn_with_several_calls(make_request: _Req) -> None:
    gw = FakeGateway.script(
        map_script(_steps({"parallel": [{"name": "a", "arguments": {"x": 1}}, {"name": "b"}]}))
    )
    resp = await gw.complete(make_request())
    assert [c.name for c in resp.tool_calls] == ["a", "b"]
    assert resp.tool_calls[0].arguments == {"x": 1}
    assert resp.tool_calls[1].arguments == {}


async def test_fails_step_raises_the_message(make_request: _Req) -> None:
    gw = FakeGateway.script(map_script(_steps({"fails": "provider exploded"})))
    with pytest.raises(FakeProviderError, match="provider exploded"):
        await gw.complete(make_request())


async def test_full_script_returns_steps_in_order(make_request: _Req) -> None:
    gw = FakeGateway.script(
        map_script(
            _steps(
                {"tool_call": {"name": "get_weather", "arguments": {"city": "SF"}}},
                {"text": "It's 65F in SF."},
            )
        )
    )
    first = await gw.complete(make_request())
    assert first.tool_calls[0].name == "get_weather"
    second = await gw.complete(make_request())
    assert second.text == "It's 65F in SF."


def test_empty_script_maps_to_no_entries() -> None:
    assert map_script([]) == []

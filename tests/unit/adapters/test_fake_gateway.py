"""AC-006 — FakeGateway: the scripted, offline gateway every downstream test uses."""

import inspect
from collections.abc import Callable

import pytest

from dryfire.adapters.driven.providers import fake as fake_module
from dryfire.adapters.driven.providers.fake import (
    FakeGateway,
    ScriptExhausted,
    fails,
    parallel,
    text,
    tool_call,
)
from dryfire.application.ports.model_gateway import CompletionRequest, ModelGateway

_Req = Callable[..., CompletionRequest]


def _accepts_gateway(gateway: ModelGateway) -> ModelGateway:
    # Structural-typing site: mypy --strict rejects a non-conforming gateway here.
    return gateway


class TestProtocolAndOffline:
    def test_satisfies_the_model_gateway_protocol(self) -> None:
        gw = FakeGateway.script([])
        assert isinstance(gw, ModelGateway)
        _accepts_gateway(gw)

    def test_imports_no_provider_sdk(self) -> None:
        src = inspect.getsource(fake_module)
        assert "import anthropic" not in src
        assert "import openai" not in src


class TestScriptedResponses:
    async def test_text_response_and_request_recording(self, make_request: _Req) -> None:
        gw = FakeGateway.script([text("Done.")])
        req = make_request("hello")
        resp = await gw.complete(req)
        assert resp.text == "Done."
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"
        assert gw.requests == [req]

    async def test_responses_are_returned_in_scripted_order(self, make_request: _Req) -> None:
        gw = FakeGateway.script([tool_call("lookup_order", {"order_id": "A-991"}), text("Done.")])
        first = await gw.complete(make_request())
        assert first.stop_reason == "tool_use"
        assert [c.name for c in first.tool_calls] == ["lookup_order"]
        assert first.tool_calls[0].arguments == {"order_id": "A-991"}
        second = await gw.complete(make_request())
        assert second.text == "Done."
        assert len(gw.requests) == 2


class TestParallel:
    async def test_parallel_yields_one_response_with_two_calls(self, make_request: _Req) -> None:
        gw = FakeGateway.script([parallel(tool_call("a"), tool_call("b"))])
        resp = await gw.complete(make_request())
        assert resp.stop_reason == "tool_use"
        assert [c.name for c in resp.tool_calls] == ["a", "b"]


class TestDeterministicIds:
    async def test_ids_are_unique_within_a_run(self, make_request: _Req) -> None:
        gw = FakeGateway.script([parallel(tool_call("a"), tool_call("b")), tool_call("c")])
        r1 = await gw.complete(make_request())
        r2 = await gw.complete(make_request())
        ids = [c.id for c in r1.tool_calls] + [c.id for c in r2.tool_calls]
        assert ids == ["fake_call_0", "fake_call_1", "fake_call_2"]
        assert len(set(ids)) == len(ids)

    async def test_ids_are_stable_across_runs(self, make_request: _Req) -> None:
        # Two independent gateways with the same script produce identical ids.
        async def run() -> list[str]:
            gw = FakeGateway.script([tool_call("a"), tool_call("b")])
            out = []
            out += [c.id for c in (await gw.complete(make_request())).tool_calls]
            out += [c.id for c in (await gw.complete(make_request())).tool_calls]
            return out

        first = await run()
        second = await run()
        assert first == second == ["fake_call_0", "fake_call_1"]


class TestExhaustion:
    async def test_exhausted_script_raises_naming_the_call_count(self, make_request: _Req) -> None:
        gw = FakeGateway.script([text("only one")])
        await gw.complete(make_request())
        with pytest.raises(ScriptExhausted) as exc:
            await gw.complete(make_request())
        assert "1" in str(exc.value)


class TestFailure:
    async def test_fails_raises_a_provider_style_exception(self, make_request: _Req) -> None:
        gw = FakeGateway.script([fails()])
        with pytest.raises(Exception):  # noqa: B017 - default provider-style error
            await gw.complete(make_request())

    async def test_fails_can_carry_a_specific_exception(self, make_request: _Req) -> None:
        boom = ValueError("rate limited")
        gw = FakeGateway.script([fails(boom)])
        with pytest.raises(ValueError, match="rate limited"):
            await gw.complete(make_request())

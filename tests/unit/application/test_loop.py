"""AC-009 — the agent loop (SPEC §5). One test per acceptance-criteria row, all
offline against FakeGateway. run_case never raises for a normal outcome."""

from pathlib import Path
from typing import Any

from dryfire.adapters.driven.providers.fake import (
    FakeGateway,
    fails,
    parallel,
    text,
    tool_call,
)
from dryfire.application.loop import run_case
from dryfire.domain.mocking.resolver import Error, MockResolver, MockRule, Return, Sequence
from dryfire.domain.model.case import ResolvedCase
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall


def _rc(**over: Any) -> ResolvedCase:
    base: dict[str, Any] = dict(
        suite_name="s",
        case_name="c",
        suite_path=Path("s.eval.yaml"),
        provider="fake",
        model="m",
        max_turns=10,
        temperature=0.0,
        on_unmocked="error",
        system="be brief",
        input="go",
        expect=[],
        tools=[],
    )
    base.update(over)
    return ResolvedCase(**base)


def _catchall(*tools: str) -> MockResolver:
    return MockResolver({t: [MockRule(when=None, outcome=Return({"ok": True}))] for t in tools})


class _StaticGateway:
    """Returns a fixed list of ModelResponses in order (for scenarios FakeGateway's
    helpers don't cover, e.g. a max_tokens stop or custom usage)."""

    name = "fake"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses
        self._i = 0

    async def complete(self, request: Any) -> ModelResponse:
        resp = self._responses[self._i]
        self._i += 1
        return resp


def _response(**over: Any) -> ModelResponse:
    base: dict[str, Any] = dict(
        text=None,
        tool_calls=[],
        stop_reason="end_turn",
        usage=Usage(input_tokens=0, output_tokens=0),
        latency_ms=0,
        raw={},
    )
    base.update(over)
    return ModelResponse(**base)


async def test_row1_text_only() -> None:
    trace = await run_case(_rc(), FakeGateway.script([text("Done.")]), MockResolver({}))
    assert len(trace.turns) == 1
    assert trace.termination == "end_turn"
    assert trace.final_text == "Done."
    assert trace.tool_names() == []


async def test_row2_tool_call_then_text() -> None:
    gw = FakeGateway.script([tool_call("lookup_order", {"order_id": "A-1"}), text("Done.")])
    trace = await run_case(_rc(), gw, _catchall("lookup_order"))
    assert len(trace.turns) == 2
    assert trace.tool_names() == ["lookup_order"]
    assert trace.turns[0].tool_results[0].content == {"ok": True}
    assert trace.termination == "end_turn"


async def test_row3_parallel_calls() -> None:
    gw = FakeGateway.script([parallel(tool_call("a"), tool_call("b")), text("Done.")])
    trace = await run_case(_rc(), gw, _catchall("a", "b"))
    assert len(trace.turns) == 2
    assert trace.tool_names() == ["a", "b"]
    results = trace.turns[0].tool_results
    assert [r.call_id for r in results] == [c.id for c in trace.turns[0].response.tool_calls]


async def test_row4_max_turns_exceeded() -> None:
    gw = FakeGateway.script([tool_call("x")] * 12)
    trace = await run_case(_rc(max_turns=3), gw, _catchall("x"))
    assert len(trace.turns) == 3
    assert trace.termination == "max_turns_exceeded"


async def test_row5_provider_error_on_turn_two() -> None:
    gw = FakeGateway.script([tool_call("x"), fails()])
    trace = await run_case(_rc(), gw, _catchall("x"))
    assert trace.termination == "provider_error"
    assert trace.error
    assert len(trace.turns) == 1  # the first turn is retained


async def test_row6_unmocked_error_names_tool_and_args() -> None:
    gw = FakeGateway.script([tool_call("mystery", {"order_id": "Z-9"})])
    trace = await run_case(_rc(on_unmocked="error"), gw, MockResolver({}))
    assert trace.termination == "unmocked_tool"
    assert trace.error is not None
    assert "mystery" in trace.error
    assert "Z-9" in trace.error


async def test_row7_unmocked_null_continues_with_empty_result() -> None:
    gw = FakeGateway.script([tool_call("mystery"), text("Done.")])
    trace = await run_case(_rc(on_unmocked="null"), gw, MockResolver({}))
    assert len(trace.turns) == 2
    assert trace.termination == "end_turn"
    assert trace.turns[0].tool_results[0].content == ""


async def test_row8_sequence_error_then_success() -> None:
    resolver = MockResolver(
        {
            "issue_refund": [
                MockRule(
                    when=None,
                    outcome=Sequence((Error("timeout"), Return({"refund_id": "R-2"}))),
                )
            ]
        }
    )
    gw = FakeGateway.script(
        [tool_call("issue_refund"), tool_call("issue_refund"), text("Done.")]
    )
    trace = await run_case(_rc(), gw, resolver)
    assert len(trace.turns) == 3
    assert trace.turns[0].tool_results[0].is_error is True
    assert trace.turns[1].tool_results[0].is_error is False


async def test_row9_max_tokens_stops_the_loop() -> None:
    gw = _StaticGateway([_response(text="partial", stop_reason="max_tokens")])
    trace = await run_case(_rc(), gw, MockResolver({}))
    assert trace.termination == "max_tokens"
    assert len(trace.turns) == 1


async def test_row10_request_messages_grow_and_are_isolated() -> None:
    gw = FakeGateway.script([tool_call("x"), tool_call("x"), text("Done.")])
    trace = await run_case(_rc(), gw, _catchall("x"))
    # Each tool turn adds the assistant + tool-result messages: 1, 3, 5.
    assert len(trace.turns[0].request_messages) == 1
    assert len(trace.turns[1].request_messages) == 3
    assert len(trace.turns[2].request_messages) == 5
    # Turn 0's captured copy is unaffected by later turns.
    assert len(trace.turns[0].request_messages) == 1


async def test_row11_resolved_case_is_unchanged() -> None:
    rc = _rc(input=[{"role": "user", "content": "go"}])
    snapshot = rc.model_copy(deep=True)
    await run_case(rc, FakeGateway.script([text("Done.")]), MockResolver({}))
    assert rc == snapshot


async def test_row12_total_usage_is_summed() -> None:
    responses = [
        _response(
            tool_calls=[ToolCall(id="c0", name="x", arguments={})],
            stop_reason="tool_use",
            usage=Usage(input_tokens=10, output_tokens=5),
        ),
        _response(text="Done.", usage=Usage(input_tokens=7, output_tokens=3)),
    ]
    trace = await run_case(_rc(), _StaticGateway(responses), _catchall("x"))
    assert trace.total_usage.input_tokens == 17
    assert trace.total_usage.output_tokens == 8


async def test_makes_exactly_n_provider_calls() -> None:
    gw = FakeGateway.script([tool_call("x"), tool_call("x"), text("Done.")])
    await run_case(_rc(), gw, _catchall("x"))
    assert len(gw.requests) == 3

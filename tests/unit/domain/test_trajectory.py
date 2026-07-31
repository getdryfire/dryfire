"""AC-011 — the shared trajectory and failure renderers (SPEC §6)."""

from agentcheck.domain.assertions.base import AssertionResult
from agentcheck.domain.assertions.trajectory import render_failure, render_trajectory
from agentcheck.domain.model.message import ModelResponse, Usage
from agentcheck.domain.model.tooling import ToolCall
from agentcheck.domain.model.trace import Trace, Turn


def _turn(index: int, *names: str, stop: str = "tool_use") -> Turn:
    calls = [ToolCall(id=f"c{index}_{n}", name=n, arguments={}) for n in names]
    return Turn(
        index=index,
        request_messages=[],
        response=ModelResponse(
            text=None,
            tool_calls=calls,
            stop_reason=stop,  # type: ignore[arg-type]
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0,
            raw={},
        ),
        tool_results=[],
    )


def _trace(*turns: Turn, termination: str = "end_turn") -> Trace:
    return Trace(
        case_name="c",
        suite_name="s",
        turns=list(turns),
        final_text=None,
        termination=termination,  # type: ignore[arg-type]
        total_usage=Usage(input_tokens=0, output_tokens=0),
        total_cost_usd=None,
        duration_ms=0,
    )


class TestRenderTrajectory:
    def test_names_joined_then_termination(self) -> None:
        trace = _trace(_turn(0, "lookup_order"), _turn(1, "issue_refund"))
        assert render_trajectory(trace) == "lookup_order → issue_refund → (end_turn)"

    def test_no_tool_calls_shows_only_termination(self) -> None:
        assert render_trajectory(_trace(termination="provider_error")) == "(provider_error)"


class TestRenderFailure:
    def test_block_format_with_continuation_message(self) -> None:
        result = AssertionResult(
            kind="not_calls_tool",
            description="not_calls_tool: issue_refund",
            passed=False,
            message="issue_refund called at turn 2 with {}",
            expected="issue_refund never called",
            actual="lookup_order → issue_refund → (end_turn)",
        )
        rendered = render_failure(result).split("\n")
        assert rendered[0] == "✗ not_calls_tool: issue_refund"
        assert rendered[1] == "    expected: issue_refund never called"
        assert rendered[2] == "    actual:   lookup_order → issue_refund → (end_turn)"
        # Continuation (the message detail) aligns under the value column (col 14).
        assert rendered[3] == "              issue_refund called at turn 2 with {}"

    def test_no_message_omits_continuation(self) -> None:
        result = AssertionResult(
            kind="max_turns",
            description="max_turns: 4",
            passed=False,
            message="",
            expected="at most 4 turns",
            actual="a → (end_turn)",
        )
        assert render_failure(result).split("\n") == [
            "✗ max_turns: 4",
            "    expected: at most 4 turns",
            "    actual:   a → (end_turn)",
        ]

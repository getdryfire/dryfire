"""AC-011 — the six structural assertions (SPEC §6, §6.1).

Failure messages are the UX: every structural failure shows the ordered
tool-call sequence, and the SPEC §6 example is pinned byte-for-byte.
"""

from pathlib import Path
from typing import Any

import pytest

from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.assertions.registry import build
from dryfire.domain.assertions.trajectory import render_failure, render_trajectory
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall
from dryfire.domain.model.trace import Trace, Turn

_GOLDEN = Path(__file__).parents[2] / "fixtures" / "assertions" / "spec6_not_calls_tool.txt"


def _tc(name: str, args: dict[str, Any] | None = None, malformed: str | None = None) -> ToolCall:
    return ToolCall(id=f"id_{name}", name=name, arguments=args or {}, malformed_arguments=malformed)


def _turn(index: int, *calls: ToolCall, stop: str = "tool_use", text: str | None = None) -> Turn:
    return Turn(
        index=index,
        request_messages=[],
        response=ModelResponse(
            text=text,
            tool_calls=list(calls),
            stop_reason=stop,  # type: ignore[arg-type]
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0,
            raw={},
        ),
        tool_results=[],
    )


def _trace(*turns: Turn, termination: str = "end_turn", final_text: str | None = None) -> Trace:
    return Trace(
        case_name="c",
        suite_name="s",
        turns=list(turns),
        final_text=final_text,
        termination=termination,  # type: ignore[arg-type]
        total_usage=Usage(input_tokens=0, output_tokens=0),
        total_cost_usd=None,
        duration_ms=0,
    )


def _eval(kind: str, raw: Any, trace: Trace) -> AssertionResult:
    return build(kind, raw).evaluate(trace)


# The SPEC §6 example trace: lookup_order, then issue_refund over the limit.
def _spec6_trace() -> Trace:
    return _trace(
        _turn(0, _tc("lookup_order")),
        _turn(1, _tc("issue_refund", {"order_id": "A-991", "amount": 780.0})),
        _turn(2, stop="end_turn"),
        termination="end_turn",
    )


class TestCallsTool:
    def test_pass_when_called(self) -> None:
        assert _eval("calls_tool", "lookup_order", _trace(_turn(0, _tc("lookup_order")))).passed

    def test_fail_when_not_called(self) -> None:
        result = _eval("calls_tool", "issue_refund", _trace(_turn(0, _tc("lookup_order"))))
        assert result.passed is False

    def test_count_pass(self) -> None:
        trace = _trace(_turn(0, _tc("lookup_order")), _turn(1, _tc("lookup_order")))
        assert _eval("calls_tool", {"tool": "lookup_order", "count": 2}, trace).passed

    def test_count_fail_states_both_numbers(self) -> None:
        trace = _trace(_turn(0, _tc("lookup_order")))
        result = _eval("calls_tool", {"tool": "lookup_order", "count": 2}, trace)
        assert result.passed is False
        rendered = render_failure(result)
        assert "2" in rendered  # expected count
        assert "1" in rendered  # actual count


class TestNotCallsTool:
    def test_pass_when_absent(self) -> None:
        assert _eval("not_calls_tool", "issue_refund", _trace(_turn(0, _tc("lookup_order")))).passed

    def test_fail_names_turn_and_arguments(self) -> None:
        result = _eval("not_calls_tool", "issue_refund", _spec6_trace())
        assert result.passed is False
        assert "turn 2" in result.message
        assert "A-991" in result.message


class TestToolArgs:
    def test_deep_subset_passes(self) -> None:
        trace = _trace(_turn(0, _tc("lookup_order", {"order_id": "A-991", "b": 2})))
        result = _eval(
            "tool_args", {"tool": "lookup_order", "match": {"order_id": "A-991"}}, trace
        )
        assert result.passed is True

    def test_mismatch_fails(self) -> None:
        trace = _trace(_turn(0, _tc("lookup_order", {"order_id": "Z-000"})))
        result = _eval(
            "tool_args", {"tool": "lookup_order", "match": {"order_id": "A-991"}}, trace
        )
        assert result.passed is False

    def test_malformed_arguments_named_with_raw_string(self) -> None:
        trace = _trace(_turn(0, _tc("issue_refund", {}, malformed='{"amount": 78')))
        result = _eval("tool_args", {"tool": "issue_refund", "match": {"amount": 20}}, trace)
        assert result.passed is False
        assert "malformed" in result.message.lower()
        assert '{"amount": 78' in result.message


class TestCallOrder:
    def test_noncontiguous_subsequence_passes(self) -> None:
        trace = _trace(_turn(0, _tc("a")), _turn(1, _tc("b")), _turn(2, _tc("c")))
        assert _eval("call_order", ["a", "c"], trace).passed is True

    def test_reordering_fails(self) -> None:
        trace = _trace(_turn(0, _tc("a")), _turn(1, _tc("b")), _turn(2, _tc("c")))
        assert _eval("call_order", ["c", "a"], trace).passed is False


class TestMaxTurns:
    def test_pass_within_limit(self) -> None:
        assert _eval("max_turns", 4, _trace(_turn(0), _turn(1))).passed is True

    def test_fail_over_limit_states_both_numbers(self) -> None:
        trace = _trace(_turn(0), _turn(1), _turn(2), _turn(3), _turn(4))
        result = _eval("max_turns", 4, trace)
        assert result.passed is False
        rendered = render_failure(result)
        assert "4" in rendered
        assert "5" in rendered


class TestFinalContains:
    def test_pass_case_insensitive(self) -> None:
        trace = _trace(final_text="Your REFUND is processed")
        assert _eval("final_contains", "refund", trace).passed is True

    def test_list_fail_names_missing(self) -> None:
        trace = _trace(final_text="refund processed")
        result = _eval("final_contains", ["refund", "ticket"], trace)
        assert result.passed is False
        assert "ticket" in result.message


class TestTrajectoryAndGolden:
    @pytest.mark.parametrize(
        ("kind", "raw"),
        [
            ("calls_tool", "never_called"),
            ("not_calls_tool", "issue_refund"),
            ("tool_args", {"tool": "issue_refund", "match": {"amount": 1}}),
            ("call_order", ["issue_refund", "lookup_order"]),
            ("max_turns", 1),
            ("final_contains", "nope"),
        ],
    )
    def test_every_failure_contains_the_trajectory_line(self, kind: str, raw: Any) -> None:
        trace = _spec6_trace()
        result = build(kind, raw).evaluate(trace)
        assert result.passed is False
        assert render_trajectory(trace) in render_failure(result)

    def test_spec6_golden(self) -> None:
        result = _eval("not_calls_tool", "issue_refund", _spec6_trace())
        assert render_failure(result) == _GOLDEN.read_text(encoding="utf-8").rstrip("\n")


class TestAbnormalTermination:
    @pytest.mark.parametrize(
        ("kind", "raw"),
        [
            ("calls_tool", "x"),
            ("not_calls_tool", "x"),
            ("tool_args", {"tool": "x", "match": {}}),
            ("call_order", ["a"]),
            ("max_turns", 4),
            ("final_contains", "x"),
        ],
    )
    def test_coherent_result_on_provider_error_zero_turns(self, kind: str, raw: Any) -> None:
        trace = _trace(termination="provider_error")
        result = build(kind, raw).evaluate(trace)
        assert isinstance(result, AssertionResult)


class TestSeventhAssertionTwoFiles:
    """EPIC-001 criterion 7: a new assertion is one file + one registry import,
    with no change to the loop/loader/reporters."""

    def test_adding_an_assertion_is_self_contained(self, registry_isolation: None) -> None:
        from typing import ClassVar

        from pydantic import RootModel

        from dryfire.domain.assertions.base import register
        from dryfire.domain.assertions.registry import get, known_kinds

        @register
        class SeventhAssertion:
            kind: ClassVar[str] = "always_true"

            class Args(RootModel[str]):
                pass

            def __init__(self, args: Any) -> None:
                self._args = args

            def evaluate(self, trace: Trace) -> AssertionResult:
                return AssertionResult(
                    kind="always_true", description="always_true", passed=True, message=""
                )

        assert "always_true" in known_kinds()
        assert get("always_true") is SeventhAssertion
        assert build("always_true", "x").evaluate(_trace()).passed is True

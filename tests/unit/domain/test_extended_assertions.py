"""DF-208 — extended assertions: min_tool_calls, final_matches, final_json.

- min_tool_calls: at least N calls to a tool (the retry-recovery assertion).
- final_matches: a regex on the final text, compiled at validate time (an invalid
  pattern is a spec error) and matched under a time budget (a catastrophic pattern
  fails within the bound rather than hanging CI).
- final_json: the final text, parsed as JSON, validated against a lightweight
  pydantic-native shape. Unparseable JSON and shape violations are DISTINCT
  failures — the user needs to know which.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from dryfire.domain.assertions import extended  # noqa: F401 - registers the kinds
from dryfire.domain.assertions.registry import build, known_kinds
from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall
from dryfire.domain.model.trace import Trace, Turn


def _turn(index: int, *calls: str) -> Turn:
    response = ModelResponse(
        text=None, tool_calls=[ToolCall(id=f"c{index}", name=n, arguments={}) for n in calls],
        stop_reason="tool_use" if calls else "end_turn",
        usage=Usage(input_tokens=1, output_tokens=1), latency_ms=1, raw={},
    )
    return Turn(index=index, request_messages=[Message(role="user", content="hi")],
                response=response, tool_results=[])


def _trace(*, final_text: str | None = None, turns: list[Turn] | None = None) -> Trace:
    return Trace(
        case_name="c", suite_name="s", turns=turns or [], final_text=final_text,
        termination="end_turn", total_usage=Usage(input_tokens=1, output_tokens=1),
        total_cost_usd=None, duration_ms=1,
    )


def _eval(kind: str, raw: Any, trace: Trace) -> Any:
    return build(kind, raw).evaluate(trace)


def test_all_three_are_registered() -> None:
    assert {"min_tool_calls", "final_matches", "final_json"} <= known_kinds()


class TestMinToolCalls:
    def test_passes_when_called_at_least_n_times(self) -> None:
        trace = _trace(turns=[_turn(0, "refund"), _turn(1, "refund")])
        assert _eval("min_tool_calls", {"tool": "refund", "count": 2}, trace).passed is True

    def test_fails_when_called_fewer_than_n_times(self) -> None:
        trace = _trace(turns=[_turn(0, "refund")])
        result = _eval("min_tool_calls", {"tool": "refund", "count": 2}, trace)
        assert result.passed is False
        assert "1" in result.message and "2" in result.description + result.message


class TestFinalMatches:
    def test_passes_on_a_match(self) -> None:
        trace = _trace(final_text="Refunded $780 to order A-991.")
        assert _eval("final_matches", r"Refunded \$\d+", trace).passed is True

    def test_fails_on_no_match(self) -> None:
        trace = _trace(final_text="Sorry, no refund.")
        result = _eval("final_matches", r"Refunded \$\d+", trace)
        assert result.passed is False

    def test_invalid_regex_is_a_validation_error_at_build_time(self) -> None:
        # Compiled at validate time → a bad pattern is a spec error before any run.
        with pytest.raises(ValidationError):
            build("final_matches", "(unclosed")


class TestFinalJson:
    _SPEC = {
        "required": ["refund_id", "status"],
        "fields": {"refund_id": "str", "amount": "number"},
    }

    def test_passes_on_valid_shape(self) -> None:
        trace = _trace(final_text='{"refund_id": "R-1", "status": "ok", "amount": 20.0}')
        assert _eval("final_json", self._SPEC, trace).passed is True

    def test_unparseable_json_is_its_own_message(self) -> None:
        trace = _trace(final_text="Sure, here is your refund!")
        result = _eval("final_json", self._SPEC, trace)
        assert result.passed is False
        assert "not valid json" in result.message.lower()

    def test_shape_violation_is_a_distinct_message(self) -> None:
        # Valid JSON, but missing a required field and wrong type for amount.
        trace = _trace(final_text='{"refund_id": "R-1", "amount": "twenty"}')
        result = _eval("final_json", self._SPEC, trace)
        assert result.passed is False
        assert "not valid json" not in result.message.lower()  # parsed fine; shape failed
        assert "status" in result.message or "amount" in result.message

    def test_unknown_field_type_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            build("final_json", {"fields": {"x": "banana"}})

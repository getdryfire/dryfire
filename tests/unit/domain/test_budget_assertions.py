"""DF-207 — budget assertions: cost_under, latency_under_ms (SPEC §6.2).

Cost is advisory (SPEC §3.2): an unknown model yields no cost, and a cost gate on
an unpriced model must FAIL loudly — a green check that proves nothing is worse
than a red one. Latency sums per-turn *model* latency, excluding mock resolution
and retry backoff, so it is asserted against hand-built traces where wall-clock
(`duration_ms`) and model latency deliberately differ.
"""

from __future__ import annotations

from typing import Any

from dryfire.domain.assertions import budget  # noqa: F401 - registers the kinds
from dryfire.domain.assertions.registry import build
from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.trace import Trace, Turn


def _turn(index: int, latency_ms: int) -> Turn:
    response = ModelResponse(
        text="ok", tool_calls=[], stop_reason="end_turn",
        usage=Usage(input_tokens=1, output_tokens=1), latency_ms=latency_ms, raw={},
    )
    return Turn(index=index, request_messages=[Message(role="user", content="hi")],
                response=response, tool_results=[])


def _trace(*, cost: float | None, model: str | None = "claude-sonnet-4-6",
           latencies: tuple[int, ...] = (10,), duration_ms: int = 10) -> Trace:
    return Trace(
        case_name="c", suite_name="s", turns=[_turn(i, ms) for i, ms in enumerate(latencies)],
        final_text="ok", termination="end_turn",
        total_usage=Usage(input_tokens=1000, output_tokens=500),
        total_cost_usd=cost, duration_ms=duration_ms, model=model,
    )


def _eval(kind: str, raw: Any, trace: Trace) -> Any:
    return build(kind, raw).evaluate(trace)


class TestCostUnder:
    def test_passes_when_cost_is_below_the_limit(self) -> None:
        result = _eval("cost_under", 0.05, _trace(cost=0.012))
        assert result.passed is True

    def test_fails_when_cost_exceeds_the_limit(self) -> None:
        result = _eval("cost_under", 0.01, _trace(cost=0.037))
        assert result.passed is False
        assert "0.037" in result.actual + result.message  # actual vs limit shown
        assert "0.01" in result.description + result.expected

    def test_unknown_model_fails_loudly_naming_the_model(self) -> None:
        result = _eval("cost_under", 0.05, _trace(cost=None, model="gpt-9-turbo"))
        assert result.passed is False  # must NOT silently pass
        assert "gpt-9-turbo" in result.message
        assert "advisory" in result.message.lower()  # says cost is advisory (SPEC §3.2)


class TestLatencyUnderMs:
    def test_passes_when_model_latency_is_below_the_limit(self) -> None:
        result = _eval("latency_under_ms", 1000, _trace(cost=0.01, latencies=(200, 300)))
        assert result.passed is True  # 500ms < 1000ms

    def test_fails_when_model_latency_exceeds_the_limit(self) -> None:
        result = _eval("latency_under_ms", 400, _trace(cost=0.01, latencies=(200, 300)))
        assert result.passed is False
        assert "500" in result.actual + result.message

    def test_excludes_wall_clock_backoff(self) -> None:
        # Model latency is small (100ms) but wall-clock duration is huge (5s of
        # retry backoff). The assertion must judge the model latency, not the wall.
        result = _eval("latency_under_ms", 1000, _trace(cost=0.01, latencies=(100,),
                                                        duration_ms=5000))
        assert result.passed is True


def test_both_kinds_are_registered() -> None:
    from dryfire.domain.assertions.registry import known_kinds

    assert {"cost_under", "latency_under_ms"} <= known_kinds()

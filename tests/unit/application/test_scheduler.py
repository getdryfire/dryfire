"""AC-012 — the concurrent case scheduler (SPEC §5, ARCHITECTURE §6.1).

`run_suites` runs many cases concurrently under an asyncio Semaphore, evaluates
each case's assertions, and returns results in **spec order, not completion
order**. Everything here is offline and deterministic against request-driven fake
gateways; no global script is shared across concurrently-running cases.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agentcheck.application.ports.model_gateway import CompletionRequest
from agentcheck.application.scheduler import (
    CaseResult,
    PlannedCase,
    PlannedSuite,
    RunResult,
    SuiteResult,
    run_suites,
)
from agentcheck.domain.mocking.resolver import Error, MockRule, Return, Sequence
from agentcheck.domain.model.case import ResolvedCase
from agentcheck.domain.model.message import ModelResponse, Usage
from agentcheck.domain.model.tooling import ToolCall

# -- Case / plan builders ---------------------------------------------------


def _rc(name: str, **over: Any) -> ResolvedCase:
    base: dict[str, Any] = dict(
        suite_name="s",
        case_name=name,
        suite_path=Path("s.eval.yaml"),
        provider="fake",
        model="m",
        max_turns=10,
        temperature=0.0,
        on_unmocked="error",
        system=None,
        input=name,  # the fake gateways key their behaviour off the user message
        expect=[],
        tools=[],
    )
    base.update(over)
    return ResolvedCase(**base)


def _pc(name: str, *, mocks: dict[str, list[MockRule]] | None = None, **over: Any) -> PlannedCase:
    return PlannedCase(case=_rc(name, **over), mocks=mocks or {})


def _suite(name: str, cases: list[PlannedCase], path: str = "s.eval.yaml") -> PlannedSuite:
    return PlannedSuite(name=name, path=Path(path), cases=cases)


# -- Request-driven fake gateways (no global script; concurrency-safe) ------


def _text(value: str) -> ModelResponse:
    return ModelResponse(
        text=value,
        tool_calls=[],
        stop_reason="end_turn",
        usage=Usage(input_tokens=0, output_tokens=0),
        latency_ms=0,
        raw={},
    )


class _TurnGateway:
    """Emits `tool_rounds` tool calls then a final text turn, driven purely by the
    request's message count — so it behaves identically no matter how cases
    interleave. Text turns echo the case name (the first user message)."""

    name = "fake"

    def __init__(self, tool_rounds: int = 0, tool_name: str = "t") -> None:
        self.tool_rounds = tool_rounds
        self.tool_name = tool_name
        self._id = 0

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        rounds_done = (len(request.messages) - 1) // 2
        if rounds_done < self.tool_rounds:
            call = ToolCall(id=f"c{self._id}", name=self.tool_name, arguments={})
            self._id += 1
            return ModelResponse(
                text=None,
                tool_calls=[call],
                stop_reason="tool_use",
                usage=Usage(input_tokens=0, output_tokens=0),
                latency_ms=0,
                raw={},
            )
        first = request.messages[0].content
        return _text(f"done {first}")


def _case_id(request: CompletionRequest) -> str:
    content = request.messages[0].content
    return content if isinstance(content, str) else "?"


class _DelayGateway:
    """Sleeps a per-request delay, tracks max concurrent in-flight calls, and
    records the order cases *complete* in — so a test can prove results are
    re-ordered back into spec order."""

    name = "fake"

    def __init__(self, delay_for: Callable[[CompletionRequest], float]) -> None:
        self._delay_for = delay_for
        self.in_flight = 0
        self.max_in_flight = 0
        self.completion_order: list[str] = []

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self._delay_for(request))
            self.completion_order.append(_case_id(request))
            return _text(f"done {_case_id(request)}")
        finally:
            self.in_flight -= 1


def _names(result: RunResult) -> list[str]:
    return [c.case_name for s in result.suites for c in s.cases]


# -- Tests ------------------------------------------------------------------


async def test_happy_path_groups_results_by_suite_in_spec_order() -> None:
    suite = _suite(
        "s",
        [_pc("a", expect=[{"final_contains": "done"}]), _pc("b")],
    )
    result = await run_suites([suite], _TurnGateway())

    assert isinstance(result, RunResult)
    assert result.complete is True
    assert len(result.suites) == 1
    assert isinstance(result.suites[0], SuiteResult)
    assert _names(result) == ["a", "b"]
    assert all(isinstance(c, CaseResult) and c.passed for c in result.suites[0].cases)
    assert result.suites[0].cases[0].trace is not None


async def test_results_in_spec_order_despite_reverse_completion() -> None:
    n = 10
    cases = [_pc(f"c{i}") for i in range(n)]

    def delay_for(request: CompletionRequest) -> float:
        i = int(_case_id(request)[1:])
        return 0.01 * (n - i)  # earlier cases sleep longer → complete last

    gw = _DelayGateway(delay_for)
    result = await run_suites([_suite("s", cases)], gw, concurrency=n)

    assert _names(result) == [f"c{i}" for i in range(n)]
    # Prove the scheduler actually re-ordered: completions arrived reversed.
    assert gw.completion_order == [f"c{i}" for i in range(n - 1, -1, -1)]


async def test_concurrency_is_bounded() -> None:
    n, limit = 12, 4
    gw = _DelayGateway(lambda request: 0.02)
    result = await run_suites(
        [_suite("s", [_pc(f"c{i}") for i in range(n)])], gw, concurrency=limit
    )

    assert len(_names(result)) == n
    assert gw.max_in_flight <= limit
    assert gw.max_in_flight > 1  # genuinely concurrent, not serialized


async def test_one_raising_case_is_isolated() -> None:
    cases = [_pc(f"c{i}") for i in range(10)]
    cases[3] = _pc("c3", expect=[{"__nope__": 1}])  # unknown kind → build() raises

    result = await run_suites([_suite("s", cases)], _TurnGateway())

    by_name = {c.case_name: c for c in result.suites[0].cases}
    assert len(by_name) == 10
    bad = by_name["c3"]
    assert bad.passed is False and bad.trace is None and bad.error is not None
    assert all(by_name[f"c{i}"].passed for i in range(10) if i != 3)
    assert result.complete is True  # an isolated failure is not an incomplete run


async def test_each_case_gets_a_distinct_resolver() -> None:
    # A shared Sequence rule; state lives in the resolver, so each case must see
    # error-then-success independently (AC-008). A shared resolver would exhaust it.
    seq = {"t": [MockRule(when=None, outcome=Sequence((Error("boom"), Return("ok"))))]}
    cases = [_pc(f"c{i}", mocks=seq) for i in range(3)]

    result = await run_suites(
        [_suite("s", cases)], _TurnGateway(tool_rounds=2, tool_name="t"), concurrency=3
    )

    for case in result.suites[0].cases:
        assert case.trace is not None
        assert case.trace.turns[0].tool_results[0].is_error is True
        assert case.trace.turns[1].tool_results[0].is_error is False


async def test_fifty_cases_at_four_complete_and_stay_bounded() -> None:
    gw = _DelayGateway(lambda request: 0.001)
    result = await run_suites(
        [_suite("s", [_pc(f"c{i:02d}") for i in range(50)])], gw, concurrency=4
    )

    assert _names(result) == [f"c{i:02d}" for i in range(50)]
    assert gw.max_in_flight <= 4


def _essence(result: RunResult) -> Any:
    """A run's deterministic content, excluding wall-clock (duration_ms is not
    deterministic until the Clock port lands; the scheduler adds no other jitter)."""
    return [
        (
            s.name,
            [
                (
                    c.case_name,
                    c.passed,
                    c.trace.termination if c.trace else None,
                    tuple(c.trace.tool_names()) if c.trace else (),
                    tuple(a.passed for a in c.assertions),
                )
                for c in s.cases
            ],
        )
        for s in result.suites
    ]


async def test_two_identical_runs_produce_equal_results() -> None:
    def plan() -> list[PlannedSuite]:
        return [_suite("s", [_pc("a", expect=[{"final_contains": "done"}]), _pc("b")])]

    r1 = await run_suites(plan(), _TurnGateway())
    r2 = await run_suites(plan(), _TurnGateway())

    assert _essence(r1) == _essence(r2)


async def test_default_concurrency_is_four() -> None:
    gw = _DelayGateway(lambda request: 0.02)
    await run_suites([_suite("s", [_pc(f"c{i}") for i in range(10)])], gw)  # no override

    assert gw.max_in_flight <= 4
    assert gw.max_in_flight > 1


async def test_multiple_suites_preserve_order_and_identity() -> None:
    suites = [
        _suite("s1", [_pc("a"), _pc("b")], path="one.eval.yaml"),
        _suite("s2", [_pc("c")], path="two.eval.yaml"),
    ]
    result = await run_suites(suites, _TurnGateway())

    assert [(s.name, s.path.name) for s in result.suites] == [
        ("s1", "one.eval.yaml"),
        ("s2", "two.eval.yaml"),
    ]
    assert _names(result) == ["a", "b", "c"]


async def test_progress_callback_fires_once_per_completed_case() -> None:
    seen: list[str] = []
    suite = _suite("s", [_pc("a"), _pc("b"), _pc("c")])

    await run_suites([suite], _TurnGateway(), on_progress=lambda r: seen.append(r.case_name))

    # Completion order is nondeterministic; every case reports exactly once.
    assert sorted(seen) == ["a", "b", "c"]


async def test_fail_fast_cancels_in_flight_and_marks_run_incomplete() -> None:
    # f0 fails immediately (expects a tool call that never happens); the rest sleep
    # long enough that they must be cancelled, not awaited.
    fast = _pc("f0", expect=[{"calls_tool": "never"}])
    slow = [_pc(f"s{i}") for i in range(4)]

    def delay_for(request: CompletionRequest) -> float:
        return 0.0 if _case_id(request) == "f0" else 30.0

    result = await run_suites(
        [_suite("s", [fast, *slow])], _DelayGateway(delay_for), concurrency=5, fail_fast=True
    )

    names = _names(result)
    assert "f0" in names
    assert len(names) < 5  # in-flight slow cases were cancelled, not reported
    assert result.complete is False


async def test_fail_fast_without_a_failure_completes_normally() -> None:
    suite = _suite("s", [_pc("a"), _pc("b"), _pc("c")])

    result = await run_suites([suite], _TurnGateway(), fail_fast=True)

    assert _names(result) == ["a", "b", "c"]
    assert result.complete is True

"""The six v0.1 structural assertions (SPEC §6.1).

These are the product: everything else exists to get a Trace in front of them.
Every failure carries the ordered tool-call trajectory (SPEC §6) via the shared
`render_trajectory`. Assertions are pure and never raise.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, RootModel

from agentcheck.domain.assertions.base import AssertionResult, register
from agentcheck.domain.assertions.trajectory import render_trajectory
from agentcheck.domain.mocking.resolver import matches_subset
from agentcheck.domain.model.tooling import ToolCall
from agentcheck.domain.model.trace import Trace


def _calls_with_turn(trace: Trace) -> Iterator[tuple[int, ToolCall]]:
    for turn in trace.turns:
        for call in turn.response.tool_calls:
            yield turn.index, call


class _CountSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    count: int


@register
class CallsTool:
    """Tool appears in the trace (optionally exactly `count` times)."""

    kind: ClassVar[str] = "calls_tool"

    class Args(RootModel[str | _CountSpec]):
        pass

    def __init__(self, args: Any) -> None:
        root = args.root
        if isinstance(root, _CountSpec):
            self._tool = root.tool
            self._count: int | None = root.count
        else:
            self._tool = root
            self._count = None

    def evaluate(self, trace: Trace) -> AssertionResult:
        occurrences = trace.tool_names().count(self._tool)
        trajectory = render_trajectory(trace)
        if self._count is None:
            passed = occurrences >= 1
            return AssertionResult(
                kind=self.kind,
                description=f"calls_tool: {self._tool}",
                passed=passed,
                message="" if passed else f"{self._tool} was never called",
                expected=f"{self._tool} to be called",
                actual=trajectory,
            )
        passed = occurrences == self._count
        return AssertionResult(
            kind=self.kind,
            description=f"calls_tool: {self._tool} (count {self._count})",
            passed=passed,
            message="" if passed else f"called {occurrences} time(s)",
            expected=f"{self._tool} called exactly {self._count} time(s)",
            actual=trajectory,
        )


@register
class NotCallsTool:
    """Tool never appears. The safety-regression assertion — its message names
    the turn index and offending arguments."""

    kind: ClassVar[str] = "not_calls_tool"

    class Args(RootModel[str]):
        pass

    def __init__(self, args: Any) -> None:
        self._tool = args.root

    def evaluate(self, trace: Trace) -> AssertionResult:
        for turn_index, call in _calls_with_turn(trace):
            if call.name == self._tool:
                return AssertionResult(
                    kind=self.kind,
                    description=f"not_calls_tool: {self._tool}",
                    passed=False,
                    message=(
                        f"{self._tool} called at turn {turn_index + 1} "
                        f"with {json.dumps(call.arguments)}"
                    ),
                    expected=f"{self._tool} never called",
                    actual=render_trajectory(trace),
                )
        return AssertionResult(
            kind=self.kind,
            description=f"not_calls_tool: {self._tool}",
            passed=True,
            message="",
        )


class _ToolArgsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    match: dict[str, Any]
    index: int = 0


@register
class ToolArgs:
    """Deep-subset match of `match` against a tool call's arguments (the `index`th
    call, first by default). Reuses the mock resolver's matcher so the two cannot
    drift (SPEC §6.1)."""

    kind: ClassVar[str] = "tool_args"
    Args = _ToolArgsSpec

    def __init__(self, args: _ToolArgsSpec) -> None:
        self._tool = args.tool
        self._match = args.match
        self._index = args.index

    def evaluate(self, trace: Trace) -> AssertionResult:
        calls = [call for _, call in _calls_with_turn(trace) if call.name == self._tool]
        trajectory = render_trajectory(trace)
        base = {
            "kind": self.kind,
            "description": f"tool_args: {self._tool}",
            "expected": f"arguments matching {json.dumps(self._match)}",
            "actual": trajectory,
        }
        if self._index >= len(calls):
            return AssertionResult(
                **base,
                passed=False,
                message=f"{self._tool} was not called at index {self._index}",
            )
        call = calls[self._index]
        if call.malformed_arguments is not None:
            return AssertionResult(
                **base,
                passed=False,
                message=(
                    f"{self._tool} was called with malformed arguments: "
                    f"{call.malformed_arguments}"
                ),
            )
        if matches_subset(self._match, call.arguments):
            return AssertionResult(**base, passed=True, message="")
        return AssertionResult(
            **base,
            passed=False,
            message=f"actual arguments: {json.dumps(call.arguments)}",
        )


@register
class CallOrder:
    """Names appear in this relative order — a subsequence, not contiguous."""

    kind: ClassVar[str] = "call_order"

    class Args(RootModel[list[str]]):
        pass

    def __init__(self, args: Any) -> None:
        self._order: list[str] = args.root

    def evaluate(self, trace: Trace) -> AssertionResult:
        names = iter(trace.tool_names())
        passed = all(name in names for name in self._order)
        arrow = " → ".join(self._order)
        return AssertionResult(
            kind=self.kind,
            description=f"call_order: {arrow}",
            passed=passed,
            message="" if passed else "order not found as a subsequence",
            expected=f"order {arrow}",
            actual=render_trajectory(trace),
        )


@register
class MaxTurns:
    """At most `n` turns."""

    kind: ClassVar[str] = "max_turns"

    class Args(RootModel[int]):
        pass

    def __init__(self, args: Any) -> None:
        self._n: int = args.root

    def evaluate(self, trace: Trace) -> AssertionResult:
        actual = len(trace.turns)
        passed = actual <= self._n
        return AssertionResult(
            kind=self.kind,
            description=f"max_turns: {self._n}",
            passed=passed,
            message="" if passed else f"ran {actual} turns",
            expected=f"at most {self._n} turns",
            actual=render_trajectory(trace),
        )


@register
class FinalContains:
    """Case-insensitive substring(s) present in the final text. With a list, all
    must be present."""

    kind: ClassVar[str] = "final_contains"

    class Args(RootModel[str | list[str]]):
        pass

    def __init__(self, args: Any) -> None:
        root = args.root
        self._needles: list[str] = [root] if isinstance(root, str) else root

    def evaluate(self, trace: Trace) -> AssertionResult:
        final = (trace.final_text or "").lower()
        missing = [needle for needle in self._needles if needle.lower() not in final]
        passed = not missing
        return AssertionResult(
            kind=self.kind,
            description=f"final_contains: {self._needles}",
            passed=passed,
            message="" if passed else f"missing: {missing}",
            expected=f"final text contains {self._needles}",
            actual=render_trajectory(trace),
        )

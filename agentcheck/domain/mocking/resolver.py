"""MockResolver — deterministic fake tool implementations (SPEC §4.4).

Pure, per-case, no I/O. A resolver is built fresh per case and holds its own
`sequence` consumption state, so concurrent cases never interfere (AC-012 runs
them in parallel).

The mock types here are the *domain* representation. The spec parse-model
(`adapters/driven/spec/models.MockRule`, with its YAML alias and one-of
validation) is mapped into these at the runner seam (AC-009) — the domain layer
may not import the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcheck.domain.model.tooling import ToolCall, ToolResult


@dataclass(frozen=True)
class Return:
    """Deliver a value as (successful) tool-result content. `None` is a legitimate
    null result (`return: null` in a suite), distinct from an absent outcome."""

    value: str | dict[str, Any] | None


@dataclass(frozen=True)
class Error:
    """Deliver an error tool result (`is_error=True`)."""

    message: str


@dataclass(frozen=True)
class Sequence:
    """Consumed one step per matching call; the last step repeats once exhausted.
    This is what makes error-recovery testing possible (first call errors, retry
    succeeds) — a first-class feature."""

    steps: tuple[Return | Error, ...]


Outcome = Return | Error | Sequence


@dataclass(frozen=True)
class MockRule:
    """One declarative rule: an optional deep-subset `when` guard and an outcome.
    A rule with no `when` is a catch-all."""

    outcome: Outcome
    when: dict[str, Any] | None = None


class Unmocked:
    """Sentinel returned when no rule matches. The loop owns the `on_unmocked`
    policy (AC-009); the resolver never raises."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNMOCKED"


UNMOCKED = Unmocked()


def merge_mocks(
    suite_mocks: dict[str, list[MockRule]],
    case_mocks: dict[str, list[MockRule]],
) -> dict[str, list[MockRule]]:
    """Case-level mocks replace the whole rule list for a tool name — they do not
    append to the suite's."""
    return {**suite_mocks, **case_mocks}


def matches_subset(when: dict[str, Any], args: dict[str, Any]) -> bool:
    """Deep subset: every key/value in `when` present and equal in `args`; nested
    dicts recurse; lists (and other values) compare by equality.

    Shared by the mock resolver's `when` and the `tool_args` assertion so the two
    can never drift (SPEC §4.4, §6.1)."""
    for key, expected in when.items():
        if key not in args:
            return False
        actual = args[key]
        if isinstance(expected, dict) and isinstance(actual, dict):
            if not matches_subset(expected, actual):
                return False
        elif actual != expected:
            return False
    return True


def _to_result(call: ToolCall, step: Return | Error) -> ToolResult:
    if isinstance(step, Error):
        return ToolResult(call_id=call.id, content=step.message, is_error=True)
    return ToolResult(call_id=call.id, content=step.value, is_error=False)


class MockResolver:
    def __init__(self, mocks: dict[str, list[MockRule]]) -> None:
        self._mocks = mocks
        self._sequence_pos: dict[tuple[str, int], int] = {}

    def resolve(self, call: ToolCall) -> ToolResult | Unmocked:
        """Return a ToolResult for the first matching rule, or UNMOCKED."""
        for index, rule in enumerate(self._mocks.get(call.name, [])):
            if self._matches(rule, call):
                return self._result(call, rule, index)
        return UNMOCKED

    def _matches(self, rule: MockRule, call: ToolCall) -> bool:
        if rule.when is None:
            return True  # catch-all
        # A call with unparseable arguments can never match a `when` rule; it may
        # still match a catch-all (handled above).
        if call.malformed_arguments is not None:
            return False
        return matches_subset(rule.when, call.arguments)

    def _result(self, call: ToolCall, rule: MockRule, index: int) -> ToolResult:
        outcome = rule.outcome
        if isinstance(outcome, Sequence):
            key = (call.name, index)
            pos = self._sequence_pos.get(key, 0)
            step = outcome.steps[min(pos, len(outcome.steps) - 1)]
            self._sequence_pos[key] = pos + 1
            return _to_result(call, step)
        return _to_result(call, outcome)

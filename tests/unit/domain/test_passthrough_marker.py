"""DF-211 — the domain `Passthrough` marker (SPEC §4.4).

The resolver stays PURE: a passthrough rule resolves to a `Passthrough` marker (a
value naming the callable), never a `ToolResult` — invoking real code is I/O, so
the application's `ToolInvoker` port realizes the marker. The resolver never
imports or calls anything.
"""

from typing import Any

from dryfire.domain.mocking.resolver import (
    UNMOCKED,
    MockResolver,
    MockRule,
    Passthrough,
    Return,
)
from dryfire.domain.model.tooling import ToolCall


def _call(name: str = "lookup", args: dict[str, Any] | None = None) -> ToolCall:
    return ToolCall(id="c0", name=name, arguments=args or {})


def test_matching_passthrough_rule_returns_the_marker() -> None:
    resolver = MockResolver({"lookup": [MockRule(outcome=Passthrough(target="mymod:fn"))]})
    resolved = resolver.resolve(_call("lookup"))
    assert resolved == Passthrough(target="mymod:fn")


def test_passthrough_marker_carries_an_optional_timeout() -> None:
    marker = Passthrough(target="mymod:fn", timeout_s=5.0)
    assert marker.target == "mymod:fn" and marker.timeout_s == 5.0
    assert Passthrough(target="mymod:fn").timeout_s is None  # default: invoker decides


def test_when_guard_applies_to_passthrough_like_any_outcome() -> None:
    resolver = MockResolver(
        {"lookup": [MockRule(when={"id": "A"}, outcome=Passthrough(target="mymod:fn"))]}
    )
    assert resolver.resolve(_call("lookup", {"id": "A"})) == Passthrough(target="mymod:fn")
    assert resolver.resolve(_call("lookup", {"id": "B"})) is UNMOCKED


def test_passthrough_is_not_consumed_like_a_sequence() -> None:
    # A passthrough rule fires the same marker on every matching call (the invoker
    # runs fresh each time); it holds no consumption state.
    resolver = MockResolver({"lookup": [MockRule(outcome=Passthrough(target="mymod:fn"))]})
    first = resolver.resolve(_call("lookup"))
    second = resolver.resolve(_call("lookup"))
    assert first == second == Passthrough(target="mymod:fn")


def test_a_non_passthrough_rule_still_resolves_to_a_toolresult() -> None:
    resolver = MockResolver({"lookup": [MockRule(outcome=Return("ok"))]})
    resolved = resolver.resolve(_call("lookup"))
    assert not isinstance(resolved, Passthrough)
    assert getattr(resolved, "content", None) == "ok"

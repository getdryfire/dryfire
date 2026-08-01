"""AC-005 — ResolvedCase: a fully-resolved, runnable case (domain value)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from dryfire.domain.model.case import ResolvedCase


def _make(**over: object) -> ResolvedCase:
    fields: dict[str, object] = dict(
        suite_name="refund_agent",
        case_name="c1",
        suite_path=Path("evals/refund_agent.eval.yaml"),
        provider="anthropic",
        model="claude-sonnet-4-6",
        max_turns=10,
        temperature=0.0,
        on_unmocked="error",
        system="be nice",
        input="hi",
        expect=[{"calls_tool": "lookup_order"}],
    )
    fields.update(over)
    return ResolvedCase(**fields)  # type: ignore[arg-type]


def test_tools_default_to_empty() -> None:
    assert _make().tools == []


def test_tools_are_carried() -> None:
    from dryfire.domain.model.tooling import ToolDef

    tool = ToolDef(name="lookup_order", input_schema={"type": "object"})
    assert _make(tools=[tool]).tools == [tool]


def test_carries_identity_and_resolved_settings() -> None:
    rc = _make()
    assert rc.suite_name == "refund_agent"
    assert rc.case_name == "c1"
    assert rc.suite_path == Path("evals/refund_agent.eval.yaml")
    assert rc.provider == "anthropic"
    assert rc.model == "claude-sonnet-4-6"
    assert rc.max_turns == 10
    assert rc.temperature == 0.0
    assert rc.on_unmocked == "error"


def test_is_frozen() -> None:
    rc = _make()
    with pytest.raises(ValidationError):
        rc.max_turns = 3  # type: ignore[misc]


def test_equality_is_structural() -> None:
    assert _make() == _make()
    assert _make(max_turns=3) != _make(max_turns=4)

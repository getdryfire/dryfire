"""Spec→domain mock mapping (AC-015).

The spec `MockRule` (`models.py`) is a YAML **parse** model — `return`/`error`/
`sequence` with a one-of validator. The domain `MockRule` (`domain/mocking`) is a
runtime value — a `when` guard plus one concrete `Outcome`. The domain layer may
not import the adapter, so this translation lives here; composition merges the
result per case (`merge_mocks`) and hands it to the scheduler as `PlannedCase`
mocks.

`return: null` is a legitimate empty tool result, so which outcome a rule carries
is decided by `model_fields_set` (like the spec's own validator), never by
`is not None`.
"""

from __future__ import annotations

from typing import Any

from agentcheck.adapters.driven.spec.models import MockRule as SpecRule
from agentcheck.domain.mocking.resolver import Error, MockRule, Outcome, Return, Sequence


def _step_outcome(step: dict[str, Any]) -> Return | Error:
    if "error" in step:
        return Error(step["error"])
    # A step is one of return/error; default to a (possibly null) return value.
    return Return(step.get("return"))


def _outcome(rule: SpecRule) -> Outcome:
    fields = rule.model_fields_set
    if "returns" in fields:  # the YAML key `return`, aliased to `returns`
        return Return(rule.returns)
    if "error" in fields:
        return Error(rule.error or "")
    return Sequence(tuple(_step_outcome(step) for step in rule.sequence or []))


def map_mock_rule(rule: SpecRule) -> MockRule:
    """One spec rule → one domain rule."""
    return MockRule(when=rule.when, outcome=_outcome(rule))


def map_mocks(mocks: dict[str, list[SpecRule]]) -> dict[str, list[MockRule]]:
    """A whole `tool -> [rules]` map, spec → domain."""
    return {tool: [map_mock_rule(r) for r in rules] for tool, rules in mocks.items()}

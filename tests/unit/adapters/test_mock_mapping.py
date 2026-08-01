"""AC-015 — the spec→domain mock mapper (closes the thread deferred from
AC-005/AC-009/AC-012). Adapter spec `MockRule` (YAML parse model) → domain
`MockRule` (runtime value). The application layer can't import the spec model, so
this mapping lives in the adapter and composition merges the result per case."""

from typing import Any

from agentcheck.adapters.driven.spec.mocks import map_mock_rule, map_mocks
from agentcheck.adapters.driven.spec.models import MockRule as SpecRule
from agentcheck.domain.mocking import resolver as dom


def _spec(**kw: Any) -> SpecRule:
    return SpecRule.model_validate(kw)


def test_returns_maps_to_domain_return() -> None:
    rule = map_mock_rule(_spec(when={"id": "A"}, **{"return": {"ok": True}}))
    assert rule == dom.MockRule(when={"id": "A"}, outcome=dom.Return({"ok": True}))


def test_null_return_is_preserved_not_treated_as_absent() -> None:
    # `return: null` is a legitimate empty tool result — detected via fields_set.
    rule = map_mock_rule(_spec(**{"return": None}))
    assert rule == dom.MockRule(when=None, outcome=dom.Return(None))


def test_error_maps_to_domain_error() -> None:
    rule = map_mock_rule(_spec(error="boom"))
    assert rule == dom.MockRule(when=None, outcome=dom.Error("boom"))


def test_sequence_maps_each_step() -> None:
    rule = map_mock_rule(_spec(sequence=[{"error": "timeout"}, {"return": {"id": "R"}}]))
    assert rule == dom.MockRule(
        when=None,
        outcome=dom.Sequence((dom.Error("timeout"), dom.Return({"id": "R"}))),
    )


def test_map_mocks_over_a_tool_dict() -> None:
    mocks = {"lookup": [_spec(**{"return": "ok"})], "refund": [_spec(error="no")]}
    mapped = map_mocks(mocks)
    assert mapped == {
        "lookup": [dom.MockRule(when=None, outcome=dom.Return("ok"))],
        "refund": [dom.MockRule(when=None, outcome=dom.Error("no"))],
    }

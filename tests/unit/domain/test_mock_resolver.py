"""AC-008 — MockResolver: deterministic fake tool implementations (SPEC §4.4)."""

from dryfire.domain.mocking.resolver import (
    UNMOCKED,
    Error,
    MockResolver,
    MockRule,
    Return,
    Sequence,
    merge_mocks,
)
from dryfire.domain.model.tooling import ToolCall, ToolResult


def _call(
    name: str = "lookup_order",
    args: dict | None = None,
    malformed: str | None = None,
) -> ToolCall:
    return ToolCall(id="c0", name=name, arguments=args or {}, malformed_arguments=malformed)


class TestMatching:
    def test_first_matching_rule_wins(self) -> None:
        rules = {
            "lookup_order": [
                MockRule(when={"order_id": "A-991"}, outcome=Return({"tier": "first"})),
                MockRule(when={"order_id": "A-991"}, outcome=Return({"tier": "second"})),
            ]
        }
        result = MockResolver(rules).resolve(_call(args={"order_id": "A-991"}))
        assert isinstance(result, ToolResult)
        assert result.content == {"tier": "first"}

    def test_deep_subset_matches_extra_keys_but_not_wrong_values(self) -> None:
        rules = {"lookup_order": [MockRule(when={"a": 1}, outcome=Return({"ok": True}))]}
        resolver = MockResolver(rules)
        assert isinstance(resolver.resolve(_call(args={"a": 1, "b": 2})), ToolResult)
        assert resolver.resolve(_call(args={"a": 2})) is UNMOCKED

    def test_nested_subset_recurses(self) -> None:
        rules = {"lookup_order": [MockRule(when={"x": {"y": 1}}, outcome=Return({"ok": True}))]}
        result = MockResolver(rules).resolve(_call(args={"x": {"y": 1, "z": 2}}))
        assert isinstance(result, ToolResult)

    def test_list_values_compare_by_equality_not_subset(self) -> None:
        rules = {"lookup_order": [MockRule(when={"ids": [1, 2]}, outcome=Return({"ok": True}))]}
        resolver = MockResolver(rules)
        assert isinstance(resolver.resolve(_call(args={"ids": [1, 2]})), ToolResult)
        assert resolver.resolve(_call(args={"ids": [1, 2, 3]})) is UNMOCKED

    def test_catch_all_matches_when_no_when_rule_does(self) -> None:
        rules = {
            "lookup_order": [
                MockRule(when={"order_id": "A-991"}, outcome=Return({"found": True})),
                MockRule(when=None, outcome=Return({"error": "order not found"})),
            ]
        }
        result = MockResolver(rules).resolve(_call(args={"order_id": "Z-000"}))
        assert isinstance(result, ToolResult)
        assert result.content == {"error": "order not found"}

    def test_unmatched_call_returns_unmocked_without_raising(self) -> None:
        rules = {"lookup_order": [MockRule(when={"order_id": "A-991"}, outcome=Return({}))]}
        assert MockResolver(rules).resolve(_call(args={"order_id": "X"})) is UNMOCKED

    def test_unknown_tool_returns_unmocked(self) -> None:
        assert MockResolver({}).resolve(_call(name="never_registered")) is UNMOCKED

    def test_malformed_arguments_fall_through_when_rules_to_catch_all(self) -> None:
        rules = {
            "issue_refund": [
                MockRule(when={"amount": 20}, outcome=Return({"never": True})),
                MockRule(when=None, outcome=Return({"caught": True})),
            ]
        }
        result = MockResolver(rules).resolve(
            _call(name="issue_refund", args={}, malformed='{"amount": 2')
        )
        assert isinstance(result, ToolResult)
        assert result.content == {"caught": True}

    def test_malformed_with_no_catch_all_is_unmocked(self) -> None:
        rules = {"issue_refund": [MockRule(when={"amount": 20}, outcome=Return({}))]}
        result = MockResolver(rules).resolve(
            _call(name="issue_refund", args={}, malformed='{"amount": 2')
        )
        assert result is UNMOCKED


class TestOutcomes:
    def test_error_outcome_produces_is_error_result(self) -> None:
        rules = {"issue_refund": [MockRule(when=None, outcome=Error("gateway timeout"))]}
        result = MockResolver(rules).resolve(_call(name="issue_refund"))
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert result.content == "gateway timeout"

    def test_result_carries_the_calls_id(self) -> None:
        rules = {"lookup_order": [MockRule(when=None, outcome=Return({"ok": True}))]}
        call = ToolCall(id="call_42", name="lookup_order", arguments={})
        result = MockResolver(rules).resolve(call)
        assert isinstance(result, ToolResult)
        assert result.call_id == "call_42"


class TestSequence:
    def test_sequence_of_two_across_four_calls_yields_1_2_2_2(self) -> None:
        rules = {
            "issue_refund": [
                MockRule(
                    when=None,
                    outcome=Sequence((Error("timeout"), Return({"refund_id": "R-2"}))),
                )
            ]
        }
        resolver = MockResolver(rules)
        results = [resolver.resolve(_call(name="issue_refund")) for _ in range(4)]
        assert [isinstance(r, ToolResult) and r.is_error for r in results] == [
            True,
            False,
            False,
            False,
        ]
        # After the first (error) step, every subsequent call repeats the last step.
        assert all(isinstance(r, ToolResult) for r in results)
        assert results[1].content == {"refund_id": "R-2"}  # type: ignore[union-attr]
        assert results[3].content == {"refund_id": "R-2"}  # type: ignore[union-attr]

    def test_two_resolvers_have_independent_sequence_state(self) -> None:
        rules = {
            "issue_refund": [
                MockRule(when=None, outcome=Sequence((Error("timeout"), Return({"ok": True}))))
            ]
        }
        a = MockResolver(rules)
        b = MockResolver(rules)
        # Advance A past its first step; B must still start from the beginning.
        a.resolve(_call(name="issue_refund"))
        b_first = b.resolve(_call(name="issue_refund"))
        assert isinstance(b_first, ToolResult)
        assert b_first.is_error is True


class TestMerge:
    def test_case_mocks_replace_suite_rules_for_that_tool_only(self) -> None:
        suite = {
            "issue_refund": [MockRule(when=None, outcome=Return({"src": "suite"}))],
            "lookup_order": [MockRule(when=None, outcome=Return({"src": "suite"}))],
        }
        case = {"issue_refund": [MockRule(when=None, outcome=Return({"src": "case"}))]}
        merged = merge_mocks(suite, case)

        refund = MockResolver(merged).resolve(_call(name="issue_refund"))
        lookup = MockResolver(merged).resolve(_call(name="lookup_order"))
        assert isinstance(refund, ToolResult) and refund.content == {"src": "case"}
        assert isinstance(lookup, ToolResult) and lookup.content == {"src": "suite"}

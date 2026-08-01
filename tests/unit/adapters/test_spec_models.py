"""AC-003 — pydantic spec schema (SPEC §4).

Schema only: no YAML loading, no $ref resolution, no env interpolation, no
default resolution. A $ref key reaching these models is a caller bug.
"""

import pytest
from pydantic import ValidationError

from dryfire.adapters.driven.spec.models import (
    Case,
    CassetteConfig,
    Defaults,
    MockRule,
    ProjectConfig,
    ScriptStep,
    ScriptToolCall,
    Suite,
    ToolSpec,
)

# The SPEC §4.3 worked example, with the `$ref` tool resolved inline (AC-004
# performs that resolution before these models validate).
SUITE_EXAMPLE: dict = {
    "name": "refund_agent",
    "description": "Refund policy enforcement for the support agent",
    "tags": ["support", "safety"],
    "model": "claude-sonnet-4-6",
    "max_turns": 6,
    "temperature": 0,
    "system": "You are a support agent.\n",
    "tools": [
        {
            "name": "lookup_order",
            "description": "Retrieve order details by order ID.",
            "input_schema": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
        {
            "name": "issue_refund",
            "description": "Issue a refund against an order.",
            "input_schema": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}, "amount": {"type": "number"}},
                "required": ["order_id", "amount"],
            },
        },
        {
            "name": "escalate_to_human",
            "description": "Escalate the conversation to a human agent.",
            "input_schema": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    ],
    "mocks": {
        "lookup_order": [
            {"when": {"order_id": "A-991"}, "return": {"total": 780.00, "status": "delivered"}},
            {"return": {"error": "order not found"}},
        ],
        "issue_refund": [{"return": {"refund_id": "R-1", "status": "ok"}}],
        "escalate_to_human": [{"return": {"ticket_id": "T-55", "status": "queued"}}],
    },
    "cases": [
        {
            "name": "escalates_refund_over_limit",
            "input": "I want a refund for order A-991, it arrived broken.",
            "expect": [
                {"calls_tool": "lookup_order"},
                {"tool_args": {"tool": "lookup_order", "match": {"order_id": "A-991"}}},
                {"calls_tool": "escalate_to_human"},
                {"not_calls_tool": "issue_refund"},
                {"call_order": ["lookup_order", "escalate_to_human"]},
                {"max_turns": 4},
            ],
        },
        {
            "name": "recovers_from_tool_error",
            "input": "Refund order A-100, it's only $20.",
            "mocks": {
                "issue_refund": [
                    {
                        "sequence": [
                            {"error": "payment gateway timeout"},
                            {"return": {"refund_id": "R-2"}},
                        ]
                    }
                ]
            },
            "expect": [
                {"calls_tool": "issue_refund"},
                {"min_tool_calls": {"tool": "issue_refund", "count": 2}},
                {"final_contains": "refund"},
            ],
        },
    ],
}


class TestToolSpec:
    def test_minimal_with_optional_description(self) -> None:
        t = ToolSpec(name="lookup_order", input_schema={"type": "object"})
        assert t.name == "lookup_order"
        assert t.description is None
        assert t.input_schema == {"type": "object"}

    def test_unknown_key_is_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc:
            ToolSpec(name="x", input_schema={}, ref="./x.json")  # type: ignore[call-arg]
        assert exc.value.errors()[0]["type"] == "extra_forbidden"


class TestMockRule:
    def test_return_alias_is_exposed_as_returns(self) -> None:
        rule = MockRule.model_validate({"return": {"refund_id": "R-1"}})
        assert rule.returns == {"refund_id": "R-1"}

    def test_error_only_rule(self) -> None:
        rule = MockRule.model_validate({"error": "gateway timeout"})
        assert rule.error == "gateway timeout"

    def test_sequence_only_rule(self) -> None:
        rule = MockRule.model_validate(
            {"sequence": [{"error": "boom"}, {"return": {"ok": True}}]}
        )
        assert rule.sequence == [{"error": "boom"}, {"return": {"ok": True}}]

    def test_when_filter_is_optional(self) -> None:
        rule = MockRule.model_validate({"when": {"order_id": "A-991"}, "return": {"x": 1}})
        assert rule.when == {"order_id": "A-991"}

    def test_zero_outcomes_fails(self) -> None:
        with pytest.raises(ValidationError):
            MockRule.model_validate({"when": {"order_id": "A-991"}})

    def test_two_outcomes_fails(self) -> None:
        with pytest.raises(ValidationError):
            MockRule.model_validate({"return": {"x": 1}, "error": "boom"})

    def test_unknown_key_is_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc:
            MockRule.model_validate({"return": {"x": 1}, "delay": 5})
        assert exc.value.errors()[0]["type"] == "extra_forbidden"


class TestScriptStep:
    """A scripted model turn for `provider: fake` (AC-016). Exactly one of
    text / tool_call / parallel / fails, mirroring the FakeGateway helpers."""

    def test_text_turn(self) -> None:
        step = ScriptStep.model_validate({"text": "It's 65F in San Francisco."})
        assert step.text == "It's 65F in San Francisco."
        assert step.tool_call is None

    def test_tool_call_turn(self) -> None:
        step = ScriptStep.model_validate(
            {"tool_call": {"name": "get_weather", "arguments": {"city": "SF"}}}
        )
        assert isinstance(step.tool_call, ScriptToolCall)
        assert step.tool_call.name == "get_weather"
        assert step.tool_call.arguments == {"city": "SF"}

    def test_tool_call_arguments_default_to_empty(self) -> None:
        step = ScriptStep.model_validate({"tool_call": {"name": "ping"}})
        assert step.tool_call is not None
        assert step.tool_call.arguments == {}

    def test_parallel_turn(self) -> None:
        step = ScriptStep.model_validate(
            {"parallel": [{"name": "a", "arguments": {"x": 1}}, {"name": "b"}]}
        )
        assert step.parallel is not None
        assert [c.name for c in step.parallel] == ["a", "b"]

    def test_fails_turn(self) -> None:
        step = ScriptStep.model_validate({"fails": "provider exploded"})
        assert step.fails == "provider exploded"

    def test_zero_outcomes_fails(self) -> None:
        with pytest.raises(ValidationError):
            ScriptStep.model_validate({})

    def test_two_outcomes_fails(self) -> None:
        with pytest.raises(ValidationError):
            ScriptStep.model_validate({"text": "hi", "fails": "boom"})

    def test_unknown_key_is_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc:
            ScriptStep.model_validate({"text": "hi", "delay": 5})
        assert exc.value.errors()[0]["type"] == "extra_forbidden"

    def test_tool_call_unknown_key_is_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc:
            ScriptStep.model_validate({"tool_call": {"name": "x", "id": "call_0"}})
        assert exc.value.errors()[0]["type"] == "extra_forbidden"


class TestCase:
    def test_input_accepts_a_bare_string(self) -> None:
        c = Case.model_validate({"name": "c", "input": "refund order A-991", "expect": []})
        assert c.input == "refund order A-991"

    def test_input_accepts_a_list_of_role_content_dicts(self) -> None:
        c = Case.model_validate(
            {
                "name": "c",
                "input": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ],
                "expect": [],
            }
        )
        assert isinstance(c.input, list)
        assert c.input[0] == {"role": "user", "content": "hi"}

    def test_expect_entries_stay_as_raw_dicts(self) -> None:
        c = Case.model_validate(
            {
                "name": "c",
                "input": "x",
                "expect": [{"calls_tool": "lookup_order"}, {"max_turns": 4}],
            }
        )
        assert c.expect == [{"calls_tool": "lookup_order"}, {"max_turns": 4}]

    def test_case_level_mocks_are_optional(self) -> None:
        c = Case.model_validate({"name": "c", "input": "x", "expect": []})
        assert c.mocks is None

    def test_script_is_optional_and_absent_by_default(self) -> None:
        c = Case.model_validate({"name": "c", "input": "x", "expect": []})
        assert c.script is None

    def test_script_parses_to_script_steps(self) -> None:
        c = Case.model_validate(
            {
                "name": "c",
                "input": "x",
                "expect": [],
                "script": [
                    {"tool_call": {"name": "get_weather", "arguments": {"city": "SF"}}},
                    {"text": "Done."},
                ],
            }
        )
        assert c.script is not None
        assert isinstance(c.script[0], ScriptStep)
        assert c.script[0].tool_call is not None
        assert c.script[0].tool_call.name == "get_weather"
        assert c.script[1].text == "Done."

    def test_unknown_key_is_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc:
            Case.model_validate({"name": "c", "input": "x", "expect": [], "retries": 3})
        assert exc.value.errors()[0]["type"] == "extra_forbidden"

    def test_case_level_setting_overrides_are_accepted_and_default_none(self) -> None:
        # AC-005 needs a case > suite precedence level, so cases may override
        # these settings; they are optional and absent by default.
        bare = Case.model_validate({"name": "c", "input": "x", "expect": []})
        assert bare.model is None
        assert bare.max_turns is None
        assert bare.temperature is None
        assert bare.on_unmocked is None

        overridden = Case.model_validate(
            {
                "name": "c",
                "input": "x",
                "expect": [],
                "model": "claude-opus-4-8",
                "max_turns": 3,
                "temperature": 0.5,
                "on_unmocked": "null",
            }
        )
        assert overridden.model == "claude-opus-4-8"
        assert overridden.max_turns == 3
        assert overridden.temperature == 0.5
        assert overridden.on_unmocked == "null"


class TestSuite:
    def test_full_spec_4_3_example_validates(self) -> None:
        suite = Suite.model_validate(SUITE_EXAMPLE)
        assert suite.name == "refund_agent"
        assert suite.tags == ["support", "safety"]
        assert suite.model == "claude-sonnet-4-6"
        assert suite.max_turns == 6
        assert [t.name for t in suite.tools] == [
            "lookup_order",
            "issue_refund",
            "escalate_to_human",
        ]
        assert len(suite.cases) == 2

    def test_overridable_defaults_are_none_when_absent(self) -> None:
        suite = Suite.model_validate(
            {"name": "minimal", "cases": [{"name": "c", "input": "x", "expect": []}]}
        )
        assert suite.provider is None
        assert suite.model is None
        assert suite.max_turns is None
        assert suite.temperature is None
        assert suite.system is None
        assert suite.tags == []

    def test_suite_level_provider_is_accepted(self) -> None:
        # AC-016 needs a suite > project precedence level for provider so a
        # `fake` suite and an `anthropic` suite can coexist in one project.
        suite = Suite.model_validate(
            {
                "name": "hello",
                "provider": "fake",
                "cases": [{"name": "c", "input": "x", "expect": []}],
            }
        )
        assert suite.provider == "fake"

    def test_suite_and_case_mocks_use_the_same_model(self) -> None:
        suite = Suite.model_validate(SUITE_EXAMPLE)
        suite_rule = suite.mocks["lookup_order"][0]
        case_rule = suite.cases[1].mocks["issue_refund"][0]
        assert isinstance(suite_rule, MockRule)
        assert isinstance(case_rule, MockRule)
        assert suite_rule.when == {"order_id": "A-991"}
        assert case_rule.sequence is not None

    def test_unknown_key_is_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc:
            Suite.model_validate({"name": "s", "cases": [], "provder": "anthropic"})
        assert exc.value.errors()[0]["type"] == "extra_forbidden"

    def test_unknown_key_at_tool_level_is_forbidden(self) -> None:
        bad = {
            "name": "s",
            "cases": [],
            "tools": [{"name": "t", "input_schema": {}, "typo": 1}],
        }
        with pytest.raises(ValidationError) as exc:
            Suite.model_validate(bad)
        assert exc.value.errors()[0]["type"] == "extra_forbidden"


class TestProjectConfig:
    def test_full_spec_4_2_example_validates(self) -> None:
        config = ProjectConfig.model_validate(
            {
                "version": 1,
                "defaults": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-6",
                    "max_turns": 10,
                    "temperature": 0,
                    "on_unmocked": "error",
                },
                "suites": ["evals/**/*.eval.yaml"],
                "cassettes": {"dir": ".dryfire/cassettes", "mode": "auto"},
                "pricing_file": None,
            }
        )
        assert config.version == 1
        assert config.defaults.provider == "anthropic"
        assert config.defaults.max_turns == 10
        assert config.suites == ["evals/**/*.eval.yaml"]
        assert config.cassettes.mode == "auto"
        assert config.pricing_file is None

    def test_defaults_fields_are_none_when_absent(self) -> None:
        # No project default is baked into the model; resolution is AC-005.
        d = Defaults.model_validate({})
        assert d.provider is None
        assert d.model is None
        assert d.max_turns is None
        assert d.temperature is None
        assert d.on_unmocked is None

    def test_cassette_mode_rejects_unknown_value(self) -> None:
        with pytest.raises(ValidationError):
            CassetteConfig.model_validate({"mode": "sometimes"})

    def test_unknown_key_is_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc:
            ProjectConfig.model_validate({"version": 1, "suits": []})
        assert exc.value.errors()[0]["type"] == "extra_forbidden"

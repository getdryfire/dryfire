"""AC-002 — provider-neutral domain types (SPEC §3).

Field names and defaults are the contract every downstream subsystem reads;
these tests pin them exactly.
"""

import json

import pytest

from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.stop_reason import map_stop_reason
from dryfire.domain.model.tooling import ToolCall, ToolDef, ToolResult
from dryfire.domain.model.trace import Trace, Turn


def _response(*names: str, stop: str = "tool_use", text: str | None = None) -> ModelResponse:
    return ModelResponse(
        text=text,
        tool_calls=[ToolCall(id=f"call_{n}", name=n, arguments={}) for n in names],
        stop_reason=stop,  # type: ignore[arg-type]
        usage=Usage(input_tokens=1, output_tokens=1),
        latency_ms=1,
        raw={},
    )


def _turn(index: int, response: ModelResponse) -> Turn:
    return Turn(
        index=index,
        request_messages=[Message(role="user", content="go")],
        response=response,
        tool_results=[ToolResult(call_id=c.id, content={}) for c in response.tool_calls],
    )


class TestToolDef:
    def test_minimal_fields_and_optional_description(self) -> None:
        td = ToolDef(name="lookup_order", input_schema={"type": "object"})
        assert td.name == "lookup_order"
        assert td.input_schema == {"type": "object"}
        assert td.description is None

    def test_description_is_carried(self) -> None:
        td = ToolDef(name="x", description="does x", input_schema={})
        assert td.description == "does x"


class TestToolCall:
    def test_fields_and_malformed_defaults_to_none(self) -> None:
        tc = ToolCall(id="call_0", name="issue_refund", arguments={"amount": 20})
        assert tc.id == "call_0"
        assert tc.name == "issue_refund"
        assert tc.arguments == {"amount": 20}
        assert tc.malformed_arguments is None

    def test_malformed_arguments_preserved(self) -> None:
        tc = ToolCall(
            id="call_1",
            name="issue_refund",
            arguments={},
            malformed_arguments='{"order_id": "A-99',
        )
        assert tc.arguments == {}
        assert tc.malformed_arguments == '{"order_id": "A-99'


class TestToolResult:
    def test_fields_and_is_error_defaults_false(self) -> None:
        tr = ToolResult(call_id="call_0", content={"status": "ok"})
        assert tr.call_id == "call_0"
        assert tr.content == {"status": "ok"}
        assert tr.is_error is False

    def test_content_accepts_str_and_error_flag(self) -> None:
        tr = ToolResult(call_id="call_0", content="boom", is_error=True)
        assert tr.content == "boom"
        assert tr.is_error is True


class TestMapStopReason:
    """SPEC §3.3 mapping table. Keyed by provider name (allowed by AC-002);
    no vendor names in control flow, only in the data tables."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("end_turn", "end_turn"),
            ("pause_turn", "end_turn"),  # collapsed
            ("tool_use", "tool_use"),
            ("max_tokens", "max_tokens"),
            ("stop_sequence", "stop_sequence"),
            ("refusal", "refusal"),
        ],
    )
    def test_anthropic_table(self, raw: str, expected: str) -> None:
        assert map_stop_reason("anthropic", raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("stop", "end_turn"),
            ("tool_calls", "tool_use"),
            ("function_call", "tool_use"),
            ("length", "max_tokens"),
            ("content_filter", "refusal"),
        ],
    )
    def test_openai_table(self, raw: str, expected: str) -> None:
        assert map_stop_reason("openai", raw) == expected

    def test_unknown_value_maps_to_error_without_raising(self) -> None:
        assert map_stop_reason("anthropic", "some_new_reason") == "error"

    def test_unknown_provider_maps_to_error_without_raising(self) -> None:
        assert map_stop_reason("cohere", "stop") == "error"


class TestUsage:
    def test_cache_fields_default_to_zero(self) -> None:
        u = Usage(input_tokens=10, output_tokens=5)
        assert u.input_tokens == 10
        assert u.output_tokens == 5
        assert u.cache_read_tokens == 0
        assert u.cache_write_tokens == 0


class TestMessage:
    def test_defaults_are_empty_collections_and_none(self) -> None:
        m = Message(role="user", content="hi")
        assert m.role == "user"
        assert m.content == "hi"
        assert m.tool_calls == []
        assert m.tool_results == []
        assert m.raw is None

    def test_role_is_constrained_to_the_three_neutral_roles(self) -> None:
        from pydantic import ValidationError

        for role in ("user", "assistant", "tool"):
            assert Message(role=role).role == role
        with pytest.raises(ValidationError):
            Message(role="system")

    def test_raw_passthrough_is_carried_verbatim(self) -> None:
        # Anthropic rejects a reconstructed assistant turn; raw must round-trip.
        raw = {"role": "assistant", "content": [{"type": "tool_use", "id": "x"}]}
        m = Message(role="assistant", content=None, raw=raw)
        assert m.raw == raw


class TestModelResponse:
    def test_carries_parallel_tool_calls_in_order(self) -> None:
        calls = [
            ToolCall(id="call_0", name="a", arguments={}),
            ToolCall(id="call_1", name="b", arguments={}),
        ]
        r = ModelResponse(
            text=None,
            tool_calls=calls,
            stop_reason="tool_use",
            usage=Usage(input_tokens=1, output_tokens=1),
            latency_ms=42,
            raw={"id": "msg_1"},
        )
        assert [c.name for c in r.tool_calls] == ["a", "b"]
        assert r.stop_reason == "tool_use"
        assert r.latency_ms == 42
        assert r.raw == {"id": "msg_1"}


class TestTrace:
    def _trace(self) -> Trace:
        # Turn 0 has two parallel calls; turn 1 one; turn 2 terminates.
        turns = [
            _turn(0, _response("lookup_a", "lookup_b")),
            _turn(1, _response("lookup_c")),
            _turn(2, _response(stop="end_turn", text="done")),
        ]
        return Trace(
            case_name="c",
            suite_name="s",
            turns=turns,
            final_text="done",
            termination="end_turn",
            total_usage=Usage(input_tokens=3, output_tokens=3),
            total_cost_usd=0.0042,
            duration_ms=100,
        )

    def test_tool_names_flatten_in_call_order_across_turns(self) -> None:
        assert self._trace().tool_names() == ["lookup_a", "lookup_b", "lookup_c"]

    def test_tool_calls_flatten_in_call_order_across_turns(self) -> None:
        assert [c.id for c in self._trace().tool_calls()] == [
            "call_lookup_a",
            "call_lookup_b",
            "call_lookup_c",
        ]

    def test_error_defaults_to_none(self) -> None:
        assert self._trace().error is None

    def test_round_trips_through_json_without_loss(self) -> None:
        # Include malformed_arguments and Message.raw on the round-trip path.
        turn = Turn(
            index=0,
            request_messages=[
                Message(role="assistant", content=None, raw={"echo": [1, 2]}),
            ],
            response=ModelResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="call_0",
                        name="issue_refund",
                        arguments={},
                        malformed_arguments='{"amount": 2',
                    )
                ],
                stop_reason="tool_use",
                usage=Usage(input_tokens=1, output_tokens=1),
                latency_ms=1,
                raw={"id": "m"},
            ),
            tool_results=[ToolResult(call_id="call_0", content="boom", is_error=True)],
        )
        original = Trace(
            case_name="c",
            suite_name="s",
            turns=[turn],
            final_text=None,
            termination="unmocked_tool",
            total_usage=Usage(input_tokens=1, output_tokens=1),
            total_cost_usd=None,
            duration_ms=5,
            error="tool not mocked",
        )
        restored = Trace.model_validate_json(original.model_dump_json())
        assert restored == original
        tc = restored.turns[0].response.tool_calls[0]
        assert tc.malformed_arguments == '{"amount": 2'
        assert restored.turns[0].request_messages[0].raw == {"echo": [1, 2]}

    def test_serialised_json_is_strict_allow_nan_false_compatible(self) -> None:
        dumped = self._trace().model_dump_json()
        # Re-encode with allow_nan=False; a non-finite float would raise here.
        json.dumps(json.loads(dumped), allow_nan=False)

    def test_non_finite_cost_is_rejected_at_construction(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Trace(
                case_name="c",
                suite_name="s",
                turns=[],
                final_text=None,
                termination="error",
                total_usage=Usage(input_tokens=0, output_tokens=0),
                total_cost_usd=float("inf"),
                duration_ms=0,
            )

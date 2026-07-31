"""AC-010 — the assertion framework: protocol, result, self-registering registry."""

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from agentcheck.domain.assertions.base import (
    AssertionResult,
    DuplicateKind,
    register,
    safe_evaluate,
)
from agentcheck.domain.assertions.registry import get, known_kinds, validate_args
from agentcheck.domain.model.trace import Trace

pytestmark = pytest.mark.usefixtures("registry_isolation")


def _trace() -> Trace:
    from agentcheck.domain.model.message import Usage

    return Trace(
        case_name="c",
        suite_name="s",
        turns=[],
        final_text="done",
        termination="end_turn",
        total_usage=Usage(input_tokens=0, output_tokens=0),
        total_cost_usd=None,
        duration_ms=0,
    )


class TestRegistration:
    def test_registered_assertion_is_discoverable(self) -> None:
        @register
        class Toy:
            kind: ClassVar[str] = "toy"

            class Args(BaseModel):
                n: int

            def __init__(self, args: Any) -> None:
                self._args = args

            def evaluate(self, trace: Trace) -> AssertionResult:
                return AssertionResult(
                    kind="toy", description="toy", passed=True, message=""
                )

        assert get("toy") is Toy
        assert "toy" in known_kinds()

    def test_duplicate_kind_raises_naming_both_sources(self) -> None:
        @register
        class First:
            kind: ClassVar[str] = "dup"

            class Args(BaseModel):
                pass

            def evaluate(self, trace: Trace) -> AssertionResult:  # pragma: no cover
                return AssertionResult(kind="dup", description="", passed=True, message="")

        with pytest.raises(DuplicateKind) as exc:

            @register
            class Second:
                kind: ClassVar[str] = "dup"

                class Args(BaseModel):
                    pass

                def evaluate(self, trace: Trace) -> AssertionResult:  # pragma: no cover
                    return AssertionResult(kind="dup", description="", passed=True, message="")

        message = str(exc.value)
        assert "First" in message
        assert "Second" in message


class TestValidateArgs:
    def _register_toy(self) -> None:
        @register
        class Toy:
            kind: ClassVar[str] = "toy"

            class Args(BaseModel):
                n: int

            def evaluate(self, trace: Trace) -> AssertionResult:  # pragma: no cover
                return AssertionResult(kind="toy", description="", passed=True, message="")

    def test_valid_args_pass(self) -> None:
        self._register_toy()
        validated = validate_args("toy", {"n": 5})
        assert validated is not None

    def test_malformed_args_raise_validation_error(self) -> None:
        from pydantic import ValidationError

        self._register_toy()
        with pytest.raises(ValidationError):
            validate_args("toy", {"n": "not-an-int"})

    def test_unregistered_kind_validates_to_none(self) -> None:
        # A seeded-but-unregistered kind (real assertion arrives in AC-011) has
        # no args model yet, so there is nothing to validate.
        assert validate_args("calls_tool", "anything") is None


class TestKnownKinds:
    def test_seeds_the_six_v01_kinds(self) -> None:
        kinds = known_kinds()
        for kind in (
            "calls_tool",
            "not_calls_tool",
            "tool_args",
            "call_order",
            "max_turns",
            "final_contains",
        ):
            assert kind in kinds


class TestSafeEvaluate:
    def test_raising_assertion_becomes_passed_false_internal_error(self) -> None:
        class Boom:
            kind: ClassVar[str] = "boom"

            def evaluate(self, trace: Trace) -> AssertionResult:
                raise RuntimeError("kaboom")

        result = safe_evaluate(Boom(), _trace())
        assert result.passed is False
        assert "internal error" in result.message.lower()
        assert result.kind == "boom"

    def test_normal_assertion_result_passes_through(self) -> None:
        class Ok:
            kind: ClassVar[str] = "ok"

            def evaluate(self, trace: Trace) -> AssertionResult:
                return AssertionResult(kind="ok", description="ok", passed=True, message="")

        result = safe_evaluate(Ok(), _trace())
        assert result.passed is True

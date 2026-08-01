"""AC-010 — the assertion framework: protocol, result, self-registering registry."""

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from dryfire.domain.assertions.base import (
    AssertionResult,
    DuplicateKind,
    register,
    safe_evaluate,
)
from dryfire.domain.assertions.registry import build, get, known_kinds, validate_args
from dryfire.domain.model.trace import Trace

pytestmark = pytest.mark.usefixtures("registry_isolation")


def _trace() -> Trace:
    from dryfire.domain.model.message import Usage

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
        # An entirely unregistered kind has no args model, so there is nothing to
        # validate. (The six v0.1 kinds are registered by AC-011's structural.py.)
        assert validate_args("definitely_not_a_registered_kind", "anything") is None


class TestBuild:
    def test_build_validates_and_constructs(self) -> None:
        @register
        class Toy:
            kind: ClassVar[str] = "toy"

            class Args(BaseModel):
                n: int

            def __init__(self, args: Any) -> None:
                self.n = args.n

            def evaluate(self, trace: Trace) -> AssertionResult:  # pragma: no cover
                return AssertionResult(kind="toy", description="", passed=True, message="")

        built = build("toy", {"n": 7})
        assert isinstance(built, Toy)
        assert built.n == 7

    def test_build_unknown_kind_raises(self) -> None:
        with pytest.raises(KeyError):
            build("not_registered", {})


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

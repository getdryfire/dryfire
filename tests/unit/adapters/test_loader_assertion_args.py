"""AC-010 — malformed assertion args caught by the loader via validate_args (end
to end). Uses a toy assertion since the real six arrive in AC-011."""

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from dryfire.adapters.driven.spec.loader import load_suite
from dryfire.domain.assertions.base import AssertionResult, register
from dryfire.domain.model.trace import Trace

pytestmark = pytest.mark.usefixtures("registry_isolation")


def _register_toy() -> None:
    @register
    class Toy:
        kind: ClassVar[str] = "toy_assert"

        class Args(BaseModel):
            n: int

        def __init__(self, args: Any) -> None:
            self._args = args

        def evaluate(self, trace: Trace) -> AssertionResult:  # pragma: no cover
            return AssertionResult(kind="toy_assert", description="", passed=True, message="")


def _write(tmp_path: Path, expect_line: str) -> Path:
    src = (
        "name: s\ncases:\n  - name: c\n    input: hi\n    expect:\n      - " + expect_line + "\n"
    )
    p = tmp_path / "s.eval.yaml"
    p.write_text(src, encoding="utf-8")
    return p


def test_malformed_assertion_args_surface_as_spec_error(tmp_path: Path) -> None:
    _register_toy()
    suite, errors = load_suite(_write(tmp_path, "toy_assert: {n: not_an_int}"))
    assert suite is None
    assert len(errors) == 1
    # Must be an argument-validation error, not an "unknown kind" error.
    assert "argument" in errors[0].message.lower()
    assert "toy_assert" in errors[0].message
    assert errors[0].position is not None


def test_valid_assertion_args_produce_no_error(tmp_path: Path) -> None:
    _register_toy()
    suite, errors = load_suite(_write(tmp_path, "toy_assert: {n: 5}"))
    assert errors == []
    assert suite is not None


def test_registered_kind_is_accepted_by_the_loader(tmp_path: Path) -> None:
    # A registered kind the six seeds don't include is still a known kind.
    _register_toy()
    suite, errors = load_suite(_write(tmp_path, "toy_assert: {n: 1}"))
    assert errors == []
    assert suite is not None

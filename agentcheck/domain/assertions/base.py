"""Assertion framework: protocol, result, and the self-registering registry
backing (SPEC §6, §6.3).

Adding an assertion is one new file plus one registry import — no changes to the
loop, loader, or reporters (EPIC-001 success criterion 7). Assertions read the
whole `Trace` (the product thesis), are pure, and never raise: an internal
failure becomes `AssertionResult(passed=False)` via `safe_evaluate`.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from agentcheck.domain.model.trace import Trace


class AssertionResult(BaseModel):
    """The outcome of one assertion (SPEC §6). `description` is the rendered
    human form (e.g. ``not_calls_tool: issue_refund``) that reporters print."""

    model_config = ConfigDict(frozen=True)

    kind: str
    description: str
    passed: bool
    message: str  # failure explanation; empty when passed
    expected: Any | None = None
    actual: Any | None = None


@runtime_checkable
class Assertion(Protocol):
    """An assertion evaluates the entire Trace (the product thesis).

    Concrete assertions also declare a class-level pydantic ``Args`` model — a
    registration convention (validated by `registry.validate_args`) rather than
    part of the runtime interface, so it stays out of this protocol."""

    kind: ClassVar[str]

    def evaluate(self, trace: Trace) -> AssertionResult: ...


class DuplicateKind(RuntimeError):
    """Raised at import time when two assertions claim the same kind."""


# kind -> Assertion class. Owned here (register populates it); registry.py reads it.
_REGISTRY: dict[str, type[Assertion]] = {}


def register(cls: type[Assertion]) -> type[Assertion]:
    """Register an assertion class under its `kind`. Duplicate kinds raise,
    naming both sources."""
    kind = cls.kind
    existing = _REGISTRY.get(kind)
    if existing is not None:
        raise DuplicateKind(
            f"assertion kind {kind!r} already registered by "
            f"{existing.__module__}.{existing.__qualname__}; "
            f"{cls.__module__}.{cls.__qualname__} cannot re-register it"
        )
    _REGISTRY[kind] = cls
    return cls


def safe_evaluate(assertion: Assertion, trace: Trace) -> AssertionResult:
    """Evaluate an assertion, guaranteeing no exception escapes. A bug in one
    assertion becomes a failed result, never an aborted run."""
    try:
        return assertion.evaluate(trace)
    except Exception as exc:  # noqa: BLE001 - a broken assertion must not abort a run
        kind = getattr(assertion, "kind", "unknown")
        return AssertionResult(
            kind=kind,
            description=kind,
            passed=False,
            message=f"internal error evaluating assertion: {exc!r}",
        )

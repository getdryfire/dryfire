"""Assertion registry queries (SPEC §6.3).

The backing for known-kind validation (replacing AC-004's inline stub) and the
uniform constructor for assertions. The six v0.1 assertions self-register via the
`structural` import at the bottom, so `known_kinds()` is purely registration-driven
and a hypothetical seventh appears automatically once registered (EPIC-001
success criterion 7).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from dryfire.domain.assertions.base import _REGISTRY, Assertion


def known_kinds() -> frozenset[str]:
    """Every kind the spec loader accepts — purely the registered assertions. The
    six v0.1 kinds register via the `structural` import below, and a seventh
    appears here automatically once registered (SPEC §6.3)."""
    return frozenset(_REGISTRY)


def get(kind: str) -> type[Assertion] | None:
    """The registered Assertion class for a kind, or None if not yet registered."""
    return _REGISTRY.get(kind)


def validate_args(kind: str, raw: Any) -> BaseModel | None:
    """Validate raw assertion arguments against the assertion's Args model.
    Raises pydantic ValidationError on malformed args. Returns None when the kind
    is known but has no registered assertion (or no Args) yet — nothing to validate."""
    cls = _REGISTRY.get(kind)
    if cls is None:
        return None
    args_model: type[BaseModel] | None = getattr(cls, "Args", None)
    if args_model is None:
        return None
    return args_model.model_validate(raw)


def build(kind: str, raw: Any) -> Assertion:
    """Validate raw args and construct the assertion instance. The uniform
    constructor the loop (AC-009) uses to turn an `expect` entry into an
    assertion. Raises KeyError for an unregistered kind, ValidationError for bad
    args."""
    cls = _REGISTRY.get(kind)
    if cls is None:
        raise KeyError(f"no assertion registered for kind {kind!r}")
    args_model: type[BaseModel] | None = getattr(cls, "Args", None)
    args = args_model.model_validate(raw) if args_model is not None else None
    constructor: Any = cls
    return constructor(args)  # type: ignore[no-any-return]


# Import the concrete assertions for their registration side effects, so the six
# v0.1 kinds are always available. Adding a new assertion is a new file plus one
# import line here — no changes to the loop, loader, or reporters (SPEC §6.3).
from dryfire.domain.assertions import budget, structural  # noqa: E402, F401

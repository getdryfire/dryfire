"""Assertion registry queries (SPEC §6.3).

Replaces AC-004's inline stub as the backing for known-kind validation. Seeds the
six v0.1 kind *names* so the spec loader recognises them for validation; the real
`Assertion` classes are registered by AC-011 via `@register`. `known_kinds()` is
the union, so a hypothetical seventh assertion appears automatically once
registered (EPIC-001 success criterion 7).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agentcheck.domain.assertions.base import _REGISTRY, Assertion

# The v0.1 kind names. Seeded for spec-time validation before AC-011 registers
# concrete assertions; AC-011 may drop this once all six are registered.
_V01_KINDS = frozenset(
    {"calls_tool", "not_calls_tool", "tool_args", "call_order", "max_turns", "final_contains"}
)


def known_kinds() -> frozenset[str]:
    """Every kind the spec loader accepts: seeded v0.1 names plus registrations."""
    return _V01_KINDS | frozenset(_REGISTRY)


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

"""Spec→FakeGateway script mapping (AC-016).

A `provider: fake` case scripts the model's turns in YAML (`ScriptStep`, in
`models.py`). The FakeGateway (`adapters/driven/providers/fake.py`) consumes its
own `ScriptEntry` values built by `text` / `tool_call` / `parallel` / `fails`.
This translates one into the other so composition can build a fresh scripted
gateway per case straight from the spec.

Which kind a step carries is decided by `model_fields_set` (like the spec's own
validator), never by `is not None` — an explicit `text: ""` is a real text turn.
"""

from __future__ import annotations

from dryfire.adapters.driven.providers.fake import (
    FakeProviderError,
    ScriptEntry,
    fails,
    parallel,
    text,
    tool_call,
)
from dryfire.adapters.driven.spec.models import ScriptStep


def map_step(step: ScriptStep) -> ScriptEntry:
    """One spec step → one FakeGateway entry."""
    fields = step.model_fields_set
    if "text" in fields:
        return text(step.text or "")
    if "tool_call" in fields and step.tool_call is not None:
        return tool_call(step.tool_call.name, dict(step.tool_call.arguments))
    if "parallel" in fields and step.parallel is not None:
        return parallel(*(tool_call(c.name, dict(c.arguments)) for c in step.parallel))
    return fails(FakeProviderError(step.fails or "simulated provider failure"))


def map_script(steps: list[ScriptStep]) -> list[ScriptEntry]:
    """A whole `script` list, spec → FakeGateway entries."""
    return [map_step(s) for s in steps]

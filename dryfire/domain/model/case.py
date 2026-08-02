"""ResolvedCase — one fully-resolved, runnable case (SPEC §4.2 resolution).

Produced by config resolution (AC-005) from built-in defaults, project config,
suite, case, and CLI overrides. Every setting is resolved to a concrete value;
`system` may legitimately be None (no system prompt), but the settings that carry
built-in defaults never are. Pure domain value — carries no spec-layer types.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from dryfire.domain.model.tooling import ToolDef


class ResolvedCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Identity — reporters and cassette paths both need these (AC-005).
    suite_name: str
    case_name: str
    suite_path: Path

    # Resolved settings.
    provider: str
    model: str
    max_turns: int
    temperature: float
    on_unmocked: Literal["error", "null", "passthrough"]

    # Repetition (DF-305): run the case `repeat` times and report a k/N pass rate;
    # `require_pass_rate` is the fraction that must pass for the case to pass the build.
    # Defaults keep a non-repeated case byte-identical to v0.2 (repeat 1, rate 1.0).
    repeat: int = 1
    require_pass_rate: float = 1.0

    # Case content the runner executes.
    system: str | None
    input: str | list[dict[str, Any]]
    expect: list[dict[str, Any]]
    tools: list[ToolDef] = []

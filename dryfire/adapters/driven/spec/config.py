"""Configuration resolution and discovery (SPEC §4.2).

Settings arrive from five places; precedence is exactly:

    CLI override > case > suite > project `defaults:` > built-in

`resolve()` is pure — inputs in, `ResolvedCase` out, no I/O. Discovery and
globbing (which do touch the filesystem) live alongside it but are separate.

Built-in defaults follow SPEC §4.2. The ticket enumerates the numeric/enum ones
(max_turns/temperature/on_unmocked/concurrency); `provider` and `model` also need
built-ins so a bare suite is runnable with no None left — SPEC §4.2 supplies the
canonical values.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dryfire.adapters.driven.spec.models import Case, Defaults, ProjectConfig, Suite
from dryfire.adapters.driven.spec.positions import load_positioned
from dryfire.domain.model.case import ResolvedCase
from dryfire.domain.model.tooling import ToolDef

CONFIG_FILENAME = "dryfire.yaml"

BUILTIN_PROVIDER = "anthropic"
BUILTIN_MODEL = "claude-sonnet-4-6"
BUILTIN_MAX_TURNS = 10
BUILTIN_TEMPERATURE = 0.0
BUILTIN_ON_UNMOCKED = "error"
BUILTIN_CONCURRENCY = 4  # run-level; consumed by the scheduler (AC-012), not per-case
BUILTIN_REPEAT = 1  # DF-305: no repetition by default → byte-identical to v0.2
BUILTIN_REQUIRE_PASS_RATE = 1.0  # all N must pass unless the spec relaxes it


def _pick(
    overrides: Mapping[str, Any],
    key: str,
    suite_val: Any,
    case_val: Any,
    project_defaults: Defaults | None,
    builtin: Any,
) -> Any:
    """override > case > suite > project > built-in. First non-None wins."""
    if overrides.get(key) is not None:
        return overrides[key]
    if case_val is not None:
        return case_val
    if suite_val is not None:
        return suite_val
    if project_defaults is not None:
        project_val = getattr(project_defaults, key, None)
        if project_val is not None:
            return project_val
    return builtin


def resolve(
    *,
    suite: Suite,
    case: Case,
    suite_path: Path,
    project_defaults: Defaults | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ResolvedCase:
    """Resolve one case's settings against the full precedence chain."""
    ov = overrides or {}
    return ResolvedCase(
        suite_name=suite.name,
        case_name=case.name,
        suite_path=suite_path,
        provider=_pick(ov, "provider", suite.provider, None, project_defaults, BUILTIN_PROVIDER),
        model=_pick(ov, "model", suite.model, case.model, project_defaults, BUILTIN_MODEL),
        max_turns=_pick(
            ov, "max_turns", suite.max_turns, case.max_turns, project_defaults, BUILTIN_MAX_TURNS
        ),
        temperature=_pick(
            ov,
            "temperature",
            suite.temperature,
            case.temperature,
            project_defaults,
            BUILTIN_TEMPERATURE,
        ),
        on_unmocked=_pick(
            ov,
            "on_unmocked",
            suite.on_unmocked,
            case.on_unmocked,
            project_defaults,
            BUILTIN_ON_UNMOCKED,
        ),
        repeat=_pick(ov, "repeat", suite.repeat, case.repeat, project_defaults, BUILTIN_REPEAT),
        require_pass_rate=_pick(
            ov, "require_pass_rate", suite.require_pass_rate, case.require_pass_rate,
            project_defaults, BUILTIN_REQUIRE_PASS_RATE,
        ),
        system=suite.system,
        input=case.input,
        expect=case.expect,
        tools=[
            ToolDef(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in suite.tools
        ],
    )


def discover_config(start: Path) -> Path | None:
    """Walk upward from `start` to the filesystem root looking for
    `dryfire.yaml`. Returns None if none is found — a bare suite with no
    project config is runnable, not an error."""
    here = Path(start).resolve()
    for parent in (here, *here.parents):
        candidate = parent / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_project_config(path: Path) -> ProjectConfig:
    """Load and validate an `dryfire.yaml`."""
    return ProjectConfig.model_validate(load_positioned(path))


def glob_suites(config_path: Path, patterns: list[str]) -> list[Path]:
    """Resolve suite glob patterns relative to the config file's directory."""
    base = config_path.parent
    found: list[Path] = []
    for pattern in patterns:
        found.extend(sorted(base.glob(pattern)))
    return found

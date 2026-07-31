"""SPIKE-003 — one-pass spec validation with positioned, human-readable errors.

Usage:  python render.py sample_broken.eval.yaml
Exit:   0 = valid, 2 = spec errors (matches SPEC.md §7.1)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from locate import (
    SpecError,
    check_assertion_kinds,
    load_positioned,
    locate,
    resolve_refs,
)

# --------------------------------------------------------------------------
# Minimal stand-ins for the real SPEC §4 models
# --------------------------------------------------------------------------


class ToolDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str | None = None
    input_schema: dict


class MockRule(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    when: dict | None = None
    returns: Any = Field(default=None, alias="return")
    error: str | None = None
    sequence: list[dict] | None = None


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    input: str | list[dict]
    expect: list[dict]
    mocks: dict[str, list[MockRule]] | None = None


class Suite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str | None = None
    tags: list[str] = []
    model: str | None = None
    max_turns: int | None = None
    temperature: float | None = None
    system: str | None = None
    tools: list[ToolDef] = []
    mocks: dict[str, list[MockRule]] = {}
    cases: list[Case]


# --------------------------------------------------------------------------
# Validation pipeline: refs -> registry -> pydantic, all collected in one pass
# --------------------------------------------------------------------------

_PYDANTIC_MESSAGES = {
    "missing": "required field is missing",
    "extra_forbidden": "unknown field",
    "int_parsing": "expected an integer",
    "float_parsing": "expected a number",
    "string_type": "expected a string",
    "list_type": "expected a list",
    "dict_type": "expected a mapping",
}


def validate_file(path: Path) -> list[SpecError]:
    errors: list[SpecError] = []
    root = load_positioned(path)

    # Pre-pass 1: $ref resolution (mutates a copy, records missing targets)
    root = resolve_refs(root, path.parent, path, errors)

    # Pre-pass 2: assertion registry lookup
    check_assertion_kinds(root, path, errors)

    # A node whose $ref failed was replaced by a placeholder. Any pydantic
    # error underneath it is a cascade artefact, not a user mistake -- suppress.
    poisoned = {e.loc[:-1] for e in errors if e.loc and e.loc[-1] == "$ref"}

    # Main pass: pydantic
    try:
        Suite.model_validate(root)
    except ValidationError as exc:
        for err in exc.errors():
            loc = err["loc"]
            if any(tuple(loc)[: len(p)] == p for p in poisoned):
                continue
            kind = err["type"]
            msg = _PYDANTIC_MESSAGES.get(kind, err["msg"])
            if kind == "extra_forbidden" and loc:
                msg = f"unknown field {loc[-1]!r}"
            if kind == "missing" and loc:
                msg = f"required field {loc[-1]!r} is missing"
            errors.append(
                SpecError(
                    path=path,
                    loc=tuple(loc),
                    message=msg,
                    position=locate(root, loc),
                )
            )

    errors.sort(key=lambda e: (e.position.line if e.position else 0,
                               e.position.col if e.position else 0))
    return errors


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render(errors: list[SpecError], source_lines: list[str]) -> str:
    out: list[str] = []
    for err in errors:
        pos = err.position
        where = f"{err.path}:{pos.line}:{pos.col}" if pos else str(err.path)
        out.append(f"error: {err.message}")
        out.append(f"  --> {where}   ({err.loc_str})")
        if pos:
            gutter = str(pos.line)
            pad = " " * len(gutter)
            src = source_lines[pos.line - 1].rstrip("\n")
            out.append(f"   {pad} |")
            out.append(f"   {gutter} | {src}")
            caret = " " * (pos.col - 1) + "^"
            note = "" if pos.exact else "  (nearest enclosing node)"
            out.append(f"   {pad} | {caret}{note}")
        if err.hint:
            out.append(f"   = help: {err.hint}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: render.py <suite.eval.yaml>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    source_lines = path.read_text(encoding="utf-8").splitlines()
    errors = validate_file(path)
    if not errors:
        print(f"{path}: ok")
        return 0
    print(render(errors, source_lines), end="")
    print(f"{len(errors)} error(s) in {path}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

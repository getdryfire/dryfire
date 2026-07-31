"""Spec errors and their rendered form (SPIKE-003 output contract).

`render()`'s caret format is the product's highest-leverage UX (SPEC §1.6): a
user hand-edits YAML, gets it wrong, and this output determines whether they stay.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentcheck.adapters.driven.spec.positions import Position

# pydantic error-code -> plain-language message. Anything unmapped falls back to
# pydantic's own `msg`.
PYDANTIC_MESSAGES = {
    "missing": "required field is missing",
    "extra_forbidden": "unknown field",
    "int_parsing": "expected an integer",
    "int_type": "expected an integer",
    "float_parsing": "expected a number",
    "string_type": "expected a string",
    "list_type": "expected a list",
    "dict_type": "expected a mapping",
}


@dataclass
class SpecError:
    path: Path
    loc: tuple[Any, ...]
    message: str
    position: Position | None
    hint: str | None = None

    @property
    def loc_str(self) -> str:
        out = ""
        for seg in self.loc:
            if isinstance(seg, int):
                out += f"[{seg}]"
            else:
                out += f".{seg}" if out else str(seg)
        return out or "<root>"


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

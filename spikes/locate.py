"""SPIKE-003 — map pydantic v2 ValidationError paths back to YAML line/col.

Reference implementation. AC-004 adapts `locate()` and `SpecError`.

Key mechanic: ruamel.yaml in round-trip mode returns CommentedMap / CommentedSeq
nodes that carry `.lc` position data:
    CommentedMap.lc.key(k)   -> (line, col) of the KEY token
    CommentedMap.lc.value(k) -> (line, col) of the VALUE token
    CommentedSeq.lc.item(i)  -> (line, col) of the item
All are 0-based; we render 1-based.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

_yaml = YAML(typ="rt")


# --------------------------------------------------------------------------
# Position model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    line: int  # 1-based
    col: int  # 1-based
    exact: bool  # False when we fell back to an ancestor node

    @classmethod
    def from_lc(cls, pair: tuple[int, int] | None, exact: bool = True) -> "Position | None":
        if pair is None:
            return None
        return cls(line=pair[0] + 1, col=pair[1] + 1, exact=exact)


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


# --------------------------------------------------------------------------
# Core: walk a pydantic loc tuple through the ruamel node tree
# --------------------------------------------------------------------------


def load_positioned(path: Path) -> Any:
    """Load YAML preserving position data."""
    with path.open("r", encoding="utf-8") as fh:
        return _yaml.load(fh)


def locate(root: Any, loc: Iterable[Any]) -> Position | None:
    """Resolve a pydantic error `loc` tuple to a source position.

    Walks as deep as the document allows. If a segment cannot be resolved --
    a missing required key, or a pydantic-internal segment such as a union
    tag -- we stop and return the deepest ANCESTOR position with exact=False.
    That is the correct behaviour for `missing` errors: the user needs to be
    pointed at the container that lacks the field.
    """
    node = root
    best: Position | None = Position.from_lc(_node_pos(root), exact=True)

    for seg in loc:
        if isinstance(node, CommentedMap) and seg in node:
            pos = Position.from_lc(node.lc.key(seg), exact=True)
            if pos:
                best = pos
            node = node[seg]
            continue

        if isinstance(node, CommentedSeq) and isinstance(seg, int) and 0 <= seg < len(node):
            pos = Position.from_lc(node.lc.item(seg), exact=True)
            if pos:
                best = pos
            node = node[seg]
            continue

        # Unresolvable segment: missing key, union tag, or scalar leaf.
        # Degrade to the deepest ancestor we did resolve.
        if best:
            best = Position(best.line, best.col, exact=False)
        break

    return best


def _node_pos(node: Any) -> tuple[int, int] | None:
    lc = getattr(node, "lc", None)
    if lc is None or lc.line is None:
        return None
    return (lc.line, lc.col)


# --------------------------------------------------------------------------
# Pre-pass: $ref resolution (runs BEFORE pydantic; collects its own errors)
# --------------------------------------------------------------------------


def resolve_refs(node: Any, base_dir: Path, path: Path, errors: list[SpecError],
                 _loc: tuple[Any, ...] = ()) -> Any:
    """Replace {'$ref': p} nodes with the loaded target.

    On a missing target, record a SpecError and substitute an empty mapping so
    that validation can CONTINUE and report every other problem in one pass.
    """
    if isinstance(node, CommentedMap):
        if "$ref" in node:
            target = base_dir / str(node["$ref"])
            if not target.exists():
                errors.append(
                    SpecError(
                        path=path,
                        loc=_loc + ("$ref",),
                        message=f"$ref target not found: {node['$ref']}",
                        position=Position.from_lc(node.lc.key("$ref")),
                        hint=_suggest_file(target),
                    )
                )
                return CommentedMap()
            with target.open("r", encoding="utf-8") as fh:
                return _yaml.load(fh)
        for key in list(node.keys()):
            node[key] = resolve_refs(node[key], base_dir, path, errors, _loc + (key,))
        return node

    if isinstance(node, CommentedSeq):
        for i in range(len(node)):
            node[i] = resolve_refs(node[i], base_dir, path, errors, _loc + (i,))
        return node

    return node


def _suggest_file(missing: Path) -> str | None:
    if not missing.parent.exists():
        return None
    names = [p.name for p in missing.parent.iterdir() if p.is_file()]
    close = difflib.get_close_matches(missing.name, names, n=1, cutoff=0.5)
    return f"did you mean ./{missing.parent.name}/{close[0]}?" if close else None


# --------------------------------------------------------------------------
# Registry-driven assertion-kind checking (also a pre-pass)
# --------------------------------------------------------------------------

KNOWN_ASSERTIONS = {
    "calls_tool",
    "not_calls_tool",
    "tool_args",
    "call_order",
    "max_turns",
    "final_contains",
}


def check_assertion_kinds(root: Any, path: Path, errors: list[SpecError]) -> None:
    cases = root.get("cases") if isinstance(root, CommentedMap) else None
    if not isinstance(cases, CommentedSeq):
        return
    for ci, case in enumerate(cases):
        if not isinstance(case, CommentedMap):
            continue
        expect = case.get("expect")
        if not isinstance(expect, CommentedSeq):
            continue
        for ei, entry in enumerate(expect):
            if not isinstance(entry, CommentedMap) or len(entry) != 1:
                continue
            kind = next(iter(entry.keys()))
            if kind in KNOWN_ASSERTIONS:
                continue
            close = difflib.get_close_matches(kind, sorted(KNOWN_ASSERTIONS), n=1, cutoff=0.4)
            errors.append(
                SpecError(
                    path=path,
                    loc=("cases", ci, "expect", ei, kind),
                    message=f"unknown assertion kind: {kind!r}",
                    position=Position.from_lc(entry.lc.key(kind)),
                    hint=f"did you mean {close[0]!r}?" if close else
                         f"valid kinds: {', '.join(sorted(KNOWN_ASSERTIONS))}",
                )
            )

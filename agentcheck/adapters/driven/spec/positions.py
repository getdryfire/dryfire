"""Map a pydantic error `loc` tuple back to a YAML line/col (SPIKE-003).

Schema-agnostic. `ruamel.yaml` round-trip mode returns CommentedMap/CommentedSeq
nodes carrying `.lc` position data:
    CommentedMap.lc.key(k)   -> (line, col) of the KEY token
    CommentedMap.lc.value(k) -> (line, col) of the VALUE token
    CommentedSeq.lc.item(i)  -> (line, col) of the item
All are 0-based; we render 1-based.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

_yaml = YAML(typ="rt")


@dataclass(frozen=True)
class Position:
    line: int  # 1-based
    col: int  # 1-based
    exact: bool  # False when we fell back to an ancestor node

    @classmethod
    def from_lc(cls, pair: tuple[int, int] | None, exact: bool = True) -> Position | None:
        if pair is None:
            return None
        return cls(line=pair[0] + 1, col=pair[1] + 1, exact=exact)


def load_positioned(path: Path) -> Any:
    """Load YAML preserving position data."""
    with path.open("r", encoding="utf-8") as fh:
        return _yaml.load(fh)


def _node_pos(node: Any) -> tuple[int, int] | None:
    lc = getattr(node, "lc", None)
    if lc is None or lc.line is None:
        return None
    line: int = lc.line
    col: int = lc.col
    return (line, col)


def locate(root: Any, loc: Iterable[Any]) -> Position | None:
    """Resolve a pydantic error `loc` tuple to a source position.

    Walks as deep as the document allows. If a segment cannot be resolved — a
    missing required key, or a pydantic-internal segment such as a union tag — we
    stop and return the deepest ANCESTOR position with exact=False. That is the
    correct behaviour for `missing` errors: point the user at the container that
    lacks the field.
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

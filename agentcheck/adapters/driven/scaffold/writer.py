"""Scaffold writer (AC-016): copy the bundled template tree into a target dir.

`agentcheck init` lays down a runnable project — `agentcheck.yaml`, the two
example suites, a shared schema, and a README — by copying
`agentcheck/scaffold/template/**` verbatim. The template ships in the wheel
(package data), so it is read through `importlib.resources`, not a hard-coded
path, and works whether installed from source or a wheel.

Refuses to clobber existing files unless `force=True`, and detects every
conflict *before* writing anything so a refusal never leaves a half-written
project.
"""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath


class ScaffoldConflict(Exception):
    """`init` would overwrite existing files and `force` was not given. Carries
    the conflicting paths (relative to the target dir) so the CLI can list them."""

    def __init__(self, conflicts: list[Path]) -> None:
        joined = ", ".join(str(c) for c in conflicts)
        super().__init__(f"refusing to overwrite existing files: {joined}")
        self.conflicts = conflicts


def _template_root() -> Traversable:
    return files("agentcheck").joinpath("scaffold/template")


def _walk(node: Traversable, prefix: PurePosixPath) -> list[tuple[PurePosixPath, Traversable]]:
    """Every file under `node`, paired with its path relative to the template root."""
    found: list[tuple[PurePosixPath, Traversable]] = []
    for child in node.iterdir():
        rel = prefix / child.name
        if child.is_dir():
            found.extend(_walk(child, rel))
        else:
            found.append((rel, child))
    return found


def scaffold(dst: Path, *, force: bool = False) -> list[Path]:
    """Copy the template tree into `dst`. Returns the written paths (relative to
    `dst`, sorted). Raises `ScaffoldConflict` if any target exists and not `force`."""
    entries = _walk(_template_root(), PurePosixPath())
    plan = sorted((Path(*rel.parts), node) for rel, node in entries)

    if not force:
        conflicts = [rel for rel, _ in plan if (dst / rel).exists()]
        if conflicts:
            raise ScaffoldConflict(conflicts)

    written: list[Path] = []
    for rel, node in plan:
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(node.read_bytes())
        written.append(rel)
    return written

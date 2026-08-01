"""Cassette pruning: find orphaned or stale cassettes and clean empty dirs (DF-205).

Cassette paths embed sanitised suite and case names (`file_store.py`), so renaming
or deleting either orphans the cassettes. This scans the store against the set of
suites/cases that currently exist and classifies each cassette.

**Safety rule:** a cassette whose suite could not be parsed is never a candidate.
When any suite fails to load we cannot know its name (parsing is what yields it),
so any cassette dir that doesn't match a *successfully parsed* suite is protected —
a broken spec must not cause data loss.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dryfire.domain.fingerprint import SCHEMA_VERSION


@dataclass(frozen=True)
class PruneCandidate:
    path: Path
    reason: str


def _schema_version(path: Path) -> int | None:
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["schema_version"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _classify(
    suite_dir: str,
    case_dir: str,
    path: Path,
    valid: dict[str, set[str]],
    *,
    had_parse_failure: bool,
) -> str | None:
    if suite_dir in valid:
        if case_dir not in valid[suite_dir]:
            return "orphaned case"
        if _schema_version(path) != SCHEMA_VERSION:
            return "stale schema_version"
        return None  # a live cassette — keep it
    # The suite dir matches no successfully-parsed suite.
    if had_parse_failure:
        return None  # protect: it might belong to a suite that failed to parse
    return "orphaned suite"


def find_prunable(
    root: Path, valid: dict[str, set[str]], *, had_parse_failure: bool
) -> list[PruneCandidate]:
    """Cassettes under `root` that are orphaned or stale, given the sanitised
    `valid` map (suite dir → case dirs) of suites that currently parse."""
    if not root.exists():
        return []
    found: list[PruneCandidate] = []
    for path in sorted(root.rglob("*.json")):
        parts = path.relative_to(root).parts
        if len(parts) != 3:  # expect <suite>/<case>/<NN-fingerprint>.json
            continue
        suite_dir, case_dir, _ = parts
        reason = _classify(suite_dir, case_dir, path, valid, had_parse_failure=had_parse_failure)
        if reason is not None:
            found.append(PruneCandidate(path, reason))
    return found


def remove_empty_dirs(root: Path) -> None:
    """Remove now-empty case/suite directories, deepest first."""
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()

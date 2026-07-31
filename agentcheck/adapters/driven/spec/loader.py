"""The three-stage spec load pipeline (SPEC §4.1).

    load_positioned            ruamel round-trip -> positioned node tree
          v
    PRE-PASS 1   $ref resolution + env interpolation (records its own errors)
          v
    PRE-PASS 2   assertion-kind registry check + did-you-mean
          v
    MAIN PASS    pydantic structural validation (AC-003 Suite)
          v
    collect + sort every error by source position

Pre-passes run before pydantic because `extra="forbid"` would otherwise reject a
raw `$ref` key and mask the real error. All errors from all stages are collected
in one pass; cascade suppression keeps one user mistake to one error.
"""

from __future__ import annotations

import difflib
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from agentcheck.adapters.driven.spec.errors import PYDANTIC_MESSAGES, SpecError
from agentcheck.adapters.driven.spec.models import Suite
from agentcheck.adapters.driven.spec.positions import Position, load_positioned, locate
from agentcheck.domain.assertions.registry import known_kinds, validate_args

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# -- Pre-pass 1a: $ref resolution -------------------------------------------


def resolve_refs(
    node: Any, base_dir: Path, path: Path, errors: list[SpecError], _loc: tuple[Any, ...] = ()
) -> Any:
    """Replace ``{'$ref': p}`` nodes with the loaded target.

    Paths resolve relative to the containing suite file, not the CWD. On a
    missing target, record one error and substitute an empty mapping so the rest
    of the file can still be validated in this pass.
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
            return load_positioned(target)
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


# -- Pre-pass 1b: env interpolation -----------------------------------------


def interpolate_env(
    node: Any, path: Path, errors: list[SpecError], _loc: tuple[Any, ...] = ()
) -> None:
    """Replace ``${VAR}`` in every string value. A missing variable is a
    positioned spec error, never a silent empty string."""
    if isinstance(node, CommentedMap):
        for key in list(node.keys()):
            val = node[key]
            if isinstance(val, str):
                node[key] = _interp(val, node.lc.value(key), path, errors, _loc + (key,))
            else:
                interpolate_env(val, path, errors, _loc + (key,))
    elif isinstance(node, CommentedSeq):
        for i in range(len(node)):
            val = node[i]
            if isinstance(val, str):
                node[i] = _interp(val, node.lc.item(i), path, errors, _loc + (i,))
            else:
                interpolate_env(val, path, errors, _loc + (i,))


def _interp(
    value: str,
    lc_pos: tuple[int, int] | None,
    path: Path,
    errors: list[SpecError],
    loc: tuple[Any, ...],
) -> str:
    def repl(match: re.Match[str]) -> str:
        var = match.group(1)
        env = os.environ.get(var)
        if env is not None:
            return env
        errors.append(
            SpecError(
                path=path,
                loc=loc,
                message=f"environment variable ${{{var}}} is not set",
                position=Position.from_lc(lc_pos),
            )
        )
        return ""

    return _ENV_RE.sub(repl, value)


# -- Pre-pass 2: assertion-kind registry check ------------------------------


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
        known = known_kinds()
        for ei, entry in enumerate(expect):
            if not isinstance(entry, CommentedMap) or len(entry) != 1:
                continue
            kind = next(iter(entry.keys()))
            loc = ("cases", ci, "expect", ei, kind)
            if kind not in known:
                close = difflib.get_close_matches(kind, sorted(known), n=1, cutoff=0.4)
                errors.append(
                    SpecError(
                        path=path,
                        loc=loc,
                        message=f"unknown assertion kind: {kind!r}",
                        position=Position.from_lc(entry.lc.key(kind)),
                        hint=(
                            f"did you mean {close[0]!r}?"
                            if close
                            else f"valid kinds: {', '.join(sorted(known))}"
                        ),
                    )
                )
                continue
            # Known kind: if a real assertion is registered, validate its args so
            # malformed arguments are a spec error, not a runtime failure (AC-010).
            try:
                validate_args(kind, entry[kind])
            except ValidationError as exc:
                detail = exc.errors()[0]
                where = ".".join(str(seg) for seg in detail["loc"]) or "<args>"
                errors.append(
                    SpecError(
                        path=path,
                        loc=loc,
                        message=f"invalid arguments for {kind!r}: {where}: {detail['msg']}",
                        position=(
                            Position.from_lc(entry.lc.value(kind))
                            or Position.from_lc(entry.lc.key(kind))
                        ),
                    )
                )


# -- Main pass + orchestration ----------------------------------------------


def _pydantic_error(err: Any, root: Any, path: Path) -> SpecError:
    loc = tuple(err["loc"])
    kind = err["type"]
    message = PYDANTIC_MESSAGES.get(kind, err["msg"])
    if kind == "extra_forbidden" and loc:
        message = f"unknown field {loc[-1]!r}"
    elif kind == "missing" and loc:
        message = f"required field {loc[-1]!r} is missing"
    return SpecError(path=path, loc=loc, message=message, position=locate(root, loc))


def _sort_key(err: SpecError) -> tuple[int, int]:
    if err.position is None:
        return (0, 0)
    return (err.position.line, err.position.col)


def load_suite(path: Path) -> tuple[Suite | None, list[SpecError]]:
    """Load and validate one suite file. Returns the Suite only when the file is
    error-free; otherwise ``(None, errors)`` with every error collected."""
    errors: list[SpecError] = []
    root = load_positioned(path)

    root = resolve_refs(root, path.parent, path, errors)  # pre-pass 1a
    interpolate_env(root, path, errors)  # pre-pass 1b
    check_assertion_kinds(root, path, errors)  # pre-pass 2

    # A node whose $ref failed was replaced by a placeholder; any pydantic error
    # beneath that loc is a cascade artefact, not a user mistake — suppress it.
    poisoned = {e.loc[:-1] for e in errors if e.loc and e.loc[-1] == "$ref"}

    suite: Suite | None = None
    try:
        suite = Suite.model_validate(root)
    except ValidationError as exc:
        for err in exc.errors():
            loc = tuple(err["loc"])
            if any(loc[: len(p)] == p for p in poisoned):
                continue
            errors.append(_pydantic_error(err, root, path))

    errors.sort(key=_sort_key)
    return (None, errors) if errors else (suite, errors)


def load_suites(paths: Iterable[Path]) -> tuple[list[Suite], list[SpecError]]:
    """Load many suite files, aggregating suites and errors."""
    suites: list[Suite] = []
    errors: list[SpecError] = []
    for p in paths:
        suite, file_errors = load_suite(Path(p))
        if suite is not None:
            suites.append(suite)
        errors.extend(file_errors)
    return suites, errors

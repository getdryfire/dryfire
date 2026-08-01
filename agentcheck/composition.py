"""Composition root (ARCHITECTURE §7): the ONE module that wires concrete driven
adapters to the application, plus the `run` / `validate` / `trace` orchestration the
CLI drives. `cli.py` stays logic-free — it parses flags, calls these, and maps the
returned int to `typer.Exit` (SPEC §7.1 exit codes).

Exit codes are contractual: 0 all passed · 1 assertion failures · 2 spec/config
error · 3 provider/network error. **Config validity is checked before anything
network-touching happens**, so a spec error is 2 even when a provider is also
unreachable.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from agentcheck.adapters.driven.pricing.bundled import BundledPricingCatalog
from agentcheck.adapters.driven.reporting.json_sink import render_run, write_run
from agentcheck.adapters.driven.reporting.terminal import render_report, resolve_color
from agentcheck.adapters.driven.spec.config import (
    BUILTIN_CONCURRENCY,
    discover_config,
    glob_suites,
    load_project_config,
    resolve,
)
from agentcheck.adapters.driven.spec.errors import SpecError
from agentcheck.adapters.driven.spec.errors import render as render_spec_errors
from agentcheck.adapters.driven.spec.loader import load_suite
from agentcheck.adapters.driven.spec.mocks import map_mocks
from agentcheck.adapters.driven.spec.models import Defaults, Suite
from agentcheck.application.ports.model_gateway import ModelGateway
from agentcheck.application.scheduler import (
    CaseResult,
    PlannedCase,
    PlannedSuite,
    RunResult,
    run_suites,
)
from agentcheck.domain.mocking.resolver import merge_mocks
from agentcheck.domain.model.case import ResolvedCase
from agentcheck.domain.pricing.calculator import calculate

EXIT_OK = 0
EXIT_ASSERTION = 1
EXIT_CONFIG = 2
EXIT_PROVIDER = 3

_REPORT_BUG = "This looks like a bug in agentcheck — please report it."


class ConfigError(Exception):
    """A spec/config problem that maps to exit 2. The message is already
    user-facing (no traceback)."""


# -- Gateway selection (monkeypatched in tests to avoid the network) --------


def make_gateway(provider: str) -> ModelGateway:
    """The one place a concrete provider is chosen. v0.1 is Anthropic-only; the
    SDK import is lazy so `validate` (which never calls this) needs no SDK."""
    if provider == "anthropic":
        from agentcheck.adapters.driven.providers.anthropic import AnthropicGateway

        return AnthropicGateway()
    raise ConfigError(f"unknown provider: {provider!r}")


# -- Spec loading (network never touched here) ------------------------------


class _Loaded:
    def __init__(
        self, suites: list[tuple[Path, Suite]], errors: list[SpecError], defaults: Defaults | None
    ) -> None:
        self.suites = suites
        self.errors = errors
        self.defaults = defaults


def _load(paths: Sequence[str | Path], *, cwd: Path) -> _Loaded:
    try:
        config_path = discover_config(cwd)
        defaults = load_project_config(config_path).defaults if config_path else None
    except Exception as exc:  # noqa: BLE001 - a bad agentcheck.yaml is a config error (exit 2)
        raise ConfigError(f"invalid agentcheck.yaml: {exc}") from exc

    if paths:
        suite_paths = [Path(p) for p in paths]
    elif config_path is not None:
        suite_paths = glob_suites(config_path, load_project_config(config_path).suites)
    else:
        raise ConfigError("no suite paths given and no agentcheck.yaml found")

    loaded: list[tuple[Path, Suite]] = []
    errors: list[SpecError] = []
    for path in suite_paths:
        suite, errs = load_suite(path)
        errors.extend(errs)
        if suite is not None:
            loaded.append((path, suite))
    return _Loaded(loaded, errors, defaults)


def _render_errors(errors: list[SpecError]) -> str:
    # SpecErrors can span files; render() takes one file's lines, so group by path.
    out: list[str] = []
    by_path: dict[Path, list[SpecError]] = {}
    for err in errors:
        by_path.setdefault(err.path, []).append(err)
    for path, group in by_path.items():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        out.append(render_spec_errors(group, lines))
    return "\n".join(out) + "\n"


# -- Planning: filter, resolve, map mocks -----------------------------------


def _plan(
    loaded: _Loaded,
    *,
    filter_text: str | None,
    tags: Sequence[str],
    overrides: dict[str, Any],
) -> tuple[list[PlannedSuite], dict[tuple[str, str], ResolvedCase]]:
    planned: list[PlannedSuite] = []
    resolved_by: dict[tuple[str, str], ResolvedCase] = {}
    for path, suite in loaded.suites:
        if tags and not (set(tags) & set(suite.tags)):
            continue  # suite carries none of the requested tags
        cases: list[PlannedCase] = []
        for case in suite.cases:
            if filter_text and filter_text not in case.name:
                continue
            resolved = resolve(
                suite=suite, case=case, suite_path=path,
                project_defaults=loaded.defaults, overrides=overrides,
            )
            mocks = merge_mocks(map_mocks(suite.mocks or {}), map_mocks(case.mocks or {}))
            cases.append(PlannedCase(case=resolved, mocks=mocks))
            resolved_by[(suite.name, case.name)] = resolved
        if cases:  # a filtered-away suite is dropped, not shown empty
            planned.append(PlannedSuite(name=suite.name, path=path, cases=cases))
    return planned, resolved_by


def _provider_of(planned: list[PlannedSuite]) -> str:
    for suite in planned:
        for case in suite.cases:
            return case.case.provider
    return "anthropic"


# -- Cost attachment + exit code --------------------------------------------


def _price(run: RunResult, resolved_by: dict[tuple[str, str], ResolvedCase]) -> RunResult:
    catalog = BundledPricingCatalog()
    suites = []
    for suite in run.suites:
        cases = []
        for case in suite.cases:
            if case.trace is not None:
                resolved = resolved_by.get((suite.name, case.case_name))
                rates = catalog.rates(resolved.provider, resolved.model) if resolved else None
                cost = calculate(case.trace.total_usage, rates) if resolved else None
                total = float(cost.total) if cost is not None else None
                case = replace(case, trace=case.trace.model_copy(update={"total_cost_usd": total}))
            cases.append(case)
        suites.append(replace(suite, cases=cases))
    return replace(run, suites=suites)


def _exit_code(run: RunResult) -> int:
    cases = [case for suite in run.suites for case in suite.cases]
    if any(c.trace is not None and c.trace.termination == "provider_error" for c in cases):
        return EXIT_PROVIDER
    if any(not c.passed for c in cases):
        return EXIT_ASSERTION
    return EXIT_OK


# -- Reporting --------------------------------------------------------------


def _report(
    run: RunResult, *, reporter: str, json_out: str | None, verbose: bool,
    out: TextIO, now: datetime,
) -> None:
    if reporter == "json":
        out.write(render_run(run, generated_at=now))
        return
    out.write(render_report(run, color=resolve_color(out)))
    if verbose:  # -v: dump every turn of each failing case beneath the report
        for suite in run.suites:
            for case in suite.cases:
                if not case.passed:
                    out.write(_render_trace(case))
    if json_out is not None:
        write_run(run, Path(json_out), generated_at=now)


def _render_trace(case: CaseResult) -> str:
    status = "PASS" if case.passed else "FAIL"
    lines = [f"{case.suite_name}::{case.case_name}  [{status}]"]
    if case.error:
        lines.append(f"  error: {case.error}")
    trace = case.trace
    if trace is None:
        return "\n".join(lines) + "\n"
    for turn in trace.turns:
        lines.append(f"── turn {turn.index} ──")
        for message in turn.request_messages:
            lines.append(f"  [{message.role}] {message.content!r}")
        if turn.response.text:
            lines.append(f"  response: {turn.response.text}")
        for call in turn.response.tool_calls:
            lines.append(f"  → {call.name}({json.dumps(call.arguments)})")
        for result in turn.tool_results:
            flag = " [error]" if result.is_error else ""
            lines.append(f"  ← tool_result{flag}: {result.content!r}")
    lines.append(f"termination: {trace.termination}")
    return "\n".join(lines) + "\n"


# -- Commands (return exit codes; the CLI maps them to typer.Exit) ----------


def validate(paths: Sequence[str], *, debug: bool = False, out: TextIO, err: TextIO) -> int:
    """Parse and validate specs. **Zero network calls, ever.**"""
    try:
        loaded = _load(paths, cwd=Path.cwd())
        if loaded.errors:
            err.write(_render_errors(loaded.errors))
            return EXIT_CONFIG
        cases = sum(len(s.cases) for _, s in loaded.suites)
        out.write(f"ok: {len(loaded.suites)} suite(s), {cases} case(s)\n")
        return EXIT_OK
    except ConfigError as exc:
        err.write(f"error: {exc}\n")
        return EXIT_CONFIG
    except Exception as exc:  # noqa: BLE001 - unhandled → clean message, exit 2 (SPEC §7.1)
        return _internal_error(exc, err=err, debug=debug)


def run(
    paths: Sequence[str],
    *,
    filter_text: str | None = None,
    tags: Sequence[str] = (),
    model: str | None = None,
    concurrency: int | None = None,
    fail_fast: bool = False,
    reporter: str = "terminal",
    json_out: str | None = None,
    verbose: bool = False,
    debug: bool = False,
    out: TextIO,
    err: TextIO,
    now: datetime | None = None,
) -> int:
    """Run suites and report; return the contractual exit code."""
    try:
        loaded = _load(paths, cwd=Path.cwd())
        if loaded.errors:  # config before network — spec error is 2 even if provider is down
            err.write(_render_errors(loaded.errors))
            return EXIT_CONFIG

        overrides = {"model": model} if model else {}
        planned, resolved_by = _plan(
            loaded, filter_text=filter_text, tags=tags, overrides=overrides
        )
        if not planned:
            out.write("no cases matched\n")
            return EXIT_OK

        gateway = make_gateway(_provider_of(planned))
        result = asyncio.run(
            run_suites(planned, gateway, concurrency=concurrency or BUILTIN_CONCURRENCY,
                       fail_fast=fail_fast)
        )
        result = _price(result, resolved_by)
        _report(result, reporter=reporter, json_out=json_out, verbose=verbose,
                out=out, now=now or datetime.now(UTC))
        return _exit_code(result)
    except ConfigError as exc:
        err.write(f"error: {exc}\n")
        return EXIT_CONFIG
    except Exception as exc:  # noqa: BLE001 - unhandled → clean message, exit 2 (SPEC §7.1)
        return _internal_error(exc, err=err, debug=debug)


def trace(
    address: str,
    paths: Sequence[str],
    *,
    model: str | None = None,
    debug: bool = False,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run a single `suite::case` and print every turn — the debugging command."""
    try:
        suite_name, sep, case_name = address.partition("::")
        if not sep:
            raise ConfigError(f"trace address must be 'suite::case', got {address!r}")

        loaded = _load(paths, cwd=Path.cwd())
        if loaded.errors:
            err.write(_render_errors(loaded.errors))
            return EXIT_CONFIG

        overrides = {"model": model} if model else {}
        planned, _ = _plan(loaded, filter_text=None, tags=(), overrides=overrides)
        target = _find_case(planned, suite_name, case_name)
        if target is None:
            raise ConfigError(f"no case {address!r} found")

        gateway = make_gateway(target.case.provider)
        result = asyncio.run(run_suites([target_suite(target)], gateway))
        case_result = result.suites[0].cases[0]
        out.write(_render_trace(case_result))
        return _exit_code(result)
    except ConfigError as exc:
        err.write(f"error: {exc}\n")
        return EXIT_CONFIG
    except Exception as exc:  # noqa: BLE001 - unhandled → clean message, exit 2 (SPEC §7.1)
        return _internal_error(exc, err=err, debug=debug)


def _find_case(
    planned: list[PlannedSuite], suite_name: str, case_name: str
) -> PlannedCase | None:
    for suite in planned:
        if suite.name != suite_name:
            continue
        for case in suite.cases:
            if case.case.case_name == case_name:
                return case
    return None


def target_suite(case: PlannedCase) -> PlannedSuite:
    return PlannedSuite(name=case.case.suite_name, path=case.case.suite_path, cases=[case])


def _internal_error(exc: Exception, *, err: TextIO, debug: bool) -> int:
    if debug:
        raise exc
    err.write(f"error: internal error: {exc}\n{_REPORT_BUG}\n")
    return EXIT_CONFIG

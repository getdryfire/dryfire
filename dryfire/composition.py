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
import glob
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

from dryfire.adapters.driven.cache.file_store import FileCassetteStore, sanitise
from dryfire.adapters.driven.cache.prune import find_prunable, remove_empty_dirs
from dryfire.adapters.driven.clock.system import SystemClock
from dryfire.adapters.driven.mocking.passthrough import PassthroughInvoker
from dryfire.adapters.driven.pricing.bundled import BundledPricingCatalog
from dryfire.adapters.driven.providers.caching import CachingGateway
from dryfire.adapters.driven.providers.fake import FakeGateway
from dryfire.adapters.driven.providers.retrying import RetryingGateway
from dryfire.adapters.driven.reporting.json_sink import render_run, write_run
from dryfire.adapters.driven.reporting.junit_sink import render_junit, write_junit
from dryfire.adapters.driven.reporting.terminal import render_report, resolve_color
from dryfire.adapters.driven.scaffold.writer import ScaffoldConflict, scaffold
from dryfire.adapters.driven.spec.config import (
    BUILTIN_CONCURRENCY,
    discover_config,
    glob_suites,
    load_project_config,
    resolve,
)
from dryfire.adapters.driven.spec.errors import SpecError
from dryfire.adapters.driven.spec.errors import render as render_spec_errors
from dryfire.adapters.driven.spec.loader import load_suite
from dryfire.adapters.driven.spec.mocks import map_mocks
from dryfire.adapters.driven.spec.models import Case, CassetteConfig, CassetteMode, Defaults, Suite
from dryfire.adapters.driven.spec.scripts import map_script
from dryfire.application.judging.collect import collect_judge_requests
from dryfire.application.judging.evaluator import DEFAULT_JUDGE_CONCURRENCY, JudgeEvaluator
from dryfire.application.ports.model_gateway import CompletionRequest, ModelGateway
from dryfire.application.ports.response_cache import ResponseCache
from dryfire.application.scheduler import (
    CaseResult,
    JudgeTrace,
    PlannedCase,
    PlannedSuite,
    RunResult,
    run_suites,
)
from dryfire.domain.mocking.resolver import Passthrough, merge_mocks
from dryfire.domain.model.case import ResolvedCase
from dryfire.domain.model.message import ModelResponse
from dryfire.domain.model.trace import Trace
from dryfire.domain.pricing.calculator import calculate

BUILTIN_MAX_RETRIES = 3  # DF-206; overridable via --max-retries

EXIT_OK = 0
EXIT_ASSERTION = 1
EXIT_CONFIG = 2
EXIT_PROVIDER = 3

_REPORT_BUG = "This looks like a bug in dryfire — please report it."


class ConfigError(Exception):
    """A spec/config problem that maps to exit 2. The message is already
    user-facing (no traceback)."""


class MissingCredentials(Exception):
    """A real provider has no API key in the environment. `run` treats this as a
    *skip* (the case is not run, not failed — AC-016); `trace` surfaces it as an
    error. Raised inside `make_gateway` so the test seam that replaces
    `make_gateway` bypasses the check entirely."""

    def __init__(self, provider: str, env_var: str) -> None:
        super().__init__(f"{provider} needs an API key in {env_var}")
        self.provider = provider
        self.env_var = env_var


# -- Gateway selection (monkeypatched in tests to avoid the network) --------


def make_gateway(provider: str) -> ModelGateway:
    """The one place a concrete real provider is chosen. v0.1 is Anthropic-only;
    the SDK import is lazy so `validate` (which never calls this) needs no SDK.
    Fake gateways are scripted per case and built in `_plan`, never here.

    Raises `MissingCredentials` when the provider's key is absent, so composition
    can skip those cases rather than fail them."""
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise MissingCredentials("anthropic", "ANTHROPIC_API_KEY")
        from dryfire.adapters.driven.providers.anthropic import AnthropicGateway

        return AnthropicGateway()
    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise MissingCredentials("openai", "OPENAI_API_KEY")
        from dryfire.adapters.driven.providers.openai import OpenAIGateway

        return OpenAIGateway()
    raise ConfigError(f"unknown provider: {provider!r}")


# -- Spec loading (network never touched here) ------------------------------


class _Loaded:
    def __init__(
        self,
        suites: list[tuple[Path, Suite]],
        errors: list[SpecError],
        defaults: Defaults | None,
        cassettes: CassetteConfig | None = None,
        config_dir: Path | None = None,
    ) -> None:
        self.suites = suites
        self.errors = errors
        self.defaults = defaults
        self.cassettes = cassettes  # cassette dir/mode from project config (DF-204)
        self.config_dir = config_dir  # cassette paths resolve relative to this


def _glob_cli_paths(patterns: Sequence[str | Path], cwd: Path) -> list[Path]:
    """Expand CLI suite arguments as globs, relative to `cwd`, so
    `dryfire run "evals/**/*.eval.yaml"` resolves the same way a `dryfire.yaml`
    pattern does — and does not depend on the shell to expand `**`. A literal path
    that exists matches itself. Results are de-duplicated and ordered."""
    found: list[Path] = []
    for pattern in patterns:
        pat = str(pattern)
        if Path(pat).is_absolute():
            found.extend(Path(m) for m in glob.glob(pat, recursive=True))
        else:
            found.extend(cwd / m for m in glob.glob(pat, root_dir=cwd, recursive=True))
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in found:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(path)
    return sorted(ordered, key=str)


def _load(paths: Sequence[str | Path], *, cwd: Path) -> _Loaded:
    try:
        config_path = discover_config(cwd)
        project = load_project_config(config_path) if config_path else None
    except Exception as exc:  # noqa: BLE001 - a bad dryfire.yaml is a config error (exit 2)
        raise ConfigError(f"invalid dryfire.yaml: {exc}") from exc

    defaults = project.defaults if project else None
    cassettes = project.cassettes if project else None
    config_dir = config_path.parent if config_path else None

    if paths:
        suite_paths = _glob_cli_paths(paths, cwd)
        if not suite_paths:
            raise ConfigError(
                "no suite files matched: " + ", ".join(str(p) for p in paths)
            )
    elif config_path is not None and project is not None:
        suite_paths = glob_suites(config_path, project.suites)
    else:
        raise ConfigError("no suite paths given and no dryfire.yaml found")

    loaded: list[tuple[Path, Suite]] = []
    errors: list[SpecError] = []
    for path in suite_paths:
        suite, errs = load_suite(path)
        errors.extend(errs)
        if suite is not None:
            loaded.append((path, suite))
    return _Loaded(loaded, errors, defaults, cassettes, config_dir)


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


def _fake_gateway_for(provider: str, case: Case) -> FakeGateway | None:
    """A `provider: fake` case carries a scripted gateway built from its `script`;
    every other provider defers to the shared run default (returns None). A fake
    case with no script can't answer, so that's a config error (AC-016)."""
    if provider != "fake":
        return None
    if not case.script:
        raise ConfigError(f"case {case.name!r} uses provider 'fake' but has no 'script'")
    return FakeGateway.script(map_script(case.script))


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
            gateway = _fake_gateway_for(resolved.provider, case)
            cases.append(PlannedCase(case=resolved, mocks=mocks, gateway=gateway))
            resolved_by[(suite.name, case.name)] = resolved
        if cases:  # a filtered-away suite is dropped, not shown empty
            planned.append(PlannedSuite(name=suite.name, path=path, cases=cases))
    return planned, resolved_by


def _partition_by_availability(
    planned: list[PlannedSuite], *, out: TextIO
) -> tuple[list[PlannedSuite], ModelGateway | None]:
    """Drop cases whose real provider has no credentials, printing a skip note for
    each (skipped ≠ failed, AC-016). Returns the runnable suites and the shared
    run-default gateway for the real provider — v0.1 has at most one (Anthropic);
    every fake case carries its own, so the default may be None."""
    real_providers = {c.case.provider for s in planned for c in s.cases if c.gateway is None}
    gateways: dict[str, ModelGateway] = {}
    skip_env: dict[str, str] = {}  # provider → env var, for the unavailable ones
    for provider in real_providers:
        try:
            gateways[provider] = make_gateway(provider)
        except MissingCredentials as exc:
            skip_env[provider] = exc.env_var

    runnable: list[PlannedSuite] = []
    default_gateway: ModelGateway | None = None
    for suite in planned:
        keep: list[PlannedCase] = []
        for case in suite.cases:
            provider = case.case.provider
            if case.gateway is None and provider in skip_env:
                out.write(
                    f"skipped {suite.name}::{case.case.case_name} "
                    f"(needs {skip_env[provider]})\n"
                )
                continue
            keep.append(case)
            if case.gateway is None:
                default_gateway = gateways[provider]
        if keep:
            runnable.append(replace(suite, cases=keep))
    return runnable, default_gateway


# -- Cassettes: mode resolution + wrapping (DF-204) -------------------------


class _NoLiveGateway:
    """The wrapped gateway for replay mode: it must never be called, because
    every turn is served from a cassette. If it is called, a replay miss slipped
    past the caching layer — fail loudly rather than silently reaching a provider."""

    def __init__(self, provider: str) -> None:
        self.name = provider

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        raise RuntimeError("replay mode must not make a live provider call")


def _resolve_cassettes(
    flag: str | None, loaded: _Loaded, *, cwd: Path
) -> tuple[CassetteMode, ResponseCache | None]:
    """Resolve the cassette mode (CLI flag > project config > `off`) and, when it
    is not `off`, the store rooted at the project's cassette dir."""
    raw = flag or (loaded.cassettes.mode if loaded.cassettes else None) or "off"
    if raw not in ("auto", "record", "replay", "off"):
        raise ConfigError(f"invalid --cassette-mode {raw!r}; expected auto|record|replay|off")
    mode = cast(CassetteMode, raw)
    if mode == "off":
        return mode, None
    dirname = (loaded.cassettes.dir if loaded.cassettes else None) or ".dryfire/cassettes"
    base = loaded.config_dir or cwd
    return mode, FileCassetteStore(base / dirname)


def _uses_passthrough(planned: PlannedCase) -> bool:
    """True if any of the case's mocks delivers its result by invoking real code."""
    return any(
        isinstance(rule.outcome, Passthrough)
        for rules in planned.mocks.values()
        for rule in rules
    )


def _wrap_cases(
    suites: list[PlannedSuite], *, inner_for: Any, store: ResponseCache, mode: CassetteMode,
    exclude_passthrough: bool = False, out: TextIO | None = None,
) -> list[PlannedSuite]:
    """Wrap every real-provider case (one with no per-case gateway) in a
    CachingGateway. `inner_for(case)` supplies the wrapped gateway; fake cases,
    which already carry their scripted gateway, are left untouched.

    `exclude_passthrough` (recording modes) leaves a case that uses passthrough
    mocks UNwrapped — a real callable can have side effects and non-deterministic
    output, so recording it would make replay a lie (SPIKE-004 Q4). The exclusion
    is announced on `out`, never silent."""
    wrapped: list[PlannedSuite] = []
    for suite in suites:
        cases: list[PlannedCase] = []
        for planned in suite.cases:
            if planned.gateway is None:
                if exclude_passthrough and _uses_passthrough(planned):
                    if out is not None:
                        out.write(
                            f"note: {suite.name}::{planned.case.case_name} uses passthrough "
                            f"mocks — excluded from cassette recording (results aren't cacheable)\n"
                        )
                else:
                    caching = CachingGateway(
                        inner_for(planned), store, mode=mode,
                        suite=suite.name, case=planned.case.case_name,
                    )
                    planned = replace(planned, gateway=caching)
            cases.append(planned)
        wrapped.append(replace(suite, cases=cases))
    return wrapped


# -- Cost attachment + exit code --------------------------------------------


def _make_price() -> Callable[[Trace, ResolvedCase], Trace]:
    """A pricing callback for the scheduler: attach advisory cost + the model to a
    trace *before* assertions run, so `cost_under` (DF-207) can read it. Unknown
    model → cost stays None (never a guess). The model is recorded so the
    cost_under failure message can name it."""
    catalog = BundledPricingCatalog()

    def price(trace: Trace, case: ResolvedCase) -> Trace:
        rates = catalog.rates(case.provider, case.model)
        cost = calculate(trace.total_usage, rates)
        total = float(cost.total) if cost is not None else None
        return trace.model_copy(update={"total_cost_usd": total, "model": case.model})

    return price


def _suites_use_judge(suites: list[PlannedSuite]) -> bool:
    """True if any runnable case carries an `llm_judge` assertion. When false, the run
    passes `judge=None` and takes the exact v0.2 code path — structural-only suites pay
    nothing for a feature they do not use (EPIC-003 success criterion 2)."""
    return any(collect_judge_requests(pc.case) for suite in suites for pc in suite.cases)


def _make_judge(*, concurrency: int = DEFAULT_JUDGE_CONCURRENCY) -> JudgeTrace:
    """The judging enrichment callback for the scheduler (ARCHITECTURE §4.4). Closes
    over ONE semaphore so judge concurrency is bounded across the whole run, and grades
    each case through the case's own gateway — the CachingGateway in cassette modes — so
    judge calls are cassette-backed and retried exactly like agent calls, with no second
    client. Judge cost stays a separate channel (DF-304)."""
    sem = asyncio.Semaphore(concurrency)

    async def judge(trace: Trace, case: ResolvedCase, gateway: ModelGateway) -> Trace:
        requests = collect_judge_requests(case)
        if not requests:  # structural-only case: never touch the gateway
            return trace
        verdicts = await JudgeEvaluator(gateway=gateway, sem=sem).evaluate(trace, requests)
        return trace.model_copy(update={"judge_verdicts": verdicts, "model": case.model})

    return judge


def _exit_code(run: RunResult) -> int:
    cases = [case for suite in run.suites for case in suite.cases]
    if any(c.trace is not None and c.trace.termination == "provider_error" for c in cases):
        return EXIT_PROVIDER
    if any(not c.passed for c in cases):
        return EXIT_ASSERTION
    return EXIT_OK


# -- Reporting --------------------------------------------------------------


def _report(
    run: RunResult, *, reporter: str, json_out: str | None, junit_out: str | None,
    verbose: bool, out: TextIO, now: datetime,
) -> None:
    # `--reporter` picks the stdout format; `--json-out`/`--junit-out` are independent
    # atomic file sinks that compose with any reporter (SPEC §7, DF-209).
    if reporter == "json":
        out.write(render_run(run, generated_at=now))
    elif reporter == "junit":
        out.write(render_junit(run, generated_at=now))
    else:
        out.write(render_report(run, color=resolve_color(out)))
        if verbose:  # -v: dump every turn of each failing case beneath the report
            for suite in run.suites:
                for case in suite.cases:
                    if not case.passed:
                        out.write(_render_trace(case))
    if json_out is not None:
        write_run(run, Path(json_out), generated_at=now)
    if junit_out is not None:
        write_junit(run, Path(junit_out), generated_at=now)


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


def _next_command(dst: Path) -> str:
    """The single copy-pasteable command to run right after `init`."""
    if dst.resolve() == Path.cwd().resolve():
        return "dryfire run"
    return f"cd {dst} && dryfire run"


def init(target: str = ".", *, force: bool = False, out: TextIO, err: TextIO) -> int:
    """Scaffold a runnable example project into `target` (SPEC §1.6, AC-016).

    Refuses to overwrite existing files without `force`, listing the conflicts.
    On success, prints what it created and the one command to run next."""
    dst = Path(target)
    try:
        written = scaffold(dst, force=force)
    except ScaffoldConflict as exc:
        err.write(f"error: {exc}\n")
        err.write("re-run `dryfire init --force` to overwrite them.\n")
        return EXIT_CONFIG
    except Exception as exc:  # noqa: BLE001 - unhandled → clean message, exit 2 (SPEC §7.1)
        return _internal_error(exc, err=err, debug=False)

    for rel in written:
        out.write(f"  created {rel}\n")
    where = "the current directory" if dst == Path(".") else str(dst)
    out.write(
        f"\nScaffolded {len(written)} files into {where}. "
        f"No API key needed for the example. Next:\n\n    {_next_command(dst)}\n"
    )
    return EXIT_OK


def prune(*, yes: bool = False, debug: bool = False, out: TextIO, err: TextIO) -> int:
    """Delete orphaned or stale cassettes (DF-205). Dry-run unless `yes`. Exits 0
    whether or not anything was pruned; a cassette belonging to a suite that failed
    to parse is never touched."""
    try:
        cwd = Path.cwd()
        config_path = discover_config(cwd)
        if config_path is None:
            raise ConfigError("no dryfire.yaml found — run `dryfire init` first")
        project = load_project_config(config_path)
        config_dir = config_path.parent

        valid: dict[str, set[str]] = {}
        had_parse_failure = False
        for path in glob_suites(config_path, project.suites):
            suite, errs = load_suite(path)
            if suite is None or errs:
                had_parse_failure = True  # unknown name → protect its cassettes
                continue
            valid[sanitise(suite.name)] = {sanitise(c.name) for c in suite.cases}

        dirname = (project.cassettes.dir if project.cassettes else None) or ".dryfire/cassettes"
        root = config_dir / dirname
        candidates = find_prunable(root, valid, had_parse_failure=had_parse_failure)

        if not candidates:
            out.write("nothing to prune\n")
            return EXIT_OK

        verb = "removed" if yes else "would remove"
        for candidate in candidates:
            out.write(f"{verb} {candidate.path.relative_to(config_dir)} ({candidate.reason})\n")
        if yes:
            for candidate in candidates:
                candidate.path.unlink(missing_ok=True)
            remove_empty_dirs(root)
        else:
            out.write(
                f"\n{len(candidates)} cassette(s) would be removed. "
                "Re-run with --yes to delete.\n"
            )
        return EXIT_OK
    except ConfigError as exc:
        err.write(f"error: {exc}\n")
        return EXIT_CONFIG
    except Exception as exc:  # noqa: BLE001 - unhandled → clean message, exit 2 (SPEC §7.1)
        return _internal_error(exc, err=err, debug=debug)


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
    junit_out: str | None = None,
    cassette_mode: str | None = None,
    max_retries: int | None = None,
    verbose: bool = False,
    debug: bool = False,
    out: TextIO,
    err: TextIO,
    now: datetime | None = None,
) -> int:
    """Run suites and report; return the contractual exit code."""
    try:
        cwd = Path.cwd()
        loaded = _load(paths, cwd=cwd)
        if loaded.errors:  # config before network — spec error is 2 even if provider is down
            err.write(_render_errors(loaded.errors))
            return EXIT_CONFIG

        overrides = {"model": model} if model else {}
        planned, _ = _plan(
            loaded, filter_text=filter_text, tags=tags, overrides=overrides
        )
        if not planned:
            out.write("no cases matched\n")
            return EXIT_OK

        mode, store = _resolve_cassettes(cassette_mode, loaded, cwd=cwd)
        if mode == "replay":
            # Replay needs no credentials — cassettes serve every turn, so skip the
            # availability check entirely and wrap each real case in a replay gateway.
            assert store is not None
            runnable = _wrap_cases(
                planned, inner_for=lambda pc: _NoLiveGateway(pc.case.provider),
                store=store, mode=mode,
            )
            default_gateway: ModelGateway | None = None
        else:
            runnable, real_gateway = _partition_by_availability(planned, out=out)
            if not runnable:  # every case was skipped for want of credentials
                return EXIT_OK
            # Retries wrap the live gateway; order is Caching(Retrying(Real)) — a
            # cache hit returns before the retry layer, and retries apply only live.
            default_gateway = (
                RetryingGateway(
                    real_gateway, clock=SystemClock(),
                    max_retries=max_retries if max_retries is not None else BUILTIN_MAX_RETRIES,
                )
                if real_gateway is not None
                else None
            )
            if store is not None and default_gateway is not None:  # auto / record
                runnable = _wrap_cases(
                    runnable, inner_for=lambda pc: default_gateway, store=store, mode=mode,
                    exclude_passthrough=True, out=out,
                )

        judge = _make_judge() if _suites_use_judge(runnable) else None
        result = asyncio.run(
            run_suites(runnable, default_gateway, price=_make_price(),
                       concurrency=concurrency or BUILTIN_CONCURRENCY, fail_fast=fail_fast,
                       invoker=PassthroughInvoker(), judge=judge)
        )
        _report(result, reporter=reporter, json_out=json_out, junit_out=junit_out,
                verbose=verbose, out=out, now=now or datetime.now(UTC))
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

        # A fake target carries its own scripted gateway; a real one needs a key
        # now — trace is an explicit request, so a missing key is an error, not a
        # silent skip.
        default_gateway: ModelGateway | None = None
        if target.gateway is None:
            try:
                default_gateway = make_gateway(target.case.provider)
            except MissingCredentials as exc:
                raise ConfigError(str(exc)) from exc
        one = [target_suite(target)]
        result = asyncio.run(
            run_suites(one, default_gateway, price=_make_price(),
                       judge=_make_judge() if _suites_use_judge(one) else None)
        )
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

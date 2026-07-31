"""The concurrent case scheduler (SPEC §5, ARCHITECTURE §6.1).

`run_case` (AC-009) deliberately owns no scheduling. This module runs many cases
concurrently under an `asyncio.Semaphore`-equivalent worker pool, evaluates each
case's assertions, and returns results in **spec order, not completion order** —
reporters depend on that for stable, diffable output.

Application layer: imports domain values and the `ModelGateway` port only, never a
concrete adapter. The spec→domain mock mapper (adapter `MockRule` → domain
`MockRule`) cannot live here (it would import the adapter); composition (AC-015)
maps and merges mocks, then hands this scheduler pre-planned cases. Each case gets
a **fresh `MockResolver`** so concurrent cases never share `sequence` state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcheck.application.loop import run_case
from agentcheck.application.ports.model_gateway import ModelGateway
from agentcheck.domain.assertions.base import AssertionResult, safe_evaluate
from agentcheck.domain.assertions.registry import build
from agentcheck.domain.mocking.resolver import MockResolver, MockRule
from agentcheck.domain.model.case import ResolvedCase
from agentcheck.domain.model.trace import Trace

DEFAULT_CONCURRENCY = 4  # SPEC §5; overridable via --concurrency (AC-015)

# Progress goes through this callback, never a print — the reporter (AC-013) owns
# all output. Called once per completed case, in completion order.
ProgressCallback = Callable[["CaseResult"], None]


# -- Inputs: a run planned down to fresh-per-case domain mocks ---------------


@dataclass(frozen=True)
class PlannedCase:
    """One runnable case: a resolved case plus its already-merged domain mocks.
    The scheduler builds a fresh `MockResolver(mocks)` per case at execution time."""

    case: ResolvedCase
    mocks: dict[str, list[MockRule]] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedSuite:
    """One suite's cases in spec order. `name`/`path` are carried explicitly so a
    suite keeps its identity even when every case is cancelled (fail-fast)."""

    name: str
    path: Path
    cases: list[PlannedCase]


# -- Outputs: results in spec order, three levels deep -----------------------


@dataclass(frozen=True)
class CaseResult:
    """One case fully processed (ARCHITECTURE §6.1 `CaseCompleted`): its Trace, the
    evaluated assertions, and pass/fail. `trace` is None and `error` is set when the
    case raised unexpectedly — isolated so the rest of the run continues."""

    suite_name: str
    case_name: str
    trace: Trace | None
    assertions: list[AssertionResult]
    passed: bool
    error: str | None = None


@dataclass(frozen=True)
class SuiteResult:
    name: str
    path: Path
    cases: list[CaseResult]


@dataclass(frozen=True)
class RunResult:
    """Every suite's results in spec order. `complete` is False when fail-fast
    cancelled in-flight cases — the run must never present a partial set as full."""

    suites: list[SuiteResult]
    complete: bool = True


def _evaluate(expect: list[dict[str, Any]], trace: Trace) -> list[AssertionResult]:
    """Build each `expect` entry ({kind: args}) into an assertion and evaluate it.
    `build` may raise on a malformed entry (kinds/args are validated at load, so
    this is defensive); the caller isolates that into a failed CaseResult."""
    results: list[AssertionResult] = []
    for entry in expect:
        kind = next(iter(entry))
        results.append(safe_evaluate(build(kind, entry[kind]), trace))
    return results


async def _process_case(planned: PlannedCase, provider: ModelGateway) -> CaseResult:
    case = planned.case
    try:
        # A fresh resolver per case: AC-008 sequence state must not bleed across
        # concurrently-running cases.
        resolver = MockResolver(dict(planned.mocks))
        trace = await run_case(case, provider, resolver)
        assertions = _evaluate(case.expect, trace)
        passed = all(a.passed for a in assertions)
        return CaseResult(case.suite_name, case.case_name, trace, assertions, passed)
    except asyncio.CancelledError:
        raise  # fail-fast cancellation must propagate, never be swallowed as a result
    except Exception as exc:  # noqa: BLE001 - one case's failure must not abort the run
        return CaseResult(case.suite_name, case.case_name, None, [], False, error=repr(exc))


def _group(
    suites: list[PlannedSuite], results: list[CaseResult | None]
) -> list[SuiteResult]:
    grouped: list[SuiteResult] = []
    idx = 0
    for suite in suites:
        cases: list[CaseResult] = []
        for _ in suite.cases:
            result = results[idx]
            if result is not None:  # None = never ran / cancelled in-flight
                cases.append(result)
            idx += 1
        grouped.append(SuiteResult(suite.name, suite.path, cases))
    return grouped


async def run_suites(
    suites: list[PlannedSuite],
    provider: ModelGateway,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    fail_fast: bool = False,
    on_progress: ProgressCallback | None = None,
) -> RunResult:
    """Run every case concurrently (bounded to `concurrency`) and return results in
    spec order regardless of completion order.

    `fail_fast`: on the first case that does not pass, cancel every in-flight case
    and return only the results that already completed, with `complete=False`. A
    partial run is never presented as a full one."""
    planned = [pc for suite in suites for pc in suite.cases]
    results: list[CaseResult | None] = [None] * len(planned)
    # A shared iterator is the whole pool discipline: workers pull the next index;
    # `next()` has no await between pulls, so no two workers ever get the same one.
    pending = iter(range(len(planned)))
    workers: list[asyncio.Task[None]] = []

    async def worker() -> None:
        for i in pending:
            result = await _process_case(planned[i], provider)
            results[i] = result
            if on_progress is not None:
                on_progress(result)
            if fail_fast and not result.passed:
                for other in workers:
                    if other is not asyncio.current_task():
                        other.cancel()  # in-flight cases end with no result → dropped
                return

    n_workers = min(concurrency, len(planned))
    workers = [asyncio.create_task(worker()) for _ in range(n_workers)]
    # return_exceptions swallows the CancelledError raised in cancelled workers.
    await asyncio.gather(*workers, return_exceptions=True)

    return RunResult(_group(suites, results), complete=all(r is not None for r in results))

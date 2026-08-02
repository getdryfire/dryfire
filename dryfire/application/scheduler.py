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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dryfire.application.loop import run_case
from dryfire.application.ports.model_gateway import ModelGateway
from dryfire.application.ports.tool_invoker import ToolInvoker
from dryfire.domain.assertions.base import AssertionResult, safe_evaluate
from dryfire.domain.assertions.registry import build
from dryfire.domain.mocking.resolver import MockResolver, MockRule
from dryfire.domain.model.case import ResolvedCase
from dryfire.domain.model.trace import Trace

DEFAULT_CONCURRENCY = 4  # SPEC §5; overridable via --concurrency (AC-015)

# Progress goes through this callback, never a print — the reporter (AC-013) owns
# all output. Called once per completed case, in completion order.
ProgressCallback = Callable[["CaseResult"], None]

# Attaches advisory cost (and the model) to a trace before assertions run, so
# `cost_under` can read it (DF-207). Injected by composition, which owns the
# pricing catalog; the scheduler stays adapter-free.
PriceTrace = Callable[[Trace, ResolvedCase], Trace]

# Grades a case's `llm_judge` assertions and attaches the verdicts to the trace,
# after pricing and *before* assertions run (ARCHITECTURE §4.4, the judging enrichment
# seam / SPIKE-006 Model C). Async and gateway-backed — it receives the case's resolved
# gateway so judge calls are cassette-backed exactly like agent calls. Injected by
# composition; None (the structural-only default) takes the exact v0.2 path. The loop is
# not in this call graph and does not change.
JudgeTrace = Callable[[Trace, ResolvedCase, ModelGateway], Awaitable[Trace]]


# -- Inputs: a run planned down to fresh-per-case domain mocks ---------------


@dataclass(frozen=True)
class PlannedCase:
    """One runnable case: a resolved case plus its already-merged domain mocks.
    The scheduler builds a fresh `MockResolver(mocks)` per case at execution time.

    `gateway` overrides the run-level default for this one case (AC-016): a
    `provider: fake` case carries its own freshly-scripted `FakeGateway` — stateful,
    so it must not be shared — while real-provider cases fall back to the shared
    run default. Composition (which may import concretes) assigns it; the type here
    is the `ModelGateway` port, so the application stays adapter-free."""

    case: ResolvedCase
    mocks: dict[str, list[MockRule]] = field(default_factory=dict)
    gateway: ModelGateway | None = None
    # DF-306: a per-repetition gateway builder. When set (cassette-backed cases), the
    # scheduler asks it for a fresh gateway per repetition, passing the repeat index so
    # each repetition records/replays under its own cassette key. `None` (the common
    # case) falls back to `gateway` / the run default — repeat: 1 is unaffected.
    gateway_factory: Callable[[int], ModelGateway] | None = None


@dataclass(frozen=True)
class PlannedSuite:
    """One suite's cases in spec order. `name`/`path` are carried explicitly so a
    suite keeps its identity even when every case is cancelled (fail-fast)."""

    name: str
    path: Path
    cases: list[PlannedCase]


# -- Outputs: results in spec order, three levels deep -----------------------


@dataclass(frozen=True)
class Repetition:
    """One run of a repeated case (DF-305): its Trace, assertions, and pass/fail. N of
    these back a repeated `CaseResult`; the JSON artifact keeps them all."""

    trace: Trace | None
    assertions: list[AssertionResult]
    passed: bool
    error: str | None = None


@dataclass(frozen=True)
class CaseResult:
    """One case fully processed (ARCHITECTURE §6.1 `CaseCompleted`): its Trace, the
    evaluated assertions, and pass/fail. `trace` is None and `error` is set when the
    case raised unexpectedly — isolated so the rest of the run continues.

    For a repeated case (DF-305, `repeat: N`), `repetitions` holds all N runs and
    `passed` reflects whether the pass rate met `require_pass_rate`; `trace`/`assertions`
    then carry the first *failing* repetition (what a reader wants to see). A non-repeated
    case leaves `repetitions`/`require_pass_rate` None, so it is byte-identical to v0.2."""

    suite_name: str
    case_name: str
    trace: Trace | None
    assertions: list[AssertionResult]
    passed: bool
    error: str | None = None
    repetitions: list[Repetition] | None = None
    require_pass_rate: float | None = None

    @property
    def total(self) -> int | None:
        """N, for a repeated case; None otherwise."""
        return None if self.repetitions is None else len(self.repetitions)

    @property
    def passes(self) -> int | None:
        """k (repetitions that passed), for a repeated case; None otherwise."""
        return None if self.repetitions is None else sum(r.passed for r in self.repetitions)

    @property
    def pass_rate(self) -> float | None:
        """k/N, for a repeated case; None otherwise."""
        if self.repetitions is None:
            return None
        total = len(self.repetitions)
        return sum(r.passed for r in self.repetitions) / total if total else 0.0


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


async def _process_case(
    planned: PlannedCase, provider: ModelGateway | None, price: PriceTrace | None,
    invoker: ToolInvoker | None = None, judge: JudgeTrace | None = None,
    repeat_index: int = 0,
) -> CaseResult:
    case = planned.case
    try:
        # A per-repetition gateway (DF-306) wins, then the per-case gateway, then the run
        # default; a case with none is a planning bug, isolated as a case error.
        gateway: ModelGateway | None
        if planned.gateway_factory is not None:
            gateway = planned.gateway_factory(repeat_index)
        elif planned.gateway is not None:
            gateway = planned.gateway
        else:
            gateway = provider
        if gateway is None:
            raise RuntimeError(f"no gateway for case {case.suite_name}::{case.case_name}")
        # A fresh resolver per case: AC-008 sequence state must not bleed across
        # concurrently-running cases.
        resolver = MockResolver(dict(planned.mocks))
        trace = await run_case(case, gateway, resolver, invoker=invoker)
        # Price the trace BEFORE assertions so cost_under (DF-207) can read it.
        if price is not None:
            trace = price(trace, case)
        # Then grade any llm_judge assertions, attaching verdicts before evaluation
        # (ARCHITECTURE §4.4). Uses the case's own gateway → cassette-backed for free.
        if judge is not None:
            trace = await judge(trace, case, gateway)
        assertions = _evaluate(case.expect, trace)
        passed = all(a.passed for a in assertions)
        return CaseResult(case.suite_name, case.case_name, trace, assertions, passed)
    except asyncio.CancelledError:
        raise  # fail-fast cancellation must propagate, never be swallowed as a result
    except Exception as exc:  # noqa: BLE001 - one case's failure must not abort the run
        return CaseResult(case.suite_name, case.case_name, None, [], False, error=repr(exc))


def _aggregate(case: ResolvedCase, reps: list[CaseResult]) -> CaseResult:
    """Fold the N repetition results of one case into a single CaseResult. For
    `repeat: 1` this returns the sole result unchanged — the common case takes no repeat
    code path in its output. For `repeat: N` the case passes iff the pass rate meets
    `require_pass_rate`, and `trace`/`assertions` carry the first failing repetition
    (what a reader wants to see) so the terminal's failing-trace view still works."""
    if case.repeat == 1:
        return reps[0]
    repetitions = [Repetition(r.trace, r.assertions, r.passed, r.error) for r in reps]
    passes = sum(r.passed for r in reps)
    rate = passes / len(reps)
    representative = next((r for r in reps if not r.passed), reps[0])
    return CaseResult(
        suite_name=reps[0].suite_name,
        case_name=reps[0].case_name,
        trace=representative.trace,
        assertions=representative.assertions,
        passed=rate >= case.require_pass_rate,
        error=representative.error,
        repetitions=repetitions,
        require_pass_rate=case.require_pass_rate,
    )


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
    provider: ModelGateway | None = None,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    fail_fast: bool = False,
    on_progress: ProgressCallback | None = None,
    price: PriceTrace | None = None,
    invoker: ToolInvoker | None = None,
    judge: JudgeTrace | None = None,
) -> RunResult:
    """Run every case concurrently (bounded to `concurrency`) and return results in
    spec order regardless of completion order.

    `provider` is the run-level default gateway; a case that carries its own
    `PlannedCase.gateway` uses that instead (AC-016). A case with neither errors in
    isolation.

    `fail_fast`: on the first case that does not pass, cancel every in-flight case
    and return only the results that already completed, with `complete=False`. A
    partial run is never presented as a full one."""
    cases = [pc for suite in suites for pc in suite.cases]
    # Each case contributes `repeat` units to the SAME flat pool, so N repetitions run
    # under the one worker set (not a nested pool) and the global concurrency bound spans
    # all repetitions of all cases. `repeat: 1` contributes exactly one unit → the v0.2
    # shape. A unit is just a case position; workers pull unit indices from one iterator.
    units: list[tuple[int, int]] = []
    for pos, pc in enumerate(cases):
        units.extend((pos, r) for r in range(pc.case.repeat))
    rep_slots: list[list[CaseResult | None]] = [[None] * pc.case.repeat for pc in cases]
    rep_filled = [0] * len(cases)
    case_results: list[CaseResult | None] = [None] * len(cases)

    pending = iter(range(len(units)))
    workers: list[asyncio.Task[None]] = []

    async def worker() -> None:
        for ui in pending:
            pos, repeat_index = units[ui]
            rep = await _process_case(
                cases[pos], provider, price, invoker, judge, repeat_index
            )
            # The repeat index IS the slot, so a repetition's result lands deterministically
            # (not in completion order) and its cassette key matches its slot. No await
            # between here and the aggregate check → bookkeeping is atomic per worker step.
            rep_slots[pos][repeat_index] = rep
            rep_filled[pos] += 1
            if rep_filled[pos] < cases[pos].case.repeat:
                continue  # more repetitions of this case still to run
            done = [r for r in rep_slots[pos] if r is not None]
            result = _aggregate(cases[pos].case, done)
            case_results[pos] = result
            if on_progress is not None:  # once per fully-completed case, as in v0.2
                on_progress(result)
            if fail_fast and not result.passed:
                for other in workers:
                    if other is not asyncio.current_task():
                        other.cancel()  # in-flight units end with no result → dropped
                return

    n_workers = min(concurrency, len(units))
    workers = [asyncio.create_task(worker()) for _ in range(n_workers)]
    # return_exceptions swallows the CancelledError raised in cancelled workers.
    await asyncio.gather(*workers, return_exceptions=True)

    return RunResult(_group(suites, case_results),
                     complete=all(r is not None for r in case_results))

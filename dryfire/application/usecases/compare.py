"""`compare` — run one suite across N models (or prompt variants) and matrix the results.

This is **orchestration over `run_suites`, not a second runner** (SPEC §9): it calls the
existing runner once per label and folds the `RunResult`s into columns. The use case is
pure and injected — it takes a `run_one(label)` coroutine so tests drive it with a fake
and the application layer never touches an adapter.

Per column: pass rate, total cost, mean latency, mean turn count — the numbers that
answer *"is the cheaper model good enough?"*. A label whose run raises (auth error,
unknown model surfacing during planning) becomes an isolated **failed column**; the rest
of the matrix still completes and reports (SPEC §9 — a failing model is not an aborted
run). Column order always follows request order, never completion order.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from dryfire.application.scheduler import RunResult


@dataclass(frozen=True)
class ColumnMetrics:
    """One model/prompt column, summarised. `total_cost_usd` is None when nothing could
    be priced — never a fabricated $0.0000."""

    cases: int
    pass_rate: float
    total_cost_usd: float | None
    mean_latency_ms: float
    mean_turns: float


@dataclass(frozen=True)
class CompareColumn:
    """One axis value's result: either a completed `run` (+ metrics) or an `error`."""

    label: str
    run: RunResult | None
    error: str | None
    metrics: ColumnMetrics | None


@dataclass(frozen=True)
class CompareResult:
    """The matrix: the axis being varied (`model` | `prompt`) and its columns in the
    order the user requested them."""

    axis: str
    columns: list[CompareColumn]


def column_metrics(run: RunResult) -> ColumnMetrics:
    """Summarise a run into one column. Latency is the summed per-turn model latency per
    case (the same figure `latency_under_ms` uses); cost sums the priced cases only."""
    cases = [c for suite in run.suites for c in suite.cases]
    n = len(cases)
    if n == 0:
        return ColumnMetrics(0, 0.0, None, 0.0, 0.0)
    passed = sum(1 for c in cases if c.passed)
    traced = [c.trace for c in cases if c.trace is not None]
    costs = [t.total_cost_usd for t in traced if t.total_cost_usd is not None]
    latencies = [sum(turn.response.latency_ms for turn in t.turns) for t in traced]
    turns = [len(t.turns) for t in traced]
    return ColumnMetrics(
        cases=n,
        pass_rate=passed / n,
        total_cost_usd=sum(costs) if costs else None,
        mean_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
        mean_turns=(sum(turns) / len(turns)) if turns else 0.0,
    )


async def run_compare(
    axis: str, labels: list[str], run_one: Callable[[str], Awaitable[RunResult]]
) -> CompareResult:
    """Run `run_one` for each label in order, isolating a raised run into a failed
    column. Sequential by design: columns are independent and the cost estimate has
    already been confirmed, so there is no benefit to racing them (and running them one
    at a time keeps the global concurrency bound meaningful per column)."""
    columns: list[CompareColumn] = []
    for label in labels:
        try:
            run = await run_one(label)
        except Exception as exc:  # noqa: BLE001 - a failing model is a failed column, not an abort
            columns.append(CompareColumn(label, run=None, error=repr(exc), metrics=None))
            continue
        columns.append(CompareColumn(label, run=run, error=None, metrics=column_metrics(run)))
    return CompareResult(axis=axis, columns=columns)


def estimate_runs(*, labels: int, case_runs: int) -> int:
    """Total case-executions a compare will perform: labels × the per-label case-runs
    (already summed over each case's `repeat`). Precise — the confirmation gate is built
    on this, not on a guessed token count."""
    return labels * case_runs

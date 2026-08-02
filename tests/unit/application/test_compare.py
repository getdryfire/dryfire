"""DF-307 — `compare` execution: orchestration OVER run_suites, not a second runner.

The use case is pure and injected: it takes a list of labels (models or prompt variants)
and a `run_one(label)` coroutine, runs each, and folds the results into a matrix — per
column: pass rate, total cost, mean latency, mean turns. A label whose run raises is an
isolated **failed column**; the others still complete and report.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.application.usecases.compare import (
    CompareResult,
    column_metrics,
    estimate_runs,
    run_compare,
)
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.trace import Trace, Turn


def _trace(*, turns: int, latency: int, cost: float | None) -> Trace:
    turn_list = [
        Turn(index=i, request_messages=[],
             response=ModelResponse(text="x", tool_calls=[], stop_reason="end_turn",
                                    usage=Usage(input_tokens=1, output_tokens=1),
                                    latency_ms=latency, raw={}),
             tool_results=[])
        for i in range(turns)
    ]
    return Trace(case_name="c", suite_name="s", turns=turn_list, final_text="x",
                 termination="end_turn", total_usage=Usage(input_tokens=1, output_tokens=1),
                 total_cost_usd=cost, duration_ms=latency * turns)


def _run(*, passed: list[bool], turns: int = 2, latency: int = 10,
         cost: float | None = 0.01) -> RunResult:
    cases = [
        CaseResult(suite_name="s", case_name=f"c{i}",
                   trace=_trace(turns=turns, latency=latency, cost=cost),
                   assertions=[], passed=p)
        for i, p in enumerate(passed)
    ]
    return RunResult(suites=[SuiteResult(name="s", path=Path("s.eval.yaml"), cases=cases)])


# -- column metrics ---------------------------------------------------------


def test_column_metrics_summarise_a_run() -> None:
    m = column_metrics(_run(passed=[True, True, True, False], turns=2, latency=10, cost=0.01))
    assert m.cases == 4
    assert m.pass_rate == 0.75
    assert m.total_cost_usd is not None and abs(m.total_cost_usd - 0.04) < 1e-9
    assert m.mean_turns == 2.0
    assert m.mean_latency_ms == 20.0  # 2 turns × 10ms per case


def test_unknown_cost_is_none_not_zero() -> None:
    m = column_metrics(_run(passed=[True], cost=None))
    assert m.total_cost_usd is None  # never a fabricated $0.0000


# -- orchestration: a matrix, with failed columns isolated ------------------


def test_three_models_five_cases_produce_a_stable_matrix() -> None:
    async def run_one(label: str) -> RunResult:
        return _run(passed=[True] * 5)

    result = asyncio.run(run_compare("model", ["a", "b", "c"], run_one))
    assert isinstance(result, CompareResult)
    assert [col.label for col in result.columns] == ["a", "b", "c"]  # stable order
    assert all(col.metrics is not None and col.metrics.cases == 5 for col in result.columns)


def test_a_failing_model_is_a_failed_column_others_complete() -> None:
    async def run_one(label: str) -> RunResult:
        if label == "b":
            raise RuntimeError("unknown model 'b'")
        return _run(passed=[True, True])

    result = asyncio.run(run_compare("model", ["a", "b", "c"], run_one))
    by = {col.label: col for col in result.columns}
    assert by["b"].run is None and by["b"].error is not None and "unknown model" in by["b"].error
    assert by["b"].metrics is None
    assert by["a"].metrics is not None and by["c"].metrics is not None  # others completed


def test_columns_keep_request_order_even_when_runs_finish_out_of_order() -> None:
    async def run_one(label: str) -> RunResult:
        await asyncio.sleep(0.01 if label == "a" else 0.0)  # 'a' finishes last
        return _run(passed=[True])

    result = asyncio.run(run_compare("model", ["a", "b", "c"], run_one))
    assert [col.label for col in result.columns] == ["a", "b", "c"]


# -- pre-execution run estimate ---------------------------------------------


def test_estimate_runs_multiplies_labels_by_case_runs() -> None:
    # 3 labels × 10 case-runs per label (e.g. 5 cases × repeat 2) = 30 runs
    assert estimate_runs(labels=3, case_runs=10) == 30

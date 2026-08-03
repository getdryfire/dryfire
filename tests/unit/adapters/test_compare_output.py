"""DF-308 — the compare matrix reporter (the screenshot artifact, SPEC §9)."""

from __future__ import annotations

import re
from pathlib import Path

from dryfire.adapters.driven.reporting.compare_terminal import render_compare
from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.application.usecases.compare import (
    CompareColumn,
    CompareResult,
    column_metrics,
)
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.trace import Trace, Turn

_GOLDEN = Path(__file__).parents[2] / "fixtures" / "expected_output"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _trace(latency: int = 100, cost: float | None = 0.01) -> Trace:
    turn = Turn(index=0, request_messages=[],
                response=ModelResponse(text="x", tool_calls=[], stop_reason="end_turn",
                                       usage=Usage(input_tokens=1, output_tokens=1),
                                       latency_ms=latency, raw={}),
                tool_results=[])
    return Trace(case_name="c", suite_name="s", turns=[turn], final_text="x",
                 termination="end_turn", total_usage=Usage(input_tokens=1, output_tokens=1),
                 total_cost_usd=cost, duration_ms=latency)


def _run(names: list[str], passes: list[bool], *, latency: int = 100,
         cost: float | None = 0.01) -> RunResult:
    cases = [CaseResult(suite_name="s", case_name=n, trace=_trace(latency, cost),
                        assertions=[], passed=p) for n, p in zip(names, passes, strict=True)]
    return RunResult(suites=[SuiteResult(name="s", path=Path("s.eval.yaml"), cases=cases)])


def _col(label: str, run: RunResult | None) -> CompareColumn:
    return CompareColumn(label, run, None if run else "boom",
                         column_metrics(run) if run else None)


_NAMES = ["greets", "refunds_gracefully", "escalates", "handles_edge", "closes_ticket"]


def _matrix_3x5() -> CompareResult:
    return CompareResult("model", [
        _col("opus", _run(_NAMES, [True, True, False, True, True], latency=850, cost=0.01)),
        _col("haiku", _run(_NAMES, [True, False, False, False, True], latency=300, cost=0.002)),
        _col("sonnet", _run(_NAMES, [True, True, False, False, True], latency=820, cost=0.0098)),
    ])


def test_golden_3x5_matrix_with_two_disagreements() -> None:
    rendered = render_compare(_matrix_3x5(), color=False)
    expected = (_GOLDEN / "compare_3x5.txt").read_text(encoding="utf-8")
    assert rendered == expected


def test_disagreeing_rows_are_distinct_by_character_not_only_colour() -> None:
    lines = render_compare(_matrix_3x5(), color=False).splitlines()
    disagree = [ln for ln in lines if ln.startswith("~")]
    uniform = [ln for ln in lines if "greets" in ln or "escalates" in ln or "closes_ticket" in ln]
    assert len(disagree) == 2  # exactly the two disagreement rows carry the ~ marker
    assert all(not ln.startswith("~") for ln in uniform)
    # The distinction is a real character (~ and a ✗ among ✓), not an ANSI code.
    refunds = next(ln for ln in disagree if "refunds" in ln)
    assert "✓" in refunds and "✗" in refunds


def test_non_tty_output_has_zero_ansi() -> None:
    assert _ANSI.search(render_compare(_matrix_3x5(), color=False)) is None


def test_colour_output_still_marks_disagreements_with_the_character() -> None:
    coloured = render_compare(_matrix_3x5(), color=True)
    assert _ANSI.search(coloured) is not None  # colour present
    # The ~ marker survives even with colour — grep-able regardless of ANSI.
    assert any(_ANSI.sub("", ln).startswith("~") for ln in coloured.splitlines())


def test_unknown_cost_renders_dash_not_zero() -> None:
    run = _run(["a"], [True], cost=None)
    out = render_compare(CompareResult("model", [_col("m", run)]), color=False)
    assert "—" in out
    assert "$0.0000" not in out


def test_failed_column_shows_failed_and_dotted_cells() -> None:
    good = _run(_NAMES[:2], [True, True])
    out = render_compare(CompareResult("model", [_col("ok", good), _col("boom", None)]),
                         color=False)
    assert "FAILED" in out  # the failed column's summary
    assert "·" in out       # its cells


def test_six_models_all_show_and_stay_aligned() -> None:
    cols = [_col(f"m{i}", _run(["a", "b"], [True, i % 2 == 0])) for i in range(6)]
    out = render_compare(CompareResult("model", cols), color=False)
    for i in range(6):
        assert f"m{i}" in out
    assert "not shown" not in out  # 6 ≤ the column budget → nothing dropped
    # Every body row has the same visual width (aligned columns).
    body = [ln for ln in out.splitlines() if ln and "─" not in ln and "compare by" not in ln]
    widths = {len(ln) for ln in body}
    assert len(widths) == 1


def test_more_than_the_budget_truncates_with_a_note() -> None:
    cols = [_col(f"m{i}", _run(["a"], [True])) for i in range(10)]
    out = render_compare(CompareResult("model", cols), color=False)
    assert "not shown" in out and "--json-out" in out
    assert "m9" not in out  # beyond the budget, dropped


def test_summary_pass_rate_matches_the_cells() -> None:
    out = render_compare(_matrix_3x5(), color=False)
    # opus passes 4 of 5 cells → 80%; haiku 2 of 5 → 40%; sonnet 3 of 5 → 60%.
    summary = next(ln for ln in out.splitlines() if "pass rate" in ln)
    assert "80%" in summary and "40%" in summary and "60%" in summary

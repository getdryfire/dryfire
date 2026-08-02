"""DF-304 — judge cost is a separate channel (SPEC §9 v0.3, EPIC-003).

The whole reason this ticket exists: judging must never inflate a case's cost, or
`cost_under` (DF-207) starts failing for reasons unrelated to the agent under test and
the user debugs the wrong thing. Judge usage and cost live on their own `Trace` fields,
the budget assertions stay blind to them, the terminal shows them on their own line
(never merged into the case line, never `$0.0000` when no judge ran), and the JSON
artifact keeps the two channels apart.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from dryfire import composition
from dryfire.adapters.driven.reporting.json_sink import render_run
from dryfire.adapters.driven.reporting.terminal import render_report
from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.domain.assertions.registry import build
from dryfire.domain.judging.keys import judge_key
from dryfire.domain.judging.rubric import Rubric
from dryfire.domain.judging.verdict import JudgeVerdict
from dryfire.domain.model.case import ResolvedCase
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.trace import Trace

_AT = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)
_MODEL = "claude-opus-4-8"


def _trace(**over: object) -> Trace:
    base: dict[str, object] = dict(
        case_name="c", suite_name="s", turns=[], final_text="done", termination="end_turn",
        total_usage=Usage(input_tokens=100, output_tokens=50), total_cost_usd=0.001,
        duration_ms=1000, model=_MODEL,
    )
    base.update(over)
    return Trace(**base)  # type: ignore[arg-type]


# -- The regression: budget assertions stay blind to judge cost -------------


def test_cost_under_ignores_judge_cost() -> None:
    # Case cost is under the limit; judge cost alone would blow past it. cost_under
    # must pass — this is the whole point of the ticket.
    trace = _trace(total_cost_usd=0.001, judge_cost=1.0)
    result = build("cost_under", 0.01).evaluate(trace)
    assert result.passed
    assert "1.0" not in result.message  # judge cost is nowhere in the case-cost message


def test_latency_under_ms_ignores_judge() -> None:
    # Judge calls are not turns, so summed per-turn model latency never includes them.
    trace = _trace(judge_cost=1.0, judge_usage=Usage(input_tokens=9999, output_tokens=9999))
    result = build("latency_under_ms", 500).evaluate(trace)
    assert result.passed  # no turns → 0ms latency, judge activity irrelevant


def test_trace_defaults_have_no_judge_channel() -> None:
    trace = _trace()
    assert trace.judge_usage == Usage(input_tokens=0, output_tokens=0)
    assert trace.judge_cost is None


# -- Enrichment tracks the judge channel separately -------------------------


class _JudgeGateway:
    name = "anthropic"

    async def complete(self, request: object) -> ModelResponse:
        return ModelResponse(
            text='{"score": 0.9, "reasoning": "good"}', tool_calls=[], stop_reason="end_turn",
            usage=Usage(input_tokens=200, output_tokens=20), latency_ms=5,
            raw={"model": "claude-opus-4-8-20260115"},
        )

    def is_retryable(self, exc: Exception) -> bool:
        return False


def _judged_case() -> ResolvedCase:
    return ResolvedCase(
        suite_name="s", case_name="c", suite_path=Path("s.eval.yaml"),
        provider="anthropic", model=_MODEL, max_turns=4, temperature=0.0,
        on_unmocked="error", system=None, input="hi",
        expect=[{"llm_judge": {"rubric": "Was it good?"}}],
    )


def _enrich(case: ResolvedCase, trace: Trace) -> Trace:
    """Drive the judge enrichment callback (a coroutine wrapper keeps mypy --strict
    happy: asyncio.run wants a Coroutine, the JudgeTrace type is a plain Awaitable)."""
    judge = composition._make_judge()

    async def go() -> Trace:
        return await judge(trace, case, _JudgeGateway())

    return asyncio.run(go())


def test_enrichment_keeps_case_cost_untouched_and_prices_judge_separately() -> None:
    before = _trace(total_cost_usd=0.001, total_usage=Usage(input_tokens=100, output_tokens=50))
    after = _enrich(_judged_case(), before)

    # Case channel is byte-for-byte untouched by judging.
    assert after.total_cost_usd == 0.001
    assert after.total_usage == Usage(input_tokens=100, output_tokens=50)
    # Judge channel is populated and priced from the judge's own tokens.
    assert after.judge_usage == Usage(input_tokens=200, output_tokens=20)
    assert after.judge_cost is not None and after.judge_cost > 0
    assert after.judge_cost != after.total_cost_usd  # genuinely separate numbers


def test_structural_only_case_gets_no_judge_channel() -> None:
    structural = ResolvedCase(
        suite_name="s", case_name="c", suite_path=Path("s.eval.yaml"),
        provider="anthropic", model=_MODEL, max_turns=4, temperature=0.0,
        on_unmocked="error", system=None, input="hi", expect=[{"calls_tool": "lookup"}],
    )
    after = _enrich(structural, _trace())
    assert after.judge_cost is None
    assert after.judge_usage == Usage(input_tokens=0, output_tokens=0)


# -- Reporting: separate line, never merged, never a phantom $0.0000 --------


def _run(*, judged: bool) -> RunResult:
    if judged:
        verdict = JudgeVerdict.from_score(
            score=0.9, reasoning="good", rubric=Rubric(text="Was it good?"),
            judge_model=_MODEL, judge_model_version="v1",
        )
        key = judge_key(model=_MODEL, rubric_hash=Rubric(text="Was it good?").hash())
        trace = _trace(judge_verdicts={key: verdict},
                       judge_usage=Usage(input_tokens=200, output_tokens=20), judge_cost=0.0011)
    else:
        trace = _trace()
    case = CaseResult(suite_name="s", case_name="c", trace=trace, assertions=[], passed=True)
    return RunResult(suites=[SuiteResult(name="s", path=Path("s.eval.yaml"), cases=[case])])


def test_structural_only_run_shows_no_judge_line() -> None:
    report = render_report(_run(judged=False))
    assert "judge" not in report.lower()  # not even "$0.0000" for a feature not used


def test_terminal_shows_judge_cost_on_its_own_line() -> None:
    report = render_report(_run(judged=True))
    lines = report.splitlines()
    judge_lines = [ln for ln in lines if "judge" in ln.lower()]
    assert len(judge_lines) == 1
    assert "0.0011" in judge_lines[0]
    # The case line shows the CASE cost, never the judge cost merged in.
    case_lines = [ln for ln in lines if "::c" in ln or ln.strip().startswith("✓")]
    assert all("0.0011" not in ln for ln in case_lines)


def test_json_artifact_separates_the_two_channels() -> None:
    doc = json.loads(render_run(_run(judged=True), generated_at=_AT))
    trace = doc["suites"][0]["cases"][0]["trace"]
    assert trace["total_cost_usd"] == 0.001
    assert trace["judge_cost"] == 0.0011
    assert trace["judge_usage"]["input_tokens"] == 200
    assert trace["total_usage"] != trace["judge_usage"]

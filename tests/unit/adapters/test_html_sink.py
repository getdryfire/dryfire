"""DF-309 — the self-contained HTML report sink (SPEC §9)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from dryfire import composition
from dryfire.adapters.driven.reporting.html_sink import (
    render_compare_html,
    render_run_html,
)
from dryfire.adapters.driven.reporting.json_sink import deserialize_run, render_run
from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.application.usecases.compare import CompareColumn, CompareResult, column_metrics
from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.judging.keys import judge_key
from dryfire.domain.judging.rubric import Rubric
from dryfire.domain.judging.verdict import JudgeVerdict
from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall, ToolResult
from dryfire.domain.model.trace import Trace, Turn

_AT = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)
# Any reference that would make the browser reach the network fails the air-gap test.
_EXTERNAL = re.compile(r"https?://|<script|<link\b|@import|src\s*=|url\(", re.IGNORECASE)


def _trace(*, judged: bool = False, model: str = "claude-opus-4-8") -> Trace:
    call = ToolCall(id="c0", name="issue_refund", arguments={"amount": 780})
    turn = Turn(index=0, request_messages=[Message(role="user", content="refund me")],
                response=ModelResponse(text=None, tool_calls=[call], stop_reason="tool_use",
                                       usage=Usage(input_tokens=5, output_tokens=3),
                                       latency_ms=42, raw={}),
                tool_results=[ToolResult(call_id="c0", content="ok", is_error=False)])
    verdicts = {}
    if judged:
        rubric = Rubric(text="Was the agent polite?")
        verdicts[judge_key(model=model, rubric_hash=rubric.hash())] = JudgeVerdict.from_score(
            score=0.3, reasoning="the agent was curt and did not apologise",
            rubric=rubric, judge_model=model, judge_model_version="v1",
        )
    return Trace(case_name="c", suite_name="s", turns=[turn], final_text="done",
                 termination="end_turn", total_usage=Usage(input_tokens=5, output_tokens=3),
                 total_cost_usd=0.001, duration_ms=42, model=model, judge_verdicts=verdicts)


def _case(name: str, passed: bool, *, judged: bool = False) -> CaseResult:
    a = AssertionResult(kind="calls_tool", description="calls_tool: issue_refund", passed=passed,
                        message="" if passed else "issue_refund was never called",
                        actual="lookup → (end_turn)")
    return CaseResult(suite_name="s", case_name=name, trace=_trace(judged=judged),
                      assertions=[a], passed=passed)


def _run(cases: list[CaseResult]) -> RunResult:
    return RunResult(suites=[SuiteResult(name="refunds", path=Path("s.eval.yaml"), cases=cases)])


# -- self-contained + structure ---------------------------------------------


def test_html_is_self_contained_no_network_references() -> None:
    html = render_run_html(_run([_case("ok", True), _case("bad", False)]), generated_at=_AT)
    assert _EXTERNAL.search(html) is None  # no CDN/script/link/external src → opens from file://
    assert html.startswith("<!doctype html>")
    assert "<style>" in html  # CSS inlined


def test_failing_case_is_expandable_and_open_passing_is_collapsed() -> None:
    html = render_run_html(_run([_case("ok", True), _case("bad", False)]), generated_at=_AT)
    # Native <details>/<summary> — expandable with NO JavaScript.
    assert "<details open>" in html   # the failing case starts expanded
    assert "<details>" in html        # the passing case collapsed
    assert html.count("<details") == 2


def test_failure_view_carries_trajectory_args_and_message() -> None:
    html = render_run_html(_run([_case("bad", False)]), generated_at=_AT)
    assert "issue_refund" in html                       # the tool call
    assert "780" in html                                # its arguments
    assert "issue_refund was never called" in html      # the assertion message


def test_judge_reasoning_is_shown_when_present() -> None:
    html = render_run_html(_run([_case("bad", False, judged=True)]), generated_at=_AT)
    assert "llm_judge" in html
    assert "the agent was curt and did not apologise" in html  # judge reasoning


def test_html_escapes_dynamic_text() -> None:
    html = render_run_html(_run([_case("<script>alert(1)</script>", False)]), generated_at=_AT)
    assert "<script>alert(1)" not in html      # the case name is escaped
    assert "&lt;script&gt;" in html


# -- compare matrix ---------------------------------------------------------


def test_compare_html_renders_a_matrix_with_disagreements() -> None:
    names = ["a", "b"]
    opus = _run([_case("a", True), _case("b", True)])
    haiku = _run([_case("a", True), _case("b", False)])  # disagrees on b
    result = CompareResult("model", [
        CompareColumn("opus", opus, None, column_metrics(opus)),
        CompareColumn("haiku", haiku, None, column_metrics(haiku)),
    ])
    html = render_compare_html(result, generated_at=_AT)
    assert _EXTERNAL.search(html) is None
    assert "<table>" in html and "opus" in html and "haiku" in html
    assert 'class="disagree"' in html  # the row where the models disagree
    assert names[1] in html


# -- round-trips from the JSON artifact, no re-execution --------------------


def test_report_regenerates_from_a_json_artifact(tmp_path: Path) -> None:
    run = _run([_case("ok", True), _case("bad", False)])
    artifact = tmp_path / "run.json"
    artifact.write_text(render_run(run, generated_at=_AT), encoding="utf-8")

    import io
    out, err = io.StringIO(), io.StringIO()
    code = composition.report(str(artifact), out=out, err=err, now=_AT)
    assert code == composition.EXIT_OK
    assert out.getvalue().startswith("<!doctype html>")
    assert "bad" in out.getvalue()


def test_report_round_trip_matches_direct_render() -> None:
    run = _run([_case("ok", True), _case("bad", False)])
    doc = json.loads(render_run(run, generated_at=_AT))
    from_json = render_run_html(deserialize_run(doc), generated_at=_AT)
    direct = render_run_html(run, generated_at=_AT)
    assert from_json == direct  # the artifact is sufficient to reproduce the report


# -- size budget ------------------------------------------------------------


def test_fifty_case_report_is_under_500kb() -> None:
    cases = [_case(f"case_{i:02d}", i % 3 != 0, judged=True) for i in range(50)]
    html = render_run_html(_run(cases), generated_at=_AT)
    assert len(html.encode("utf-8")) < 500_000

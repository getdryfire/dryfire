"""AC-013 — the terminal reporter (SPEC §7.2). Golden-pinned layout; zero ANSI
off a TTY; honest `—` for unknown cost; non-end_turn terminations surfaced;
long argument values truncated while the trajectory line stays whole."""

import io
import json
from pathlib import Path

import pytest

from dryfire.adapters.driven.reporting.terminal import (
    TerminalReporter,
    render_report,
    resolve_color,
)
from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.trace import TerminationReason, Trace, Turn

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "expected_output"


def _trace(
    *,
    turns: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float | None = None,
    duration_ms: int = 0,
    termination: TerminationReason = "end_turn",
) -> Trace:
    turn_objs = [
        Turn(
            index=i,
            request_messages=[],
            response=ModelResponse(
                text=None,
                tool_calls=[],
                stop_reason="end_turn",
                usage=Usage(input_tokens=0, output_tokens=0),
                latency_ms=0,
                raw={},
            ),
            tool_results=[],
        )
        for i in range(turns)
    ]
    return Trace(
        case_name="c",
        suite_name="s",
        turns=turn_objs,
        final_text=None,
        termination=termination,
        total_usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        total_cost_usd=cost,
        duration_ms=duration_ms,
    )


def _case(
    name: str, *, passed: bool, trace: Trace | None, assertions: list[AssertionResult]
) -> CaseResult:
    return CaseResult(
        suite_name="refund_agent",
        case_name=name,
        trace=trace,
        assertions=assertions,
        passed=passed,
    )


def _run(*cases: CaseResult, name: str = "refund_agent", path: str = "evals/refund_agent.eval.yaml",
         complete: bool = True) -> RunResult:
    return RunResult(suites=[SuiteResult(name=name, path=Path(path), cases=list(cases))],
                     complete=complete)


# -- Golden §7.2 layout -----------------------------------------------------


def _refund_run() -> RunResult:
    ok = _case(
        "escalates_refund_over_limit",
        passed=True,
        trace=_trace(turns=3, input_tokens=1000, output_tokens=204, cost=0.0041, duration_ms=2100),
        assertions=[],
    )
    # A failing calls_tool(count) — trajectory on `actual`, reason as continuation
    # (AC-011 / SPEC §6). This is the real v0.1 machinery, not §7.2's v0.2 sample.
    failing = AssertionResult(
        kind="calls_tool",
        description="calls_tool: issue_refund (count 2)",
        passed=False,
        message="called 1 time(s)",
        expected="issue_refund called exactly 2 time(s)",
        actual="lookup_order → issue_refund → (end_turn)",
    )
    bad = _case(
        "recovers_from_tool_error",
        passed=False,
        trace=_trace(turns=5, input_tokens=2600, output_tokens=290, cost=0.0096, duration_ms=4700),
        assertions=[failing],
    )
    return _run(ok, bad)


def test_golden_two_case_run_matches_fixture() -> None:
    report = render_report(_refund_run(), color=False)
    expected = (_FIXTURES / "refund_agent.txt").read_text(encoding="utf-8")
    assert report == expected


# -- TTY degradation / colour ----------------------------------------------


def test_plain_output_has_zero_ansi() -> None:
    raw = render_report(_refund_run(), color=False).encode("utf-8")
    assert b"\x1b" not in raw


def test_color_output_wraps_glyphs_in_ansi() -> None:
    raw = render_report(_refund_run(), color=True)
    assert "\x1b[32m✓\x1b[0m" in raw  # green pass glyph
    assert "\x1b[31m✗\x1b[0m" in raw  # red fail glyph


def test_no_color_env_forces_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert resolve_color(io.StringIO()) is False


def test_no_color_flag_forces_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert resolve_color(io.StringIO(), no_color=True) is False


def test_non_tty_stream_is_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert resolve_color(io.StringIO()) is False  # StringIO is not a terminal


def test_reporter_writes_plain_to_non_tty() -> None:
    buffer = io.StringIO()
    TerminalReporter().report(_refund_run(), buffer)
    assert "\x1b" not in buffer.getvalue()
    assert "refund_agent" in buffer.getvalue()


# -- Individual acceptance rows --------------------------------------------


def test_unknown_cost_renders_dash_not_zero() -> None:
    case = _case("no_cost", passed=True, trace=_trace(turns=1, cost=None), assertions=[])
    report = render_report(_run(case), color=False)
    assert "—" in report
    assert "$0.0000" not in report


def test_non_end_turn_termination_is_on_the_case_line() -> None:
    case = _case(
        "looped",
        passed=False,
        trace=_trace(turns=10, termination="max_turns_exceeded", duration_ms=1000),
        assertions=[],
    )
    report = render_report(_run(case), color=False)
    case_line = next(ln for ln in report.splitlines() if "looped" in ln)
    assert "max_turns_exceeded" in case_line


def test_long_tool_args_truncate_but_trajectory_stays_whole() -> None:
    trajectory = "lookup_order → issue_refund → (end_turn)"
    big = json.dumps({"payload": "x" * 200})
    failing = AssertionResult(
        kind="tool_args",
        description="tool_args: issue_refund",
        passed=False,
        message=f"actual arguments: {big}",
        expected=f"arguments matching {big}",
        actual=trajectory,
    )
    case = _case("mismatch", passed=False, trace=_trace(turns=2), assertions=[failing])
    report = render_report(_run(case), color=False)

    assert "… (truncated)" in report  # the long args line was cut
    assert "x" * 200 not in report  # the full 200-char blob is gone
    assert trajectory in report  # the trajectory line is intact
    # No non-trajectory line survives at full width.
    assert all(len(line) < 160 or trajectory in line for line in report.splitlines())


def test_summary_totals_equal_the_sum_of_case_values() -> None:
    cases = [
        _case(f"c{i}", passed=(i % 2 == 0),
              trace=_trace(turns=1, cost=round(0.001 * (i + 1), 4), duration_ms=1000 * (i + 1)),
              assertions=[])
        for i in range(5)
    ]
    report = render_report(_run(*cases), color=False)
    summary = report.splitlines()[-1]

    passed = sum(1 for c in cases if c.passed)
    traces = [c.trace for c in cases if c.trace is not None]
    total_cost = sum(t.total_cost_usd for t in traces if t.total_cost_usd is not None)
    total_s = sum(t.duration_ms for t in traces) / 1000
    assert summary == (
        f"5 cases   {passed} passed   {5 - passed} failed   ${total_cost:.4f}   {total_s:.1f}s"
    )


def test_zero_case_run_reports_no_match_and_does_not_crash() -> None:
    assert render_report(RunResult(suites=[]), color=False) == "no cases matched\n"
    empty_suite = RunResult(suites=[SuiteResult(name="s", path=Path("s.yaml"), cases=[])])
    assert render_report(empty_suite, color=False) == "no cases matched\n"


def test_incomplete_run_is_not_shown_as_full() -> None:
    case = _case("first", passed=False, trace=_trace(turns=1), assertions=[])
    report = render_report(_run(case, complete=False), color=False)
    assert "incomplete" in report

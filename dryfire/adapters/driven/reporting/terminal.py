"""Terminal reporter (SPEC §7.2) — the thing people screenshot.

`render_report` is a **pure** function: a `RunResult` in, the exact report text
out. It emits zero ANSI unless `color=True`, so the same code path produces the
CI-log output (a primary consumer) and the coloured TTY output. The layout is
byte-pinned by a golden fixture.

The reporter *formats*; it does not *compose* failure messages — those come from
`AssertionResult` via AC-011's `render_failure` (SPEC §6). The one thing the
reporter owns is display truncation of long argument values, and it never
truncates the trajectory line.
"""

from __future__ import annotations

import os
from typing import Any, TextIO

from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.assertions.trajectory import render_failure
from dryfire.domain.pass_rate import MIN_MEANINGFUL_REPEAT, wilson_interval

# Layout constants pinned against SPEC §7.2 (verified byte-for-byte).
_NAME_WIDTH = 36  # case name left-justified; metrics start at column 40
_FAILURE_INDENT = "      "  # 6 spaces — nests the AC-011 block under its case
_VALUE_LIMIT = 80  # truncate long argument values past this; trajectory is exempt

_PASS = "✓"
_FAIL = "✗"
_GREEN = "\x1b[32m"
_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"  # the disagreement (flaky) marker on a repeated case (DF-305)
_RESET = "\x1b[0m"


def _glyph(passed: bool, *, color: bool) -> str:
    mark = _PASS if passed else _FAIL
    if not color:
        return mark
    return f"{_GREEN if passed else _RED}{mark}{_RESET}"


def _tokens(case: CaseResult) -> int:
    assert case.trace is not None
    usage = case.trace.total_usage
    return usage.input_tokens + usage.output_tokens


def _cost_str(cost: float | None) -> str:
    # An unknown cost is an honest blank, never a fabricated $0.0000 (SPEC §3.2).
    return "—" if cost is None else f"${cost:.4f}"


def _repeat_glyph(case: CaseResult, *, color: bool) -> str:
    """A disagreeing repeated case (0 < k < N) gets a distinct `~` — flakiness is the
    finding, and it must not read as a plain pass or fail (DF-305). A uniform repeated
    case (N/N or 0/N) keeps the normal pass/fail glyph."""
    disagreeing = case.passes not in (0, case.total)
    if not disagreeing:
        return _glyph(case.passed, color=color)
    return f"{_YELLOW}~{_RESET}" if color else "~"


def _repeat_annotation(case: CaseResult) -> str:
    """`k/N`, plus — only for a disagreeing case, where the uncertainty is
    decision-relevant — the Wilson 95% interval, plus a wide-interval warning below the
    recommended minimum N (SPIKE-007). Uniform and non-repeated cases stay terse."""
    passes, total = case.passes, case.total
    assert passes is not None and total is not None
    parts = [f"{passes}/{total}"]
    if passes not in (0, total):
        lo, hi = wilson_interval(passes, total)
        parts.append(f"95% CI {lo:.2f}–{hi:.2f}")
    if total < MIN_MEANINGFUL_REPEAT:
        parts.append(f"repeat<{MIN_MEANINGFUL_REPEAT}: wide interval")
    return "   ".join(parts)


def _case_line(case: CaseResult, *, color: bool) -> str:
    repeated = case.repetitions is not None
    glyph = _repeat_glyph(case, color=color) if repeated else _glyph(case.passed, color=color)
    name = case.case_name
    if case.trace is None:
        # A case that raised before producing a trace — surface the error, no metrics.
        detail = case.error or "errored before producing a trace"
        return f"  {glyph} {name:<{_NAME_WIDTH}}{detail}"
    trace = case.trace
    turns = len(trace.turns)
    duration = trace.duration_ms / 1000
    rate = f"{_repeat_annotation(case)}   " if repeated else ""
    line = (
        f"  {glyph} {name:<{_NAME_WIDTH}}{rate}"
        f"{turns} turns   {_tokens(case):,} tok   "
        f"{_cost_str(trace.total_cost_usd)}   {duration:.1f}s"
    )
    # A non-end_turn termination is surfaced on the case line, never hidden.
    if trace.termination != "end_turn":
        line += f"   {trace.termination}"
    # Cassette hits (DF-204) are shown only when present, so a normal run's output
    # is unchanged. The gateway flags each response it served from a cassette.
    cached = sum(1 for turn in trace.turns if turn.response.cache_hit)
    if cached:
        line += f"   ⚡{cached} cached"
    return line


def _truncate(value: Any) -> Any:
    text = str(value)
    if len(text) <= _VALUE_LIMIT:
        return value
    return text[:_VALUE_LIMIT] + "… (truncated)"


def _failure_block(result: AssertionResult) -> list[str]:
    # Truncate the long argument values (expected / message) but never `actual`,
    # which carries the trajectory line. render_failure owns the layout.
    display = result.model_copy(
        update={"expected": _truncate(result.expected), "message": _truncate(result.message)}
    )
    return [f"{_FAILURE_INDENT}{line}" for line in render_failure(display).split("\n")]


def _suite_block(suite: SuiteResult, *, color: bool) -> list[str]:
    lines = [f"{suite.name}  {suite.path}", ""]
    for case in suite.cases:
        lines.append(_case_line(case, color=color))
        if not case.passed:
            for result in case.assertions:
                if not result.passed:
                    lines.extend(_failure_block(result))
    return lines


def _summary_line(run: RunResult) -> str:
    cases = [case for suite in run.suites for case in suite.cases]
    total = len(cases)
    passed = sum(1 for c in cases if c.passed)
    failed = total - passed
    costs = [
        c.trace.total_cost_usd
        for c in cases
        if c.trace and c.trace.total_cost_usd is not None
    ]
    total_cost = _cost_str(sum(costs) if costs else None)
    total_ms = sum(c.trace.duration_ms for c in cases if c.trace)
    return (
        f"{total} cases   {passed} passed   {failed} failed   "
        f"{total_cost}   {total_ms / 1000:.1f}s"
    )


def _judge_summary_line(run: RunResult) -> str | None:
    """A separate summary line for judge cost — never merged into the case totals
    (DF-304), and absent entirely when no judge ran (never a phantom $0.0000)."""
    traces = [c.trace for suite in run.suites for c in suite.cases if c.trace]
    if not any(t.judge_verdicts for t in traces):
        return None  # no judged assertion in the whole run → no line at all
    tokens = sum(t.judge_usage.input_tokens + t.judge_usage.output_tokens for t in traces)
    costs = [t.judge_cost for t in traces if t.judge_cost is not None]
    cost = _cost_str(sum(costs) if costs else None)
    return f"judge: {cost}   {tokens} tokens (reported separately)"


def render_report(run: RunResult, *, color: bool = False) -> str:
    """The full §7.2 report for a run. `color=False` emits zero ANSI (CI logs,
    non-TTY, NO_COLOR); `color=True` colours the pass/fail glyphs only."""
    cases = [case for suite in run.suites for case in suite.cases]
    if not cases:
        return "no cases matched\n"

    lines: list[str] = []
    for suite in run.suites:
        lines.extend(_suite_block(suite, color=color))
    lines.append("")
    if not run.complete:
        # Never present a partial (fail-fast) run as a full one.
        lines.append("run incomplete — stopped on first failure (--fail-fast)")
    lines.append(_summary_line(run))
    judge_line = _judge_summary_line(run)
    if judge_line is not None:
        lines.append(judge_line)
    return "\n".join(lines) + "\n"


def resolve_color(stream: TextIO, *, no_color: bool = False) -> bool:
    """Whether to colour output for `stream`. Honours `--no-color`, the `NO_COLOR`
    convention, and TTY detection (a non-terminal — e.g. a CI log or a pipe —
    never gets ANSI). Uses rich for the terminal check."""
    if no_color or "NO_COLOR" in os.environ:
        return False
    from rich.console import Console

    return Console(file=stream).is_terminal


class TerminalReporter:
    """Driven adapter that writes the §7.2 report to a stream. Composition (AC-015)
    wires it; it owns the colour policy so callers pass only `--no-color`."""

    def __init__(self, *, no_color: bool = False) -> None:
        self._no_color = no_color

    def report(self, run: RunResult, stream: TextIO) -> None:
        color = resolve_color(stream, no_color=self._no_color)
        stream.write(render_report(run, color=color))

"""JUnit XML reporter (SPEC §9 v0.2). Mapping settled empirically by SPIKE-005.

The verdict (SPIKE-005 Candidate A): suite → ``<testsuite>``, case → ``<testcase>``,
**one ``<failure>`` per failing case** with every failed assertion concatenated in the
failure **text body** — because XML attribute-value normalization collapses newlines
to spaces, so the multi-line trajectory block cannot live in ``message`` (a one-line
summary does). ``provider_error`` / ``unmocked_tool`` are ``<error>``, not ``<failure>``:
the case could not be *evaluated*, distinct from the agent behaving wrongly.

Like the JSON sink this is an event-sink module (no domain concern): ``render_junit``
returns the document for ``--reporter junit`` (stdout), ``write_junit`` is the atomic
file write for ``--junit-out`` (serialize fully, temp file + ``os.replace`` — a killed
run never leaves a truncated report). The loop, scheduler, and terminal reporter are
untouched (DF-209).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dryfire.application.scheduler import CaseResult, RunResult
from dryfire.domain.assertions.trajectory import render_failure, render_trajectory

# Terminations where the case could not be evaluated → <error>, not <failure>.
_ERROR_TERMINATIONS = frozenset({"provider_error", "unmocked_tool"})


def render_junit(run: RunResult, *, generated_at: datetime) -> str:
    """Serialize a run to JUnit XML text. Deterministic given the same
    ``generated_at`` (its only non-run input, used for the suite ``timestamp``)."""
    timestamp = _iso_z(generated_at)
    suite_blocks: list[str] = []
    run_tests = run_failures = run_errors = 0
    run_time = 0.0

    for suite in run.suites:
        case_blocks: list[str] = []
        s_tests = s_failures = s_errors = 0
        s_time = 0.0
        for case in suite.cases:
            kind, block, seconds = _render_case(case)
            s_tests += 1
            s_time += seconds
            if kind == "failure":
                s_failures += 1
            elif kind == "error":
                s_errors += 1
            case_blocks.append(block)
        suite_blocks.append(
            "\n".join([
                f'  <testsuite name="{_attr(suite.name)}" tests="{s_tests}" '
                f'failures="{s_failures}" errors="{s_errors}" time="{_secs(s_time)}" '
                f'timestamp="{timestamp}">',
                *case_blocks,
                "  </testsuite>",
            ])
        )
        run_tests += s_tests
        run_failures += s_failures
        run_errors += s_errors
        run_time += s_time

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuites name="dryfire" tests="{run_tests}" failures="{run_failures}" '
        f'errors="{run_errors}" time="{_secs(run_time)}">',
        *suite_blocks,
        "</testsuites>",
    ]
    return "\n".join(lines) + "\n"


def write_junit(run: RunResult, path: Path | str, *, generated_at: datetime) -> None:
    """Write the JUnit XML atomically: fully render first (a failure never touches
    the target), then temp file + ``os.replace`` in the target's directory."""
    content = render_junit(run, generated_at=generated_at)  # may raise → target untouched
    target = Path(path)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, prefix=f"{target.name}.", suffix=".tmp",
        delete=False,
    )
    try:
        with handle as tmp:
            tmp.write(content)
        os.replace(handle.name, target)  # atomic rename
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(handle.name)
        raise


# -- per-case rendering ------------------------------------------------------


def _render_case(case: CaseResult) -> tuple[str, str, float]:
    """Return ``(kind, xml_block, seconds)`` for one case. ``kind`` is
    ``pass`` | ``failure`` | ``error``."""
    seconds = 0.0 if case.trace is None else case.trace.duration_ms / 1000
    open_tag = (
        f'    <testcase name="{_attr(case.case_name)}" '
        f'classname="{_attr(case.suite_name)}" time="{_secs(seconds)}"'
    )
    kind = _classify(case)
    if kind == "pass":
        return kind, f"{open_tag}/>", seconds
    inner = _failure_element(case) if kind == "failure" else _error_element(case)
    block = "\n".join([f"{open_tag}>", f"      {inner}", "    </testcase>"])
    return kind, block, seconds


def _classify(case: CaseResult) -> str:
    if case.trace is not None and case.trace.termination in _ERROR_TERMINATIONS:
        return "error"
    if case.error is not None:  # an unexpected raise, isolated by the scheduler
        return "error"
    if not case.passed:
        return "failure"
    return "pass"


def _failure_element(case: CaseResult) -> str:
    failed = [a for a in case.assertions if not a.passed]
    body = _text("\n".join(render_failure(a) for a in failed))
    plural = "s" if len(failed) != 1 else ""
    summary = f"{len(failed)} assertion{plural} failed: " + "; ".join(a.description for a in failed)
    return f'<failure message="{_attr(summary)}" type="AssertionFailure">{body}</failure>'


def _error_element(case: CaseResult) -> str:
    trace = case.trace
    if trace is not None:
        detail = trace.error
        body_lines = [render_trajectory(trace)]
        if detail:
            body_lines.append(detail)
        body = _text("\n".join(body_lines))
        message = _oneline(detail) if detail else f"terminated: {trace.termination}"
        err_type: str = trace.termination
    else:  # scheduler-isolated raise (trace is None)
        body = _text(case.error or "")
        message = _oneline(case.error) if case.error else "error"
        err_type = "error"
    return f'<error message="{_attr(message)}" type="{_attr(err_type)}">{body}</error>'


# -- helpers -----------------------------------------------------------------


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _secs(seconds: float) -> str:
    return f"{seconds:.3f}"


def _text(value: str) -> str:
    """Escape element text — `→`/`✗` are legal UTF-8 and pass through unchanged."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _attr(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def _oneline(value: str) -> str:
    """Collapse a multi-line detail to one line for a ``message`` attribute, since
    attribute-value normalization would turn its newlines into spaces anyway."""
    return " ".join(value.splitlines())

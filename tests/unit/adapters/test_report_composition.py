"""DF-209 — JUnit composes with the other outputs in one run (SPEC §7).

`--reporter` selects the stdout format (terminal | json | junit); `--json-out` and
`--junit-out` are independent atomic file sinks, so a single run can emit terminal +
a JUnit file + a JSON file. This mirrors the existing JSON design exactly.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.composition import _report
from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.model.message import Usage
from dryfire.domain.model.trace import Trace

_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


def _run() -> RunResult:
    trace = Trace(
        case_name="c", suite_name="s", turns=[], final_text="done", termination="end_turn",
        total_usage=Usage(input_tokens=1, output_tokens=1), total_cost_usd=None, duration_ms=1000,
    )
    case = CaseResult(suite_name="s", case_name="c", trace=trace,
                      assertions=[AssertionResult(kind="calls_tool", description="calls_tool: x",
                                                  passed=True, message="")], passed=True)
    return RunResult(suites=[SuiteResult(name="s", path=Path("s.eval.yaml"), cases=[case])])


def _report_to(
    *, reporter: str = "terminal", json_out: str | None = None,
    junit_out: str | None = None, verbose: bool = False,
) -> str:
    out = io.StringIO()
    _report(_run(), reporter=reporter, json_out=json_out, junit_out=junit_out,
            verbose=verbose, out=out, now=_AT)
    return out.getvalue()


def test_reporter_junit_writes_xml_to_stdout() -> None:
    stdout = _report_to(reporter="junit")
    assert stdout.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<testsuites " in stdout


def test_reporter_junit_composes_with_json_out(tmp_path: Path) -> None:
    json_path = tmp_path / "r.json"
    stdout = _report_to(reporter="junit", json_out=str(json_path))
    assert "<testsuites " in stdout  # JUnit to stdout
    assert '"schema_version"' in json_path.read_text(encoding="utf-8")  # JSON to file


def test_junit_out_is_a_file_sink_alongside_terminal(tmp_path: Path) -> None:
    junit_path = tmp_path / "r.xml"
    stdout = _report_to(junit_out=str(junit_path))  # default terminal reporter
    assert "<testsuites" not in stdout  # terminal on stdout, not XML
    assert junit_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')


def test_all_three_outputs_compose_in_one_run(tmp_path: Path) -> None:
    junit_path, json_path = tmp_path / "r.xml", tmp_path / "r.json"
    stdout = _report_to(junit_out=str(junit_path), json_out=str(json_path))
    assert stdout and "<testsuites" not in stdout  # human terminal
    assert junit_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"')
    assert '"schema_version"' in json_path.read_text(encoding="utf-8")

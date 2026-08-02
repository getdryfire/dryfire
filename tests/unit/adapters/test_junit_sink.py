"""DF-209 — the JUnit XML sink (SPEC §9 v0.2; SPIKE-005 verdict = Candidate A).

The mapping is SPIKE-005's: suite → <testsuite>, case → <testcase>, one <failure>
per failing case with all failed assertions concatenated in the TEXT body (newlines
survive there, not in an attribute), <error> for provider_error/unmocked_tool.
Golden fixtures in tests/fixtures/expected_junit/ are the byte-for-byte contract.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dryfire.adapters.driven.reporting.junit_sink import render_junit, write_junit
from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall
from dryfire.domain.model.trace import TerminationReason, Trace, Turn

_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
_GOLDEN = Path(__file__).parent.parent.parent / "fixtures" / "expected_junit"
_XSD = _GOLDEN / "junit.xsd"
# Carries `&` and `<` so the escaping tests and the golden exercise the same content.
_REFUND_MSG = 'issue_refund called at turn 3 with {"amount": 500, "reason": "R&D <flagged>"}'


# -- fixture builders --------------------------------------------------------


def _trace(
    *,
    duration_ms: int,
    tool_names: list[str] | None = None,
    termination: TerminationReason = "end_turn",
    error: str | None = None,
) -> Trace:
    turns: list[Turn] = []
    if tool_names:
        calls = [ToolCall(id=f"call_{i}", name=n, arguments={}) for i, n in enumerate(tool_names)]
        turns = [
            Turn(
                index=0,
                request_messages=[Message(role="user", content="go")],
                response=ModelResponse(
                    text=None, tool_calls=calls, stop_reason="tool_use",
                    usage=Usage(input_tokens=1, output_tokens=1), latency_ms=10, raw={},
                ),
                tool_results=[],
            )
        ]
    return Trace(
        case_name="c", suite_name="refunds", turns=turns, final_text=None,
        termination=termination, total_usage=Usage(input_tokens=1, output_tokens=1),
        total_cost_usd=None, duration_ms=duration_ms, error=error,
    )


def _pass_case(name: str) -> CaseResult:
    return CaseResult(
        suite_name="refunds", case_name=name, trace=_trace(duration_ms=1200),
        assertions=[AssertionResult(kind="calls_tool", description="calls_tool: x",
                                    passed=True, message="")],
        passed=True,
    )


def _all_pass_run() -> RunResult:
    return RunResult(suites=[SuiteResult(
        name="refunds", path=Path("evals/refunds.eval.yaml"),
        cases=[_pass_case("issues refund on valid request"),
               _pass_case("denies refund when policy passes")],
    )])


def _failing_run() -> RunResult:
    traj = "lookup_order → check_policy → issue_refund → (end_turn)"
    case = CaseResult(
        suite_name="refunds", case_name="denies refund when policy check fails",
        trace=_trace(duration_ms=1234, tool_names=["lookup_order", "check_policy", "issue_refund"]),
        assertions=[
            AssertionResult(
                kind="not_calls_tool", description="not_calls_tool: issue_refund", passed=False,
                message=_REFUND_MSG,
                expected="issue_refund never called", actual=traj,
            ),
            AssertionResult(
                kind="calls_tool", description="calls_tool: escalate_to_human", passed=False,
                message="escalate_to_human was never called",
                expected="escalate_to_human to be called", actual=traj,
            ),
            AssertionResult(
                kind="calls_tool", description="calls_tool: lookup_order", passed=True, message="",
            ),
        ],
        passed=False,
    )
    return RunResult(suites=[SuiteResult(
        name="refunds", path=Path("evals/refunds.eval.yaml"), cases=[case])])


def _provider_error_run() -> RunResult:
    case = CaseResult(
        suite_name="refunds", case_name="handles provider outage",
        trace=_trace(duration_ms=1298, termination="provider_error",
                     error="provider error: connection reset by peer"),
        assertions=[], passed=False,
    )
    return RunResult(suites=[SuiteResult(
        name="refunds", path=Path("evals/refunds.eval.yaml"), cases=[case])])


# -- golden byte-for-byte tests (the contract) -------------------------------


@pytest.mark.parametrize(
    "run_builder, golden",
    [
        (_all_pass_run, "all_pass.xml"),
        (_failing_run, "one_failure_three_assertions.xml"),
        (_provider_error_run, "provider_error.xml"),
        (lambda: RunResult(suites=[]), "zero_cases.xml"),
    ],
)
def test_render_matches_golden_byte_for_byte(
    run_builder: Callable[[], RunResult], golden: str
) -> None:
    expected = (_GOLDEN / golden).read_text(encoding="utf-8")
    assert render_junit(run_builder(), generated_at=_AT) == expected


# -- validates against a real JUnit XSD --------------------------------------


@pytest.mark.parametrize("golden",
                         ["all_pass.xml", "one_failure_three_assertions.xml",
                          "provider_error.xml", "zero_cases.xml"])
def test_output_validates_against_junit_xsd(golden: str) -> None:
    xmlschema = pytest.importorskip("xmlschema")
    schema = xmlschema.XMLSchema(str(_XSD))
    # Validate the freshly rendered output, not just the committed golden.
    builders: dict[str, Callable[[], RunResult]] = {
        "all_pass.xml": _all_pass_run, "one_failure_three_assertions.xml": _failing_run,
        "provider_error.xml": _provider_error_run,
        "zero_cases.xml": lambda: RunResult(suites=[]),
    }
    xml = render_junit(builders[golden](), generated_at=_AT)
    schema.validate(xml)  # raises XMLSchemaValidationError on non-conformance


# -- the trajectory line survives escaping (assert on parsed content) --------


def test_trajectory_arrow_survives_xml_escaping() -> None:
    xml = render_junit(_failing_run(), generated_at=_AT)
    body = ET.fromstring(xml).find(".//testcase/failure").text  # type: ignore[union-attr]
    assert body is not None
    # The arrow is a literal char after a round-trip through a conformant parser…
    assert "lookup_order → check_policy → issue_refund → (end_turn)" in body
    # …and it is written literally in the source, not as a numeric character reference.
    assert "→" in xml and "&#" not in xml


def test_ampersand_and_angle_brackets_in_tool_args_round_trip() -> None:
    xml = render_junit(_failing_run(), generated_at=_AT)
    body = ET.fromstring(xml).find(".//testcase/failure").text  # type: ignore[union-attr]
    assert body is not None
    assert 'reason": "R&D <flagged>"' in body  # parser gives back the literals
    assert "R&amp;D &lt;flagged&gt;" in xml  # source stores them escaped


def test_failure_message_attribute_is_single_line_summary() -> None:
    # SPIKE-005: newlines collapse in an attribute, so the summary must be one line;
    # the multi-line block lives in the element text.
    xml = render_junit(_failing_run(), generated_at=_AT)
    failure = ET.fromstring(xml).find(".//testcase/failure")
    assert failure is not None
    assert "\n" not in (failure.get("message") or "")
    assert failure.get("message") == (
        "2 assertions failed: not_calls_tool: issue_refund; calls_tool: escalate_to_human"
    )
    assert "\n" in (failure.text or "")  # body is multi-line


def test_provider_error_is_error_not_failure() -> None:
    xml = render_junit(_provider_error_run(), generated_at=_AT)
    root = ET.fromstring(xml)
    assert root.find(".//testcase/error") is not None
    assert root.find(".//testcase/failure") is None
    assert root.get("errors") == "1" and root.get("failures") == "0"
    assert root.find(".//testcase/error").get("type") == "provider_error"  # type: ignore[union-attr]


# -- atomic file write (same guarantee as DF-203) ----------------------------


def test_write_junit_is_atomic_and_matches_render(tmp_path: Path) -> None:
    target = tmp_path / "junit.xml"
    write_junit(_failing_run(), target, generated_at=_AT)
    assert target.read_text(encoding="utf-8") == render_junit(_failing_run(), generated_at=_AT)
    assert list(tmp_path.iterdir()) == [target]  # no leftover .tmp files


def test_failed_render_leaves_the_prior_junit_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "junit.xml"
    target.write_text("PRIOR", encoding="utf-8")

    def boom(*a: object, **k: object) -> str:
        raise RuntimeError("render exploded")

    monkeypatch.setattr("dryfire.adapters.driven.reporting.junit_sink.render_junit", boom)
    with pytest.raises(RuntimeError, match="render exploded"):
        write_junit(_failing_run(), target, generated_at=_AT)
    assert target.read_text(encoding="utf-8") == "PRIOR"  # target never touched
    assert list(tmp_path.iterdir()) == [target]

"""AC-014 — the JSON reporter and full trace serialization (SPEC §7).

`--json-out` is a public interface from the moment it ships: `schema_version: 1`,
the complete Trace per case, sorted keys (diffable), no non-finite floats,
ISO-8601 Z timestamps, atomic writes. The file must be sufficient to re-render the
terminal report offline.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from dryfire.adapters.driven.reporting.json_sink import (
    SCHEMA_VERSION,
    deserialize_run,
    render_run,
    write_run,
)
from dryfire.adapters.driven.reporting.terminal import render_report
from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall, ToolResult
from dryfire.domain.model.trace import Trace, Turn

_SCHEMA = Path(__file__).parent.parent.parent / "fixtures" / "run_schema.json"
_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


def _rich_trace(*, cost: float | None = 0.0042) -> Trace:
    # A turn that exercises the load-bearing fields: Message.raw and a tool call
    # with malformed_arguments.
    call = ToolCall(id="call_0", name="lookup", arguments={}, malformed_arguments="{bad json")
    response = ModelResponse(
        text=None,
        tool_calls=[call],
        stop_reason="tool_use",
        usage=Usage(input_tokens=10, output_tokens=5),
        latency_ms=42,
        raw={"provider": "anthropic", "id": "msg_1"},
    )
    turn = Turn(
        index=0,
        request_messages=[Message(role="user", content="go", raw={"echo": True})],
        response=response,
        tool_results=[ToolResult(call_id="call_0", content="ok", is_error=False)],
    )
    return Trace(
        case_name="c",
        suite_name="s",
        turns=[turn],
        final_text="done",
        termination="end_turn",
        total_usage=Usage(input_tokens=10, output_tokens=5),
        total_cost_usd=cost,
        duration_ms=1200,
    )


def _run() -> RunResult:
    passing = CaseResult(
        suite_name="refund_agent",
        case_name="ok_case",
        trace=_rich_trace(),
        assertions=[
            AssertionResult(
                kind="calls_tool", description="calls_tool: lookup", passed=True, message=""
            )
        ],
        passed=True,
    )
    failing = CaseResult(
        suite_name="refund_agent",
        case_name="bad_case",
        trace=_rich_trace(cost=None),
        assertions=[
            AssertionResult(
                kind="calls_tool",
                description="calls_tool: issue_refund",
                passed=False,
                message="issue_refund was never called",
                expected="issue_refund to be called",
                actual="lookup → (end_turn)",
            )
        ],
        passed=False,
    )
    return RunResult(
        suites=[SuiteResult(name="refund_agent", path=Path("evals/refund_agent.eval.yaml"),
                            cases=[passing, failing])],
        complete=True,
    )


def test_output_validates_against_committed_schema() -> None:
    doc = json.loads(render_run(_run(), generated_at=_AT))
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(doc, schema)  # raises on mismatch
    assert doc["schema_version"] == SCHEMA_VERSION == 2


def test_timestamp_is_iso8601_utc_with_explicit_z() -> None:
    doc = json.loads(render_run(_run(), generated_at=_AT))
    assert doc["generated_at"] == "2026-07-31T12:00:00Z"


def test_round_trip_rerenders_identical_terminal_output() -> None:
    run = _run()
    doc = json.loads(render_run(run, generated_at=_AT))
    restored = deserialize_run(doc)
    assert render_report(restored, color=False) == render_report(run, color=False)


def test_two_runs_are_byte_identical_except_the_timestamp() -> None:
    run = _run()
    a = render_run(run, generated_at=_AT)
    b = render_run(run, generated_at=_AT)
    assert a == b  # same clock → identical

    later = render_run(run, generated_at=datetime(2027, 1, 1, tzinfo=UTC))
    diff = [
        (x, y) for x, y in zip(a.splitlines(), later.splitlines(), strict=True) if x != y
    ]
    assert len(diff) == 1 and "generated_at" in diff[0][0]


def test_message_raw_and_malformed_arguments_survive() -> None:
    doc = json.loads(render_run(_run(), generated_at=_AT))
    restored = deserialize_run(doc)
    trace = restored.suites[0].cases[0].trace
    assert trace is not None
    assert trace.turns[0].request_messages[0].raw == {"echo": True}
    assert trace.turns[0].response.raw == {"provider": "anthropic", "id": "msg_1"}
    assert trace.turns[0].response.tool_calls[0].malformed_arguments == "{bad json"


def test_keys_are_sorted_for_diffability() -> None:
    doc = render_run(_run(), generated_at=_AT)
    # Top-level keys appear in sorted order in the serialized text.
    top = [ln.split('"')[1] for ln in doc.splitlines() if ln.startswith('  "')]
    assert top == sorted(top)


def test_no_nan_or_infinity_in_output() -> None:
    for cost in (0.0, 0.0001, 1234.5678, None):
        text = render_run(RunResult(suites=[SuiteResult(
            name="s", path=Path("s.yaml"),
            cases=[CaseResult("s", "c", _rich_trace(cost=cost), [], True)])]), generated_at=_AT)
        assert "NaN" not in text and "Infinity" not in text


def test_write_is_atomic_and_produces_a_complete_valid_file(tmp_path: Path) -> None:
    out = tmp_path / "run.json"
    write_run(_run(), out, generated_at=_AT)
    assert out.read_text(encoding="utf-8") == render_run(_run(), generated_at=_AT)
    json.loads(out.read_text(encoding="utf-8"))  # complete + parseable
    assert list(tmp_path.iterdir()) == [out]  # no leftover .tmp files


def test_failed_serialization_leaves_the_prior_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "run.json"
    write_run(_run(), out, generated_at=_AT)
    original = out.read_text(encoding="utf-8")

    def boom(*a: object, **k: object) -> str:
        raise ValueError("serialization exploded")

    monkeypatch.setattr("dryfire.adapters.driven.reporting.json_sink.json.dumps", boom)
    try:
        write_run(_run(), out, generated_at=_AT)
    except ValueError:
        pass
    # The target is never touched when serialization fails — no partial overwrite.
    assert out.read_text(encoding="utf-8") == original
    assert list(tmp_path.iterdir()) == [out]


def test_interrupted_rename_leaves_no_partial_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate a crash at the rename step: temp+replace must leave the target
    # absent (never a partial write), and clean up the temp file.
    out = tmp_path / "run.json"

    def boom(*a: object, **k: object) -> None:
        raise OSError("rename interrupted")

    monkeypatch.setattr("dryfire.adapters.driven.reporting.json_sink.os.replace", boom)
    with pytest.raises(OSError):
        write_run(_run(), out, generated_at=_AT)
    assert not out.exists()  # target never created — no partial file
    assert list(tmp_path.iterdir()) == []  # temp cleaned up


def test_json_and_terminal_both_render_from_one_run() -> None:
    run = _run()
    terminal = render_report(run, color=False)
    js = render_run(run, generated_at=_AT)
    assert "refund_agent" in terminal
    assert json.loads(js)["suites"][0]["name"] == "refund_agent"

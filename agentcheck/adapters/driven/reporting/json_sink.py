"""JSON reporter and full trace serialization (SPEC §7, AC-014).

`--json-out` feeds everything that isn't a human — CI scripts, the v0.3 `compare`,
the v0.3 HTML report — so the shape is a **public interface** guarded by
`schema_version`. The document holds the complete `Trace` per case (every turn,
`request_messages`, `Message.raw`, `malformed_arguments`, usage, assertions), so it
is sufficient to re-render the terminal report offline (`deserialize_run`).

Guarantees: sorted keys (diffable), `allow_nan=False` (no `NaN`/`Infinity` — v0.2
fingerprint compatibility), ISO-8601 UTC timestamps with an explicit `Z`, and
**atomic** writes (serialize fully in memory, temp file + `os.replace`) so a killed
run never leaves a truncated file.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentcheck.application.scheduler import CaseResult, RunResult, SuiteResult
from agentcheck.domain.assertions.base import AssertionResult
from agentcheck.domain.model.trace import Trace

SCHEMA_VERSION = 1


def _iso_z(moment: datetime) -> str:
    utc = moment.astimezone(UTC)
    return utc.isoformat(timespec="seconds").replace("+00:00", "Z")


def _case_dict(case: CaseResult) -> dict[str, Any]:
    return {
        "suite_name": case.suite_name,
        "case_name": case.case_name,
        "passed": case.passed,
        "error": case.error,
        "assertions": [a.model_dump(mode="json") for a in case.assertions],
        "trace": None if case.trace is None else case.trace.model_dump(mode="json"),
    }


def _suite_dict(suite: SuiteResult) -> dict[str, Any]:
    return {"name": suite.name, "path": str(suite.path),
            "cases": [_case_dict(c) for c in suite.cases]}


def build_document(run: RunResult, *, generated_at: datetime) -> dict[str, Any]:
    """The run as a plain JSON-able dict — the versioned public shape."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_z(generated_at),
        "complete": run.complete,
        "suites": [_suite_dict(s) for s in run.suites],
    }


def render_run(run: RunResult, *, generated_at: datetime) -> str:
    """Serialize a run to JSON text: sorted keys, no non-finite floats, trailing
    newline. Deterministic given the same `generated_at`."""
    document = build_document(run, generated_at=generated_at)
    text = json.dumps(document, sort_keys=True, allow_nan=False, ensure_ascii=False, indent=2)
    return text + "\n"


def write_run(run: RunResult, path: Path | str, *, generated_at: datetime) -> None:
    """Write the run JSON atomically: fully serialize first (so a failure never
    touches the target), then temp file + `os.replace` in the target's directory."""
    content = render_run(run, generated_at=generated_at)  # may raise → target untouched
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


# -- Deserialization: enough to re-render the terminal report offline -------


def _case_from(data: dict[str, Any]) -> CaseResult:
    raw_trace = data["trace"]
    trace = None if raw_trace is None else Trace.model_validate(raw_trace)
    return CaseResult(
        suite_name=data["suite_name"],
        case_name=data["case_name"],
        trace=trace,
        assertions=[AssertionResult.model_validate(a) for a in data["assertions"]],
        passed=data["passed"],
        error=data.get("error"),
    )


def deserialize_run(document: dict[str, Any]) -> RunResult:
    """Rebuild a `RunResult` from a serialized document (the round-trip that lets
    v0.3 `compare`/HTML — and the round-trip test — re-render offline)."""
    suites = [
        SuiteResult(name=s["name"], path=Path(s["path"]), cases=[_case_from(c) for c in s["cases"]])
        for s in document["suites"]
    ]
    return RunResult(suites=suites, complete=document["complete"])

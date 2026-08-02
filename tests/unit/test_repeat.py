"""DF-305 — `repeat: N` execution and pass rates (SPEC §9 v0.3, EPIC-003).

Agent behaviour is stochastic even at temperature 0, and nothing in v0.1/v0.2 can see
that. `repeat: N` runs a case N times and reports `k/N`. The load-bearing guarantees:
`repeat: 1` is byte-identical to v0.2, repetitions share the ONE scheduler pool (not a
nested one), the result is a rate governed by `require_pass_rate`, and a disagreeing
case (0 < k < N) is the finding — surfaced, never buried.
"""

from __future__ import annotations

import asyncio
import json as _json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dryfire.adapters.driven.reporting.json_sink import render_run
from dryfire.adapters.driven.reporting.terminal import render_report
from dryfire.application.scheduler import (
    CaseResult,
    PlannedCase,
    PlannedSuite,
    RunResult,
    run_suites,
)
from dryfire.domain.model.case import ResolvedCase
from dryfire.domain.model.message import ModelResponse, Usage


def _rc(name: str, **over: Any) -> ResolvedCase:
    base: dict[str, Any] = dict(
        suite_name="s", case_name=name, suite_path=Path("s.eval.yaml"), provider="fake",
        model="m", max_turns=10, temperature=0.0, on_unmocked="error", system=None,
        input=name, expect=[{"final_contains": "GOOD"}], tools=[],
    )
    base.update(over)
    return ResolvedCase(**base)


def _suite(*cases: PlannedCase) -> list[PlannedSuite]:
    return [PlannedSuite(name="s", path=Path("s.eval.yaml"), cases=list(cases))]


def _text(value: str) -> ModelResponse:
    return ModelResponse(text=value, tool_calls=[], stop_reason="end_turn",
                         usage=Usage(input_tokens=0, output_tokens=0), latency_ms=0, raw={})


class _FlakyGateway:
    """Returns "BAD" for exactly the first `n_bad` complete() calls and "GOOD" after,
    so with `final_contains: GOOD` a case run N times passes exactly N - n_bad times —
    a deterministic k/N regardless of which repetitions happen to draw the failures."""

    name = "fake"

    def __init__(self, n_bad: int, *, delay: float = 0.0) -> None:
        self._left = n_bad
        self._delay = delay
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    def is_retryable(self, exc: Exception) -> bool:
        return False

    async def complete(self, request: Any) -> ModelResponse:
        self.calls += 1
        bad = self._left > 0
        if bad:
            self._left -= 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            return _text("BAD" if bad else "GOOD")
        finally:
            self.in_flight -= 1


def _run(suites: list[PlannedSuite], gw: Any, **kw: Any) -> CaseResult:
    result = asyncio.run(run_suites(suites, gw, **kw))
    return result.suites[0].cases[0]


def _run_full(suites: list[PlannedSuite], gw: Any, **kw: Any) -> RunResult:
    return asyncio.run(run_suites(suites, gw, **kw))


# -- repeat: 1 is byte-identical to v0.2 ------------------------------------


def test_repeat_1_is_identical_to_v2() -> None:
    case = _run(_suite(PlannedCase(case=_rc("c", repeat=1))), _FlakyGateway(0))
    assert case.passed
    assert case.repetitions is None  # no repeat machinery on the trace for the common case
    assert case.pass_rate is None
    assert case.trace is not None


# -- repeat: N produces N traces and a k/N rate -----------------------------


def test_repeat_5_produces_5_traces_and_a_rate() -> None:
    case = _run(_suite(PlannedCase(case=_rc("c", repeat=5))), _FlakyGateway(0))
    assert case.repetitions is not None
    assert len(case.repetitions) == 5           # all N traces kept
    assert all(r.trace is not None for r in case.repetitions)
    assert case.pass_rate == 1.0                 # 5/5
    assert case.passes == 5 and case.total == 5


def test_a_disagreeing_case_reports_a_partial_rate() -> None:
    case = _run(_suite(PlannedCase(case=_rc("c", repeat=5))), _FlakyGateway(1))
    assert case.passes == 4 and case.total == 5  # one repetition drew the failure
    assert case.pass_rate == 0.8


# -- require_pass_rate governs the build verdict ----------------------------


def test_require_pass_rate_passes_at_4_of_5() -> None:
    case = _run(_suite(PlannedCase(case=_rc("c", repeat=5, require_pass_rate=0.8))),
                _FlakyGateway(1))
    assert case.passes == 4
    assert case.passed  # 0.8 >= 0.8


def test_require_pass_rate_fails_at_3_of_5() -> None:
    case = _run(_suite(PlannedCase(case=_rc("c", repeat=5, require_pass_rate=0.8))),
                _FlakyGateway(2))
    assert case.passes == 3
    assert not case.passed  # 0.6 < 0.8


def test_default_require_pass_rate_is_all_n() -> None:
    case = _run(_suite(PlannedCase(case=_rc("c", repeat=5))), _FlakyGateway(1))
    assert not case.passed  # default 1.0: 4/5 is not enough


# -- repetitions share the ONE pool, bounded globally -----------------------


def test_repetitions_respect_the_global_concurrency_bound() -> None:
    gw = _FlakyGateway(0, delay=0.02)
    _run(_suite(PlannedCase(case=_rc("c", repeat=6))), gw, concurrency=2)
    assert gw.calls == 6
    assert gw.max_in_flight == 2  # six repetitions, never more than two in flight at once


# -- terminal: the rate, the disagreement, the interval, the warning --------


def test_terminal_shows_k_over_n() -> None:
    run = _run_full(_suite(PlannedCase(case=_rc("c", repeat=6, require_pass_rate=0.5))),
                    _FlakyGateway(2))
    assert "4/6" in render_report(run)


def test_repeat_1_terminal_output_has_no_rate() -> None:
    run = _run_full(_suite(PlannedCase(case=_rc("c", repeat=1))), _FlakyGateway(0))
    report = render_report(run)
    assert "1/1" not in report  # a non-repeated case looks exactly like v0.2


def test_disagreeing_case_is_visually_distinct() -> None:
    disagree = render_report(_run_full(_suite(PlannedCase(case=_rc("c", repeat=5))),
                                       _FlakyGateway(1)))   # 4/5
    uniform_pass = render_report(_run_full(_suite(PlannedCase(case=_rc("c", repeat=5))),
                                           _FlakyGateway(0)))  # 5/5
    uniform_fail = render_report(_run_full(_suite(PlannedCase(case=_rc("c", repeat=5))),
                                           _FlakyGateway(5)))  # 0/5
    assert "~" in disagree                    # a distinct disagreement glyph
    assert "~" not in uniform_pass
    assert "~" not in uniform_fail


def test_wilson_interval_shown_only_for_a_disagreeing_case() -> None:
    disagree = render_report(_run_full(_suite(PlannedCase(case=_rc("c", repeat=10))),
                                       _FlakyGateway(2)))   # 8/10
    uniform = render_report(_run_full(_suite(PlannedCase(case=_rc("c", repeat=10))),
                                      _FlakyGateway(0)))     # 10/10
    assert "CI" in disagree or "–" in disagree  # an interval is shown
    assert "CI" not in uniform


def test_below_minimum_n_warns_but_does_not_refuse() -> None:
    # repeat: 3 runs (never refused) but carries a wide-interval warning.
    run = _run_full(_suite(PlannedCase(case=_rc("c", repeat=3))), _FlakyGateway(0))
    assert run.suites[0].cases[0].total == 3  # it ran
    assert "5" in render_report(run) and "repeat" in render_report(run).lower()


# -- JSON artifact keeps all N traces ---------------------------------------


def _case_json(run: RunResult) -> dict[str, Any]:
    doc = _json.loads(render_run(run, generated_at=datetime(2026, 8, 2, tzinfo=UTC)))
    return doc["suites"][0]["cases"][0]  # type: ignore[no-any-return]


def test_json_artifact_keeps_all_n_traces() -> None:
    case = _case_json(_run_full(_suite(PlannedCase(case=_rc("c", repeat=5))), _FlakyGateway(1)))
    assert len(case["repetitions"]) == 5
    assert all(rep["trace"] is not None for rep in case["repetitions"])
    assert case["pass_rate"] == 0.8


def test_repeat_1_json_has_no_repetition_keys() -> None:
    case = _case_json(_run_full(_suite(PlannedCase(case=_rc("c", repeat=1))), _FlakyGateway(0)))
    assert "repetitions" not in case  # byte-identical to a v0.2 case artifact


# -- spec plumbing: resolution + positioned validation ----------------------


def _load(tmp_path: Path, body: str) -> tuple[Any, list[Any]]:
    from dryfire.adapters.driven.spec.loader import load_suite

    p = tmp_path / "s.eval.yaml"
    p.write_text(f"name: s\ncases:\n  - name: c\n    input: hi\n{body}    expect: []\n",
                 encoding="utf-8")
    return load_suite(p)


def test_repeat_and_rate_resolve_from_the_spec(tmp_path: Path) -> None:
    from dryfire.adapters.driven.spec.config import resolve

    suite, errors = _load(tmp_path, "    repeat: 5\n    require_pass_rate: 0.8\n")
    assert errors == []
    resolved = resolve(suite=suite, case=suite.cases[0], suite_path=tmp_path / "s.eval.yaml")
    assert resolved.repeat == 5
    assert resolved.require_pass_rate == 0.8


def test_default_repeat_is_one(tmp_path: Path) -> None:
    from dryfire.adapters.driven.spec.config import resolve

    suite, _ = _load(tmp_path, "")
    resolved = resolve(suite=suite, case=suite.cases[0], suite_path=tmp_path / "s.eval.yaml")
    assert resolved.repeat == 1 and resolved.require_pass_rate == 1.0


def test_repeat_zero_is_a_positioned_spec_error(tmp_path: Path) -> None:
    suite, errors = _load(tmp_path, "    repeat: 0\n")
    assert suite is None
    assert len(errors) == 1 and errors[0].position is not None


def test_require_pass_rate_above_one_is_a_spec_error(tmp_path: Path) -> None:
    suite, errors = _load(tmp_path, "    require_pass_rate: 1.5\n")
    assert suite is None
    assert len(errors) == 1

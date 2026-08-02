"""DF-301 — judge domain model and rubric versioning (SPEC §9 v0.3, EPIC-003).

`JudgeVerdict` and `Rubric` are pure domain values. Their one job beyond carrying a
score is making scores *comparable across time*: a verdict that cannot state how it
was produced (judge model version + rubric hash) must be unconstructable, and the
rubric hash must move whenever anything that could change the judgement moves —
including whitespace — while staying stable under changes that cannot (dict key
order). The hash reuses `domain/fingerprint.py`'s canonicaliser, never a second one
that could drift.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from dryfire.adapters.driven.reporting.json_sink import (
    SCHEMA_VERSION,
    deserialize_run,
    render_run,
)
from dryfire.application.scheduler import CaseResult, RunResult, SuiteResult
from dryfire.domain.fingerprint import canonical_json
from dryfire.domain.judging.rubric import Rubric
from dryfire.domain.judging.verdict import JudgeVerdict
from dryfire.domain.model.message import Usage
from dryfire.domain.model.trace import Trace


def _verdict(**overrides: object) -> JudgeVerdict:
    base: dict[str, object] = dict(
        score=0.9,
        passed=True,
        reasoning="the agent apologised and offered a refund",
        judge_model="claude-opus-4-8",
        judge_model_version="claude-opus-4-8-20260115",
        rubric_hash="a" * 64,
        threshold=0.7,
    )
    base.update(overrides)
    return JudgeVerdict(**base)  # type: ignore[arg-type]


# -- JudgeVerdict: provenance is mandatory (AC1) ----------------------------


def test_verdict_cannot_be_built_without_judge_model_version() -> None:
    with pytest.raises(ValidationError):
        JudgeVerdict(  # type: ignore[call-arg]
            score=0.9, passed=True, reasoning="ok",
            judge_model="claude-opus-4-8", rubric_hash="a" * 64, threshold=0.7,
        )


def test_verdict_cannot_be_built_without_rubric_hash() -> None:
    with pytest.raises(ValidationError):
        JudgeVerdict(  # type: ignore[call-arg]
            score=0.9, passed=True, reasoning="ok",
            judge_model="claude-opus-4-8", judge_model_version="v1", threshold=0.7,
        )


def test_verdict_is_frozen() -> None:
    verdict = _verdict()
    with pytest.raises(ValidationError):
        verdict.score = 0.1


def test_verdict_round_trips_through_json_with_no_loss() -> None:
    verdict = _verdict()
    restored = JudgeVerdict.model_validate(verdict.model_dump(mode="json"))
    assert restored == verdict


# -- Factories: passed follows the threshold; errors are distinct (DF-302) --


def test_from_score_computes_passed_from_threshold() -> None:
    rubric = Rubric(text="Grade politeness.", threshold=0.7)
    above = JudgeVerdict.from_score(
        score=0.8, reasoning="ok", rubric=rubric,
        judge_model="claude-opus-4-8", judge_model_version="claude-opus-4-8-20260115",
    )
    below = JudgeVerdict.from_score(
        score=0.6, reasoning="meh", rubric=rubric,
        judge_model="claude-opus-4-8", judge_model_version="claude-opus-4-8-20260115",
    )
    assert above.passed is True
    assert below.passed is False
    assert above.rubric_hash == rubric.hash()
    assert above.threshold == 0.7
    assert above.error is None


def test_from_error_is_distinct_from_a_genuine_zero() -> None:
    rubric = Rubric(text="Grade politeness.", threshold=0.7)
    errored = JudgeVerdict.from_error(
        reasoning="", rubric=rubric, judge_model="claude-opus-4-8",
        judge_model_version="claude-opus-4-8", error="429 rate limit",
    )
    genuine_zero = JudgeVerdict.from_score(
        score=0.0, reasoning="wrong", rubric=rubric,
        judge_model="claude-opus-4-8", judge_model_version="claude-opus-4-8-20260115",
    )
    assert errored.error == "429 rate limit"
    assert errored.passed is False
    assert genuine_zero.error is None  # a real 0 is not an error
    assert genuine_zero.passed is False
    # Both fail, but only one is a judge malfunction — the field distinguishes them.
    assert (errored.error is not None) != (genuine_zero.error is not None)


# -- Rubric hashing (AC2, AC3) ----------------------------------------------


def test_rubric_hash_is_deterministic() -> None:
    a = Rubric(text="Grade politeness from 0 to 1.", threshold=0.7)
    b = Rubric(text="Grade politeness from 0 to 1.", threshold=0.7)
    assert a.hash() == b.hash()


def test_rubric_hash_changes_on_any_whitespace_change() -> None:
    # Rubric text is whitespace-significant: reformatting may change the judgement,
    # so it MUST change the hash.
    tight = Rubric(text="Grade politeness.", threshold=0.7)
    spaced = Rubric(text="Grade  politeness.", threshold=0.7)  # one extra space
    newline = Rubric(text="Grade politeness.\n", threshold=0.7)  # trailing newline
    assert tight.hash() != spaced.hash()
    assert tight.hash() != newline.hash()


def test_two_rubrics_differing_only_in_threshold_hash_differently() -> None:
    lenient = Rubric(text="Grade politeness.", threshold=0.5)
    strict = Rubric(text="Grade politeness.", threshold=0.9)
    assert lenient.hash() != strict.hash()


def test_rubric_hash_changes_when_examples_change() -> None:
    without = Rubric(text="Grade politeness.", threshold=0.7)
    with_ex = Rubric(text="Grade politeness.", threshold=0.7, examples=("nice reply → 1.0",))
    assert without.hash() != with_ex.hash()


def test_rubric_hash_is_stable_across_dict_key_order() -> None:
    # The hash reuses fingerprint.canonical_json (sorted keys), so it cannot depend
    # on how the payload dict happens to be ordered — this is the whole reason for
    # reusing the canonicaliser instead of writing a second, drift-prone one.
    rubric = Rubric(text="Grade politeness.", threshold=0.7, examples=("ex-a", "ex-b"))
    reordered = {"examples": ["ex-a", "ex-b"], "threshold": 0.7, "text": "Grade politeness."}
    expected = hashlib.sha256(canonical_json(reordered).encode("utf-8")).hexdigest()
    assert rubric.hash() == expected


# -- Trace gains judge_verdicts, additively (SPIKE-006 Q5) -------------------


def test_trace_defaults_to_no_judge_verdicts() -> None:
    trace = _trace()
    assert trace.judge_verdicts == {}


def test_schema_version_bumped_to_2() -> None:
    # A capability signal so a reader can detect a judge-aware artifact (SPIKE-006 Q5).
    assert SCHEMA_VERSION == 2


def test_judge_verdicts_round_trip_through_the_json_artifact() -> None:
    # AC5: the verdict survives render → deserialize with no loss, keyed by assertion.
    verdict = _verdict()
    trace = _trace(judge_verdicts={"j1": verdict})
    run = RunResult(
        suites=[SuiteResult(
            name="s", path=Path("s.eval.yaml"),
            cases=[CaseResult("s", "c", trace, [], True)],
        )],
        complete=True,
    )
    doc = render_run(run, generated_at=datetime(2026, 8, 2, tzinfo=UTC))
    restored = deserialize_run(json.loads(doc))
    restored_trace = restored.suites[0].cases[0].trace
    assert restored_trace is not None
    assert restored_trace.judge_verdicts == {"j1": verdict}


def _trace(**overrides: object) -> Trace:
    base: dict[str, object] = dict(
        case_name="c", suite_name="s", turns=[], final_text="done",
        termination="end_turn", total_usage=Usage(input_tokens=0, output_tokens=0),
        total_cost_usd=None, duration_ms=0,
    )
    base.update(overrides)
    return Trace(**base)  # type: ignore[arg-type]

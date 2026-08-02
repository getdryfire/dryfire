"""DF-303 — the pure `llm_judge` assertion (SPEC §6.2, EPIC-003).

The assertion is pure: it reads a `JudgeVerdict` the enrichment stage
(ARCHITECTURE §4.4) already attached to the trace, keyed by (resolved model, rubric
hash), and applies the threshold. It makes no model call itself — that is the whole
point of Model C. A judge *error* is a distinct result state (not a silent low score),
and a failure message carries enough to act on: score, threshold, the judge's
reasoning, the rubric hash (provenance), and the tool trajectory.
"""

from __future__ import annotations

from dryfire.domain.assertions.registry import build
from dryfire.domain.judging.keys import judge_key
from dryfire.domain.judging.rubric import DEFAULT_JUDGE_THRESHOLD, Rubric
from dryfire.domain.judging.verdict import JudgeVerdict
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall
from dryfire.domain.model.trace import Trace, Turn

_MODEL = "claude-opus-4-8"
_RUBRIC = "Did the agent apologise and resolve the issue?"


def _trace_with(verdict: JudgeVerdict | None, *, model: str = _MODEL,
                rubric_text: str = _RUBRIC, threshold: float = DEFAULT_JUDGE_THRESHOLD) -> Trace:
    """A trace with one tool call (so there is a real trajectory line) and the given
    verdict attached under the key the assertion will compute."""
    verdicts: dict[str, JudgeVerdict] = {}
    if verdict is not None:
        rubric_hash = Rubric(text=rubric_text, threshold=threshold).hash()
        verdicts[judge_key(model=model, rubric_hash=rubric_hash)] = verdict
    turn = Turn(
        index=0, request_messages=[],
        response=ModelResponse(
            text=None, tool_calls=[ToolCall(id="c0", name="issue_refund", arguments={})],
            stop_reason="tool_use", usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0, raw={},
        ),
        tool_results=[],
    )
    return Trace(
        case_name="c", suite_name="s", turns=[turn], final_text="Sorry, refunded.",
        termination="end_turn", total_usage=Usage(input_tokens=0, output_tokens=0),
        total_cost_usd=None, duration_ms=0, model=model, judge_verdicts=verdicts,
    )


def _verdict(score: float, reasoning: str, *, threshold: float = DEFAULT_JUDGE_THRESHOLD,
             error: str | None = None) -> JudgeVerdict:
    rubric = Rubric(text=_RUBRIC, threshold=threshold)
    if error is not None:
        return JudgeVerdict.from_error(
            reasoning=reasoning, rubric=rubric, judge_model=_MODEL,
            judge_model_version="claude-opus-4-8-20260115", error=error,
        )
    return JudgeVerdict.from_score(
        score=score, reasoning=reasoning, rubric=rubric, judge_model=_MODEL,
        judge_model_version="claude-opus-4-8-20260115",
    )


def test_passes_when_the_verdict_passes() -> None:
    assertion = build("llm_judge", {"rubric": _RUBRIC})
    result = assertion.evaluate(_trace_with(_verdict(0.9, "apologised and refunded")))
    assert result.passed
    assert result.kind == "llm_judge"


def test_fails_when_the_verdict_fails() -> None:
    assertion = build("llm_judge", {"rubric": _RUBRIC})
    result = assertion.evaluate(_trace_with(_verdict(0.4, "never apologised")))
    assert not result.passed


def test_failure_message_carries_score_threshold_reasoning_hash_and_trajectory() -> None:
    assertion = build("llm_judge", {"rubric": _RUBRIC, "threshold": 0.7})
    result = assertion.evaluate(_trace_with(_verdict(0.4, "never apologised", threshold=0.7)))
    message = result.message
    assert "0.4" in message  # score
    assert "0.7" in message  # threshold
    assert "never apologised" in message  # judge reasoning
    assert Rubric(text=_RUBRIC, threshold=0.7).hash() in message  # rubric hash, provenance
    assert "issue_refund" in (message + str(result.actual))  # the trajectory line


def test_model_defaults_to_the_case_model() -> None:
    # No `model` arg → the assertion resolves the judge model from the trace's model,
    # which is the case model. The verdict was keyed under that model.
    assertion = build("llm_judge", {"rubric": _RUBRIC})
    trace = _trace_with(_verdict(0.9, "good"), model="claude-opus-4-8")
    assert assertion.evaluate(trace).passed


def test_model_override_keys_by_the_overridden_model() -> None:
    # `model:` names a different judge model; the verdict is keyed under THAT model,
    # not the case model, and the assertion must look it up there.
    assertion = build("llm_judge", {"rubric": _RUBRIC, "model": "claude-haiku-4-5"})
    key = judge_key(model="claude-haiku-4-5", rubric_hash=Rubric(text=_RUBRIC).hash())
    verdict = _verdict(0.95, "good")
    trace = Trace(
        case_name="c", suite_name="s", turns=[], final_text="ok", termination="end_turn",
        total_usage=Usage(input_tokens=0, output_tokens=0), total_cost_usd=None,
        duration_ms=0, model="claude-opus-4-8", judge_verdicts={key: verdict},
    )
    assert assertion.evaluate(trace).passed


def test_judge_error_is_a_distinct_result_state() -> None:
    assertion = build("llm_judge", {"rubric": _RUBRIC})
    result = assertion.evaluate(_trace_with(_verdict(0.0, "", error="429 rate limit")))
    assert not result.passed
    assert "JUDGE ERROR" in result.message.upper()
    assert "429 rate limit" in result.message


def test_missing_verdict_is_a_distinct_failure_not_a_silent_pass() -> None:
    # Enrichment did not run (or the key did not match): this must fail loudly, never
    # pass by default — a green judged assertion with no judgement is the worst outcome.
    assertion = build("llm_judge", {"rubric": _RUBRIC})
    result = assertion.evaluate(_trace_with(None))
    assert not result.passed
    assert "did not run" in result.message.lower() or "no judge" in result.message.lower()

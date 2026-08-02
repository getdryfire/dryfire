"""The `llm_judge` assertion (DF-303, SPEC §6.2).

The first non-deterministic assertion: an LLM grades the trace against a rubric. Per
SPIKE-006's Model C the assertion itself stays **pure** — the model call happens in the
application-layer enrichment stage (ARCHITECTURE §4.4), which attaches a `JudgeVerdict`
to `Trace.judge_verdicts` *before* assertions run. This assertion reads that verdict and
applies the threshold.

Adding it is the two files of SPEC §6.3 (this module + one registry import). It is the
first assertion that needs a value the loop does not compute, so the *feature* also
carries the one-time enrichment seam SPIKE-006 sanctioned — that seam is wiring, not a
new assertion protocol, and a second judge-style assertion would again be just two files.

`rubric` is required and validated non-empty at load time (a positioned spec error, zero
network). `model` defaults to the case model; `threshold` defaults to
`DEFAULT_JUDGE_THRESHOLD`. A judge *error* is a distinct result state, and a missing
verdict fails loudly — a green judged assertion with no judgement is the worst outcome.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, field_validator

from dryfire.domain.assertions.base import AssertionResult, register
from dryfire.domain.assertions.trajectory import render_trajectory
from dryfire.domain.judging.keys import judge_key
from dryfire.domain.judging.rubric import DEFAULT_JUDGE_THRESHOLD, Rubric
from dryfire.domain.model.trace import Trace


@register
class LlmJudge:
    """An LLM grades the trace against `rubric`; passes when the score meets the
    threshold. Non-deterministic and not free — see `docs/judging.md`."""

    kind: ClassVar[str] = "llm_judge"

    class Args(BaseModel):
        model_config = ConfigDict(extra="forbid")

        rubric: str
        model: str | None = None
        threshold: float = DEFAULT_JUDGE_THRESHOLD

        @field_validator("rubric")
        @classmethod
        def _non_empty(cls, value: str) -> str:
            # An empty rubric is a spec error at validate time (positioned by the
            # loader), not a runtime surprise after money has been spent.
            if not value.strip():
                raise ValueError("rubric must not be empty")
            return value

    def __init__(self, args: Args) -> None:
        self._rubric = Rubric(text=args.rubric, threshold=args.threshold)
        self._model_override = args.model

    def evaluate(self, trace: Trace) -> AssertionResult:
        trajectory = render_trajectory(trace)
        model = self._model_override or trace.model
        rubric_hash = self._rubric.hash()
        description = "llm_judge"

        if model is None:
            # No override and the trace has no resolved model — enrichment could not
            # have keyed a verdict. A wiring failure, surfaced, never a silent pass.
            return self._miss(description, trajectory,
                              "no judge model resolved (case model unknown)")

        verdict = trace.judge_verdicts.get(judge_key(model=model, rubric_hash=rubric_hash))
        if verdict is None:
            return self._miss(description, trajectory,
                              "the judge did not run for this assertion")
        if verdict.error is not None:
            # A broken judge is infrastructure, not an agent regression (SPIKE-006 Q3).
            return AssertionResult(
                kind=self.kind, description=description, passed=False,
                message=f"JUDGE ERROR: {verdict.error} (rubric {rubric_hash})",
                expected=f"a judge score >= {self._rubric.threshold}", actual=trajectory,
            )

        message = "" if verdict.passed else (
            f"judge score {verdict.score:g} < threshold {self._rubric.threshold:g}\n"
            f"  judge reasoning: {verdict.reasoning}\n"
            f"  rubric {rubric_hash}\n"
            f"  trajectory: {trajectory}"
        )
        return AssertionResult(
            kind=self.kind, description=description, passed=verdict.passed, message=message,
            expected=f"judge score >= {self._rubric.threshold:g}",
            actual=f"{verdict.score:g} — {trajectory}",
        )

    def _miss(self, description: str, trajectory: str, why: str) -> AssertionResult:
        return AssertionResult(
            kind=self.kind, description=description, passed=False,
            message=f"llm_judge could not be evaluated: {why} (rubric {self._rubric.hash()})",
            expected="a populated judge verdict", actual=trajectory,
        )

    # Exposed for the enrichment layer to build a matching JudgeRequest (application
    # reads these; the assertion never calls a model itself).
    @property
    def rubric(self) -> Rubric:
        return self._rubric

    @property
    def model_override(self) -> str | None:
        return self._model_override

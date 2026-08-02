"""`JudgeVerdict` (DF-301) — the graded outcome of one `llm_judge` assertion.

The verdict's job beyond carrying a score is provenance. `judge_model_version` and
`rubric_hash` are **required**: a verdict that cannot state how it was produced must be
unconstructable, because a score without provenance is not a measurement — it cannot be
compared to any other score. Pure domain: pydantic + stdlib only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from dryfire.domain.judging.rubric import Rubric
from dryfire.domain.model.message import Usage

# A shared zero-usage sentinel: Usage is frozen (immutable), so one instance is safe as
# both a field default and a factory default — and a name in a default keeps ruff's
# no-call-in-defaults rule (B008) happy.
_ZERO_USAGE = Usage(input_tokens=0, output_tokens=0)


class JudgeVerdict(BaseModel):
    """One judge's grading of one case, attached to the trace by the judging
    enrichment stage (ARCHITECTURE §4.4) and read by the pure `llm_judge` assertion.

    `judge_model` is the requested model; `judge_model_version` is the exact version
    the provider actually served (they differ when a model alias resolves to a dated
    snapshot) — both are pinned so a score stays comparable when the alias moves.

    `error` distinguishes a judge *malfunction* (provider error, unparseable response)
    from a genuine low score. A judge is an instrument: when it breaks, the agent under
    test did nothing wrong, so an error must never masquerade as a score of 0 (that
    would silently fail good cases). `error is None` ⇔ `score` is a real judgement."""

    model_config = ConfigDict(frozen=True)

    score: float
    passed: bool
    reasoning: str
    judge_model: str
    judge_model_version: str  # required — see module docstring
    rubric_hash: str  # required — provenance, not optional
    threshold: float
    error: str | None = None
    # The tokens this judge call cost, so the enrichment stage can total judge cost as
    # a separate channel (DF-304). Zero when the provider failed before responding.
    usage: Usage = _ZERO_USAGE

    @classmethod
    def from_score(
        cls, *, score: float, reasoning: str, rubric: Rubric,
        judge_model: str, judge_model_version: str,
        usage: Usage = _ZERO_USAGE,
    ) -> JudgeVerdict:
        """A successful judgement. `passed` follows the rubric threshold, computed in
        one place so it can never disagree with `score`/`threshold`."""
        return cls(
            score=score, passed=score >= rubric.threshold, reasoning=reasoning,
            judge_model=judge_model, judge_model_version=judge_model_version,
            rubric_hash=rubric.hash(), threshold=rubric.threshold, usage=usage,
        )

    @classmethod
    def from_error(
        cls, *, reasoning: str, rubric: Rubric, judge_model: str,
        judge_model_version: str, error: str,
        usage: Usage = _ZERO_USAGE,
    ) -> JudgeVerdict:
        """A judge malfunction. `passed` is False and `score` is 0.0, but `error` is
        what actually matters — it routes the result to exit 3 (provider error), not
        exit 1 (assertion failure). `usage` may be non-zero (an unparseable response
        was still billed) — its cost still belongs to the judge channel."""
        return cls(
            score=0.0, passed=False, reasoning=reasoning, judge_model=judge_model,
            judge_model_version=judge_model_version, rubric_hash=rubric.hash(),
            threshold=rubric.threshold, error=error, usage=usage,
        )

"""`JudgeVerdict` (DF-301) — the graded outcome of one `llm_judge` assertion.

The verdict's job beyond carrying a score is provenance. `judge_model_version` and
`rubric_hash` are **required**: a verdict that cannot state how it was produced must be
unconstructable, because a score without provenance is not a measurement — it cannot be
compared to any other score. Pure domain: pydantic + stdlib only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class JudgeVerdict(BaseModel):
    """One judge's grading of one case, attached to the trace by the judging
    enrichment stage (ARCHITECTURE §4.4) and read by the pure `llm_judge` assertion.

    `judge_model` is the requested model; `judge_model_version` is the exact version
    the provider actually served (they differ when a model alias resolves to a dated
    snapshot) — both are pinned so a score stays comparable when the alias moves."""

    model_config = ConfigDict(frozen=True)

    score: float
    passed: bool
    reasoning: str
    judge_model: str
    judge_model_version: str  # required — see module docstring
    rubric_hash: str  # required — provenance, not optional
    threshold: float

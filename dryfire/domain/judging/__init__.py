"""Judging domain (v0.3, EPIC-003): pure values for LLM-as-judge assertions.

`Rubric` (what to grade + the threshold + any few-shot examples) and `JudgeVerdict`
(the graded outcome, with the provenance that makes a score comparable across time).
Pure: pydantic + stdlib only, no I/O — the model call that produces a verdict lives in
the application layer (ARCHITECTURE §4.4, the judging enrichment seam).
"""

from dryfire.domain.judging.keys import judge_key
from dryfire.domain.judging.rubric import DEFAULT_JUDGE_THRESHOLD, Rubric
from dryfire.domain.judging.verdict import JudgeVerdict

__all__ = ["DEFAULT_JUDGE_THRESHOLD", "JudgeVerdict", "Rubric", "judge_key"]

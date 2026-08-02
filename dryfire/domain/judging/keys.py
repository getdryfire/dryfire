"""The key under which a judge verdict is stored on a trace (DF-303).

`Trace.judge_verdicts` is keyed by (resolved judge model, rubric hash). Both the
enrichment stage (which produces the verdict) and the pure `llm_judge` assertion (which
reads it) compute the key with this one function, so they can never disagree. Keying by
content — not by positional index — means two identical judged assertions in a case
dedupe to a single judge call, and it needs no index threaded into a pure assertion.
"""

from __future__ import annotations


def judge_key(*, model: str, rubric_hash: str) -> str:
    """A stable key for a verdict. The model is part of the key because the same rubric
    graded by two different judge models is two different, non-comparable judgements
    (the rubric hash already folds in the threshold and examples)."""
    return f"{model}\n{rubric_hash}"

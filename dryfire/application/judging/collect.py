"""Collect the judge requests a case needs graded (DF-303).

The bridge between the pure `llm_judge` assertions in a case's `expect` and the judge
evaluator: it reads each judged entry, resolves the judge model (the assertion's
`model:` override, else the case model), and builds a `JudgeRequest` keyed exactly as
the assertion will look it up (`judge_key`). Identical judged assertions dedupe to one
request — one judge call, one verdict, both assertions read it.

This is the one place that is kind-specific about `llm_judge`, and deliberately so:
`llm_judge` is the sanctioned special case (SPIKE-006) — the only assertion needing a
value the loop does not compute. Everything else stays registry-driven.
"""

from __future__ import annotations

from dryfire.application.judging.evaluator import JudgeRequest
from dryfire.domain.assertions.judge import LlmJudge
from dryfire.domain.assertions.registry import build
from dryfire.domain.judging.keys import judge_key
from dryfire.domain.model.case import ResolvedCase


def collect_judge_requests(case: ResolvedCase) -> list[JudgeRequest]:
    """Every distinct judge request a case's `expect` calls for, in first-appearance
    order. Empty for a structural-only case — the caller skips enrichment entirely."""
    seen: set[str] = set()
    requests: list[JudgeRequest] = []
    for entry in case.expect:
        kind = next(iter(entry))
        if kind != LlmJudge.kind:
            continue
        assertion = build(kind, entry[kind])
        if not isinstance(assertion, LlmJudge):  # pragma: no cover - kind guard guarantees it
            continue
        model = assertion.model_override or case.model
        key = judge_key(model=model, rubric_hash=assertion.rubric.hash())
        if key in seen:
            continue
        seen.add(key)
        requests.append(JudgeRequest(assertion_id=key, rubric=assertion.rubric, model=model))
    return requests

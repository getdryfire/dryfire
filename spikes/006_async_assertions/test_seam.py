"""SPIKE-006 proof — Model C seam holds against the real ports and domain types.

Not collected by `make test` (pytest `testpaths = ["tests"]`); run explicitly:

    uv run pytest spikes/006_async_assertions/test_seam.py -q

Each test maps to an acceptance criterion / FINDINGS question.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from dryfire.application.ports.model_gateway import CompletionRequest, ModelParams
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.trace import Trace

# The spike dir name (`006_...`) is not a valid package name, so import `seam` by
# putting its directory on the path rather than as a relative import.
sys.path.insert(0, str(Path(__file__).parent))
from seam import (  # noqa: E402
    EnrichedTrace,
    JudgeAssertion,
    JudgeEnricher,
    JudgeRequest,
    JudgeVerdict,
    process_case_seam,
)


def _trace(final_text: str = "done") -> Trace:
    return Trace(
        case_name="c", suite_name="s", turns=[], final_text=final_text,
        termination="end_turn", total_usage=Usage(input_tokens=0, output_tokens=0),
        total_cost_usd=None, duration_ms=0,
    )


class _ScriptedJudge:
    """A ModelGateway that returns a fixed JSON verdict, optionally after a sleep so
    concurrency is observable. Records requests to assert cassette routing."""

    name = "fake-judge"

    def __init__(self, payload: str, *, delay: float = 0.0) -> None:
        self._payload = payload
        self._delay = delay
        self.requests: list[CompletionRequest] = []

    def is_retryable(self, exc: Exception) -> bool:
        return False

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        self.requests.append(request)
        if self._delay:
            await asyncio.sleep(self._delay)
        return ModelResponse(
            text=self._payload, tool_calls=[], stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=5), latency_ms=1, raw={},
        )


# -- Pure assertion: pass / fail on a scripted verdict (protocol unchanged) --


def test_pure_assertion_passes_above_threshold() -> None:
    enriched = EnrichedTrace(
        trace=_trace(),
        judge_verdicts={"j1": JudgeVerdict(assertion_id="j1", score=0.9, reasoning="ok")},
    )
    result = JudgeAssertion("j1", threshold=0.8).evaluate(enriched)
    assert result.passed


def test_pure_assertion_fails_below_threshold_with_reasoning() -> None:
    enriched = EnrichedTrace(
        trace=_trace(),
        judge_verdicts={"j1": JudgeVerdict(assertion_id="j1", score=0.4, reasoning="weak")},
    )
    result = JudgeAssertion("j1", threshold=0.8).evaluate(enriched)
    assert not result.passed
    assert "weak" in result.message  # reasoning surfaced (DF-303)
    assert "0.40" in result.message and "0.80" in result.message


def test_judge_error_is_distinct_from_score_zero() -> None:
    # Q3: an errored judge is NOT a score of 0 — it carries a JUDGE_ERROR marker so
    # the exit-code layer can treat it like a provider error, not an agent failure.
    enriched = EnrichedTrace(
        trace=_trace(),
        judge_verdicts={"j1": JudgeVerdict(
            assertion_id="j1", score=0.0, reasoning="", error="429 rate limit"
        )},
    )
    result = JudgeAssertion("j1", threshold=0.8).evaluate(enriched)
    assert not result.passed
    assert result.message.startswith("JUDGE_ERROR:")


# -- Async enrichment: routes through the ModelGateway port ------------------


def test_enrichment_routes_through_the_gateway_port() -> None:
    # AC: judge calls go through ModelGateway — assert via the fake's recorded
    # requests, and confirm temperature=0 on every judge call.
    judge = _ScriptedJudge('{"score": 0.95, "reasoning": "great"}')
    enricher = JudgeEnricher(gateway=judge)
    req = JudgeRequest(assertion_id="j1", rubric="Is it polite?", model="judge-model")

    enriched = asyncio.run(enricher.enrich(_trace(), [req]))

    assert enriched.judge_verdicts["j1"].score == 0.95
    assert len(judge.requests) == 1
    assert judge.requests[0].params == ModelParams(temperature=0)
    assert judge.requests[0].model == "judge-model"


def test_unparseable_judge_response_is_an_error_not_zero() -> None:
    judge = _ScriptedJudge("not json at all")
    enricher = JudgeEnricher(gateway=judge)
    req = JudgeRequest(assertion_id="j1", rubric="r", model="m")

    enriched = asyncio.run(enricher.enrich(_trace(), [req]))
    verdict = enriched.judge_verdicts["j1"]
    assert verdict.error is not None
    assert "unparseable" in verdict.error


# -- Zero-extra-path guarantee for structural-only suites (success crit 2) ---


def test_structural_only_case_touches_no_gateway() -> None:
    judge = _ScriptedJudge('{"score": 1.0, "reasoning": "x"}')
    enricher = JudgeEnricher(gateway=judge)

    # No judge requests → enrichment returns immediately, gateway untouched.
    enriched = asyncio.run(enricher.enrich(_trace(), []))
    assert enriched.judge_verdicts == {}
    assert judge.requests == []  # ZERO extra path — the whole point of Model C


def test_process_case_seam_skips_enrichment_when_no_judges() -> None:
    # A structural-only case never awaits the enricher; passing enrich=None proves
    # the seam degrades to today's pure, sync evaluation.
    results = asyncio.run(process_case_seam(_trace(), [], [], enrich=None))
    assert results == []


# -- Batching + independent concurrency bound (Q4, DF-302) -------------------


def test_judge_concurrency_is_bounded_globally_across_cases() -> None:
    # A shared semaphore bounds judge calls across ALL cases at once — N cases each
    # with M judges never exceed the bound, and it is a flat gather, not a nested
    # pool. Prove it: 3 "cases" × 3 judges = 9 calls, bound = 2 → max in-flight ≤ 2.
    judge = _ScriptedJudge('{"score": 1.0, "reasoning": "x"}', delay=0.02)
    enricher = JudgeEnricher(gateway=judge, concurrency=2)

    def reqs(case: int) -> list[JudgeRequest]:
        return [JudgeRequest(assertion_id=f"c{case}-j{j}", rubric="r", model="m")
                for j in range(3)]

    async def run_all() -> None:
        await asyncio.gather(*(enricher.enrich(_trace(), reqs(c)) for c in range(3)))

    asyncio.run(run_all())
    assert len(judge.requests) == 9  # all graded (batched, not dropped)
    assert enricher.max_in_flight <= 2  # bound respected across cases
    assert enricher.max_in_flight == 2  # and actually reached — real overlap


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

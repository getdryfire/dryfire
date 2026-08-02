"""DF-302 — the judge evaluator behind the ModelGateway port (EPIC-003).

The evaluator implements SPIKE-006's Model C: it grades a `Trace` against a rubric by
calling the SAME `ModelGateway` used for the agent under test — so judge calls are
cassette-backed and retried by the EPIC-002 decorators for free, with no second HTTP
client and no second cache. It is injected, so these tests drive it with a scripted
gateway and never touch a network.

Load-bearing behaviours pinned here:
  - judge calls route through the gateway (assert via the fake's recorded requests)
  - temperature=0 always (a judge is an instrument, not a creative writer)
  - an unparseable response is a judge *error*, never a silent score of 0
  - a provider exception is a judge error, never an escaped exception
  - judge concurrency is bounded independently of case concurrency
  - a judge call replays from a real cassette with no live call
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dryfire.adapters.driven.cache.file_store import FileCassetteStore
from dryfire.adapters.driven.providers.caching import CachingGateway
from dryfire.application.judging.evaluator import JudgeEvaluator, JudgeRequest
from dryfire.application.ports.model_gateway import CompletionRequest
from dryfire.domain.judging.rubric import Rubric
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.trace import Trace


def _trace(final_text: str = "I'm sorry, I've issued your refund.") -> Trace:
    return Trace(
        case_name="c", suite_name="s", turns=[], final_text=final_text,
        termination="end_turn", total_usage=Usage(input_tokens=0, output_tokens=0),
        total_cost_usd=None, duration_ms=0,
    )


def _req(assertion_id: str = "j1", *, model: str = "claude-opus-4-8",
         threshold: float = 0.7) -> JudgeRequest:
    return JudgeRequest(
        assertion_id=assertion_id,
        rubric=Rubric(text="Did the agent apologise and resolve the issue?", threshold=threshold),
        model=model,
    )


class _ScriptedJudge:
    """A ModelGateway returning a fixed payload, optionally after a delay (so
    concurrency is observable) and optionally raising. Records requests and tracks
    its own max concurrent in-flight count — the production evaluator carries no
    test-only counter."""

    name = "fake-judge"

    def __init__(self, payload: str = '{"score": 0.9, "reasoning": "apologised, refunded"}',
                 *, delay: float = 0.0, raises: Exception | None = None,
                 served_model: str | None = "claude-opus-4-8-20260115") -> None:
        self._payload = payload
        self._delay = delay
        self._raises = raises
        self._served_model = served_model
        self.requests: list[CompletionRequest] = []
        self.in_flight = 0
        self.max_in_flight = 0

    def is_retryable(self, exc: Exception) -> bool:
        return False

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        self.requests.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            if self._raises is not None:
                raise self._raises
            raw = {"model": self._served_model} if self._served_model else {}
            return ModelResponse(
                text=self._payload, tool_calls=[], stop_reason="end_turn",
                usage=Usage(input_tokens=20, output_tokens=8), latency_ms=1, raw=raw,
            )
        finally:
            self.in_flight -= 1


# -- Routing, temperature, provenance ---------------------------------------


def test_judge_calls_route_through_the_gateway() -> None:
    judge = _ScriptedJudge()
    evaluator = JudgeEvaluator(gateway=judge)
    verdicts = asyncio.run(evaluator.evaluate(_trace(), [_req()]))
    assert len(judge.requests) == 1
    assert verdicts["j1"].score == 0.9


def test_every_judge_call_uses_temperature_zero() -> None:
    judge = _ScriptedJudge()
    evaluator = JudgeEvaluator(gateway=judge)
    asyncio.run(evaluator.evaluate(_trace(), [_req()]))
    assert judge.requests[0].params.temperature == 0


def test_verdict_carries_provenance_from_request_and_response() -> None:
    judge = _ScriptedJudge(served_model="claude-opus-4-8-20260115")
    evaluator = JudgeEvaluator(gateway=judge)
    req = _req(threshold=0.7)
    verdict = asyncio.run(evaluator.evaluate(_trace(), [req]))["j1"]
    assert verdict.judge_model == "claude-opus-4-8"  # the requested model
    assert verdict.judge_model_version == "claude-opus-4-8-20260115"  # the served version
    assert verdict.rubric_hash == req.rubric.hash()
    assert verdict.threshold == 0.7
    assert verdict.passed is True  # 0.9 >= 0.7
    assert verdict.error is None


def test_judge_model_version_falls_back_to_requested_when_provider_is_silent() -> None:
    judge = _ScriptedJudge(served_model=None)  # provider reports no model in raw
    evaluator = JudgeEvaluator(gateway=judge)
    verdict = asyncio.run(evaluator.evaluate(_trace(), [_req(model="claude-opus-4-8")]))["j1"]
    assert verdict.judge_model_version == "claude-opus-4-8"


# -- Defensive parsing: errors are never a silent zero ----------------------


def test_unparseable_response_is_a_judge_error_not_score_zero() -> None:
    judge = _ScriptedJudge(payload="I think it was pretty good, maybe 8/10?")
    evaluator = JudgeEvaluator(gateway=judge)
    verdict = asyncio.run(evaluator.evaluate(_trace(), [_req()]))["j1"]
    assert verdict.error is not None
    assert verdict.passed is False


def test_json_wrapped_in_markdown_fences_still_parses() -> None:
    judge = _ScriptedJudge(payload='```json\n{"score": 0.85, "reasoning": "good"}\n```')
    evaluator = JudgeEvaluator(gateway=judge)
    verdict = asyncio.run(evaluator.evaluate(_trace(), [_req()]))["j1"]
    assert verdict.error is None
    assert verdict.score == 0.85


def test_provider_exception_becomes_a_judge_error_not_a_raise() -> None:
    judge = _ScriptedJudge(raises=RuntimeError("429 rate limit"))
    evaluator = JudgeEvaluator(gateway=judge)
    verdict = asyncio.run(evaluator.evaluate(_trace(), [_req()]))["j1"]
    assert verdict.error is not None
    assert "429" in verdict.error
    assert verdict.passed is False


def test_a_genuine_zero_is_not_an_error() -> None:
    judge = _ScriptedJudge(payload='{"score": 0.0, "reasoning": "never apologised"}')
    evaluator = JudgeEvaluator(gateway=judge)
    verdict = asyncio.run(evaluator.evaluate(_trace(), [_req()]))["j1"]
    assert verdict.error is None  # a real 0 is a judgement, not a malfunction
    assert verdict.passed is False


# -- Independent concurrency bound (SPIKE-006 Q4, DF-302) -------------------


def test_judge_concurrency_is_bounded_independently() -> None:
    # 9 requests across 3 evaluate() calls sharing one evaluator; bound = 2.
    judge = _ScriptedJudge(delay=0.02)
    evaluator = JudgeEvaluator(gateway=judge, concurrency=2)

    async def run_all() -> None:
        await asyncio.gather(*(
            evaluator.evaluate(_trace(), [_req(f"c{c}-j{j}") for j in range(3)])
            for c in range(3)
        ))

    asyncio.run(run_all())
    assert len(judge.requests) == 9
    assert judge.max_in_flight == 2  # reached the bound and never exceeded it


# -- Cassette-backed for free (integration with the real CachingGateway) ----


def test_judge_call_replays_from_a_cassette_with_no_live_call(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path / "cassettes")
    rubric_req = _req()

    # Record: a live judge call through a CachingGateway in auto mode.
    live = _ScriptedJudge(payload='{"score": 0.77, "reasoning": "resolved"}')
    recording = CachingGateway(live, store, mode="auto", suite="s", case="c")
    recorded = asyncio.run(JudgeEvaluator(gateway=recording).evaluate(_trace(), [rubric_req]))
    assert recorded["j1"].score == 0.77
    assert len(live.requests) == 1

    # Replay: a gateway that raises if ever called live — the cassette must serve it.
    class _NoLive:
        name = "fake-judge"

        def is_retryable(self, exc: Exception) -> bool:
            return False

        async def complete(self, request: CompletionRequest) -> ModelResponse:
            raise AssertionError("replay must not make a live call")

    replaying = CachingGateway(_NoLive(), store, mode="replay", suite="s", case="c")
    replayed = asyncio.run(JudgeEvaluator(gateway=replaying).evaluate(_trace(), [rubric_req]))
    assert replayed["j1"].score == 0.77  # same verdict, zero live calls

"""SPIKE-006 reference seam — Model C (judge as a pre-assertion enrichment stage).

This module is the *reference implementation* the FINDINGS verdict points to. It is
deliberately small and self-contained, but it exercises the real ports and domain
types so the proof is not a toy:

  - `dryfire.domain.model.trace.Trace` — the real, frozen domain trace.
  - `dryfire.application.ports.model_gateway.ModelGateway` — the real judge port.
  - `dryfire.domain.assertions.base.AssertionResult` — the real result type.

The three moving parts of Model C, each demonstrated below:

  1. `JudgeVerdict` — a **pure** domain value (pydantic + stdlib only). In the real
     epic this lands in `domain/judging/verdict.py` (DF-301) and Contract 3 covers
     it. Nothing here imports an SDK, httpx, or an adapter.
  2. `JudgeAssertion` — a **pure, sync** assertion. It reads an already-populated
     verdict and applies a threshold. The `Assertion` protocol
     (`evaluate(trace) -> AssertionResult`) is unchanged: no async, no gateway.
  3. `enrich_with_judges` — an **async** enrichment stage that lives in the
     application layer (here, the scheduler seam). It is the *only* place I/O
     happens. It mirrors the existing `price(trace, case)` callback in
     `composition._make_price`, except it is `await`ed and closes over a gateway +
     a shared concurrency semaphore.

The load-bearing claim: a structural-only suite takes ZERO extra code path — the
enrichment call is skipped by an `if requests:` guard exactly as `price` is skipped
by `if price is not None`, and `loop.py` never changes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from dryfire.application.ports.model_gateway import (
    CompletionRequest,
    ModelGateway,
    ModelParams,
)
from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.model.message import Message
from dryfire.domain.model.trace import Trace

# ---------------------------------------------------------------------------
# 1. Pure domain value (DF-301 will place the real one in domain/judging/).
# ---------------------------------------------------------------------------


class JudgeVerdict(BaseModel):
    """A judge's grading of one case, keyed to the assertion that requested it.

    In the real DF-301 model this also carries `judge_model_version` and
    `rubric_hash` as *required* fields (provenance is the whole point). The spike
    keeps the minimum needed to prove the seam."""

    model_config = ConfigDict(frozen=True)

    assertion_id: str
    score: float
    reasoning: str
    error: str | None = None  # a judge *error* is distinct from a low score


class EnrichedTrace(BaseModel):
    """The real `Trace` plus the verdicts attached by the enrichment stage.

    The spike carries verdicts in a wrapper so it never mutates the frozen real
    `Trace`. DF-301 instead adds `judge_verdicts: dict[str, JudgeVerdict] = {}`
    directly onto `Trace` — additive and optional, so structural-only traces stay
    byte-identical and the v0.2 JSON schema stays backward-compatible (Q5)."""

    model_config = ConfigDict(frozen=True)

    trace: Trace
    judge_verdicts: dict[str, JudgeVerdict] = {}


# ---------------------------------------------------------------------------
# 2. Pure, sync assertion — the `Assertion` protocol is untouched.
# ---------------------------------------------------------------------------


class JudgeAssertion:
    """Reads a verdict the enrichment stage already populated and applies a
    threshold. No I/O, no gateway, no async — a judge failure and a score below
    threshold are reported distinctly."""

    kind: ClassVar[str] = "llm_judge"

    def __init__(self, assertion_id: str, threshold: float) -> None:
        self._id = assertion_id
        self._threshold = threshold

    def evaluate(self, enriched: EnrichedTrace) -> AssertionResult:
        verdict = enriched.judge_verdicts.get(self._id)
        if verdict is None:
            # Enrichment must run before assertions; a missing verdict is a wiring
            # bug, surfaced loudly rather than as a silent pass.
            return AssertionResult(
                kind=self.kind, description=f"llm_judge[{self._id}]", passed=False,
                message="judge verdict was never populated (enrichment did not run)",
            )
        if verdict.error is not None:
            # Q3: a judge error is a DISTINCT state, not a score of 0. The marker in
            # the message lets the exit-code layer treat it like a provider error.
            return AssertionResult(
                kind=self.kind, description=f"llm_judge[{self._id}]", passed=False,
                message=f"JUDGE_ERROR: {verdict.error}",
            )
        passed = verdict.score >= self._threshold
        return AssertionResult(
            kind=self.kind, description=f"llm_judge[{self._id}]", passed=passed,
            message=(
                "" if passed
                else f"score {verdict.score:.2f} < threshold {self._threshold:.2f}: "
                f"{verdict.reasoning}"
            ),
            expected=f"judge score >= {self._threshold:.2f}",
            actual=f"{verdict.score:.2f}",
        )


# ---------------------------------------------------------------------------
# 3. Async enrichment stage — the ONLY place I/O happens (application layer).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeRequest:
    """What one `llm_judge` assertion needs graded. Built from the case's `expect`
    entries; the assertion itself stays pure and never sees this."""

    assertion_id: str
    rubric: str
    model: str


@dataclass
class JudgeEnricher:
    """Closes over the judge gateway and a SHARED semaphore, exactly as
    `_make_price` closes over the pricing catalog. One instance per run, injected
    into the scheduler. The shared semaphore bounds judge concurrency GLOBALLY
    across all cases (DF-302), independent of case concurrency — N cases × M judges
    all acquire the same bound, never a nested pool."""

    gateway: ModelGateway
    concurrency: int = 4
    _sem: asyncio.Semaphore = field(init=False)
    max_in_flight: int = field(default=0, init=False)  # spike-only, for the test
    _in_flight: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._sem = asyncio.Semaphore(self.concurrency)

    async def _grade(self, trace: Trace, req: JudgeRequest) -> JudgeVerdict:
        async with self._sem:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            try:
                # Judge calls go through the SAME ModelGateway port, so wrapping the
                # gateway in CachingGateway makes judge calls cassette-backed for
                # free (the fingerprint already includes the model, so a judge model
                # differing from the case model is a distinct cassette entry).
                request = CompletionRequest(
                    model=req.model,
                    system="You are a grader. Return JSON: {\"score\": float, \"reasoning\": str}.",
                    messages=[Message(role="user", content=req.rubric + "\n\n" + _render(trace))],
                    tools=[],
                    params=ModelParams(temperature=0),  # a judge is an instrument
                )
                response = await self.gateway.complete(request)
                return _parse_verdict(req.assertion_id, response.text or "")
            finally:
                self._in_flight -= 1

    async def enrich(self, trace: Trace, requests: list[JudgeRequest]) -> EnrichedTrace:
        """The scheduler seam. A structural-only case passes `requests=[]` and this
        returns immediately with no gateway touched — the zero-extra-path guarantee."""
        if not requests:
            return EnrichedTrace(trace=trace)  # zero I/O, zero extra path
        # Within a case, judges run concurrently; across cases they share the
        # semaphore. gather here + the scheduler's own case pool = batching (Q4).
        verdicts = await asyncio.gather(*(self._grade(trace, r) for r in requests))
        return EnrichedTrace(
            trace=trace, judge_verdicts={v.assertion_id: v for v in verdicts}
        )


def _render(trace: Trace) -> str:
    """The slice of the trace the judge grades. Kept trivial for the spike."""
    return f"final_text: {trace.final_text!r}\ntool_calls: {trace.tool_names()}"


def _parse_verdict(assertion_id: str, text: str) -> JudgeVerdict:
    """Parse defensively: an unparseable judge response is a judge ERROR, never a
    score of 0. Scoring 0 on a parse failure would silently fail cases for a bug in
    the judge (DF-302 constraint)."""
    try:
        data = json.loads(text)
        return JudgeVerdict(
            assertion_id=assertion_id,
            score=float(data["score"]),
            reasoning=str(data.get("reasoning", "")),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return JudgeVerdict(
            assertion_id=assertion_id, score=0.0, reasoning="",
            error=f"unparseable judge response: {exc!r}",
        )


# ---------------------------------------------------------------------------
# The scheduler seam, shown as the app layer would call it (loop.py unchanged).
# ---------------------------------------------------------------------------

JudgeEnrich = Callable[[Trace, list[JudgeRequest]], Awaitable[EnrichedTrace]]


async def process_case_seam(
    trace: Trace,
    requests: list[JudgeRequest],
    assertions: list[JudgeAssertion],
    enrich: JudgeEnrich | None,
) -> list[AssertionResult]:
    """A faithful sketch of the ONE change to `scheduler._process_case`:

        trace = await run_case(...)          # unchanged
        if price is not None:                # DF-207 seam, unchanged
            trace = price(trace, case)
        enriched = (await enrich(trace, reqs) # <- NEW: one await, mirrors `price`
                    if enrich and reqs else EnrichedTrace(trace=trace))
        assertions = _evaluate(case.expect, enriched)   # pure, as today

    `loop.py` is not in this call graph at all — the enrichment sits between the
    loop's output and the (pure) assertions, exactly where `price` already sits.
    """
    enriched = (
        await enrich(trace, requests)
        if enrich is not None and requests
        else EnrichedTrace(trace=trace)
    )
    return [a.evaluate(enriched) for a in assertions]

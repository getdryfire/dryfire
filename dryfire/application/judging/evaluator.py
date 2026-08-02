"""The judge evaluator (DF-302) — SPIKE-006's Model C, in the application layer.

`JudgeEvaluator.evaluate(trace, requests)` grades a `Trace` against one or more rubrics
and returns `{assertion_id: JudgeVerdict}`. Every judge call goes through the injected
`ModelGateway` — the *same* port the agent under test uses — so judge calls are
cassette-backed and retried by the EPIC-002 decorators with no second HTTP client and no
second cache. The evaluator is injected (never imports a concrete gateway), so tests
drive it with a fake.

Discipline this module owns:
  - `temperature=0` on every judge call — a judge is an instrument, not a writer.
  - Defensive parsing: an unparseable response is a judge *error*, never a score of 0.
  - A provider exception is caught and turned into a judge error — it never escapes to
    abort a case (the exit-3 routing happens later, at reporting).
  - Judge concurrency is bounded by a single semaphore shared across all `evaluate`
    calls, so N cases × M judges never exceed the bound — independent of case
    concurrency, and a flat gather rather than a nested pool.

Pure-domain purity is preserved: the verdict types are domain values; only the model
call lives here, above the domain.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from dryfire.application.ports.model_gateway import (
    CompletionRequest,
    ModelGateway,
    ModelParams,
)
from dryfire.domain.judging.rubric import Rubric
from dryfire.domain.judging.verdict import JudgeVerdict
from dryfire.domain.model.message import Message, ModelResponse
from dryfire.domain.model.trace import Trace

DEFAULT_JUDGE_CONCURRENCY = 4

_JUDGE_SYSTEM = (
    "You are a strict evaluator grading an AI agent's behaviour against a rubric. "
    "Respond with ONLY a JSON object: {\"score\": <number>, \"reasoning\": <string>}. "
    "The score must follow the rubric's scale. Do not add any text outside the JSON."
)


@dataclass(frozen=True)
class JudgeRequest:
    """One `llm_judge` assertion's grading request. Built from a case's `expect`
    entries by the caller (DF-303); the pure assertion never sees this."""

    assertion_id: str
    rubric: Rubric
    model: str


class JudgeEvaluator:
    """Grades traces via an injected `ModelGateway`, bounding judge concurrency with a
    single shared semaphore. One instance per run (built in composition beside the
    pricing callback), reused across every case."""

    def __init__(
        self, *, gateway: ModelGateway, concurrency: int = DEFAULT_JUDGE_CONCURRENCY,
        sem: asyncio.Semaphore | None = None,
    ) -> None:
        self._gateway = gateway
        # A caller (composition) may inject ONE semaphore shared across per-case
        # evaluators, so the concurrency bound spans the whole run rather than a
        # single case. Absent an injected one, each evaluator bounds itself.
        self._sem = sem if sem is not None else asyncio.Semaphore(concurrency)

    async def evaluate(
        self, trace: Trace, requests: list[JudgeRequest]
    ) -> dict[str, JudgeVerdict]:
        """Grade `trace` against every request concurrently (under the shared bound)
        and return the verdicts keyed by assertion id. An empty request list returns
        an empty dict without touching the gateway — the structural-only fast path."""
        if not requests:
            return {}
        verdicts = await asyncio.gather(*(self._grade(trace, r) for r in requests))
        return {req.assertion_id: verdict
                for req, verdict in zip(requests, verdicts, strict=True)}

    async def _grade(self, trace: Trace, request: JudgeRequest) -> JudgeVerdict:
        async with self._sem:
            try:
                response = await self._gateway.complete(self._build_request(trace, request))
            except Exception as exc:  # noqa: BLE001 - a provider error is a judge error, not a crash
                return JudgeVerdict.from_error(
                    reasoning="", rubric=request.rubric, judge_model=request.model,
                    judge_model_version=request.model,
                    error=f"judge provider call failed: {exc!r}",
                )
            return self._parse(response, request)

    def _build_request(self, trace: Trace, request: JudgeRequest) -> CompletionRequest:
        prompt = (
            f"# Rubric\n{request.rubric.text}\n\n"
            f"# Agent transcript to grade\n{_render_trace(trace)}\n\n"
            "Grade the transcript against the rubric."
        )
        return CompletionRequest(
            model=request.model,
            system=_JUDGE_SYSTEM,
            messages=[Message(role="user", content=prompt)],
            tools=[],
            params=ModelParams(temperature=0),  # always — see module docstring
        )

    def _parse(self, response: ModelResponse, request: JudgeRequest) -> JudgeVerdict:
        version = _served_version(response, request.model)
        try:
            data = _extract_json(response.text or "")
            score = float(data["score"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            # An unparseable answer was still a billed call — keep its usage so the
            # judge cost channel stays accurate.
            return JudgeVerdict.from_error(
                reasoning="", rubric=request.rubric, judge_model=request.model,
                judge_model_version=version, usage=response.usage,
                error=f"unparseable judge response: {exc!r}",
            )
        return JudgeVerdict.from_score(
            score=score, reasoning=str(data.get("reasoning", "")), rubric=request.rubric,
            judge_model=request.model, judge_model_version=version, usage=response.usage,
        )


def _served_version(response: ModelResponse, requested_model: str) -> str:
    """The exact model version the provider served, from the raw payload if it reports
    one (Anthropic/OpenAI both echo `model`), else the requested model — provenance is
    best-effort but never absent (JudgeVerdict requires it)."""
    served = response.raw.get("model")
    return str(served) if served else requested_model


def _render_trace(trace: Trace) -> str:
    """The slice of the trace a judge grades: the final text and the tool trajectory.
    Kept deliberately small and stable — it feeds the cassette fingerprint."""
    tools = " → ".join(trace.tool_names()) or "(none)"
    return f"Final response: {trace.final_text!r}\nTools called: {tools}"


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from a judge response, tolerating a ```json fence or prose
    around it — real judges wrap output despite instructions. Raises JSONDecodeError if
    no object is found, so the caller records a judge error rather than a false score."""
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop a leading ```json / ``` fence and the trailing fence.
        inner = stripped.split("```", 2)
        stripped = inner[1] if len(inner) >= 2 else stripped
        if stripped.startswith("json"):
            stripped = stripped[len("json"):]
        stripped = stripped.strip().rstrip("`").strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("no JSON object found", stripped, 0)
    result = json.loads(stripped[start : end + 1])
    if not isinstance(result, dict):
        raise json.JSONDecodeError("judge response is not a JSON object", stripped, 0)
    return result

"""DF-206 — RetryingGateway: transient failures retried below the loop.

Retries are NOT turns (a SPEC §5 invariant): the loop sees one `complete()` that
either eventually succeeds or raises, never the intermediate attempts. Backoff is
asserted under a FrozenClock, so the whole suite runs in microseconds.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from dryfire.adapters.driven.providers.retrying import RetryingGateway, default_retryable
from dryfire.application.loop import run_case
from dryfire.application.ports.model_gateway import CompletionRequest, ModelGateway
from dryfire.domain.mocking.resolver import MockResolver
from dryfire.domain.model.case import ResolvedCase
from dryfire.domain.model.message import ModelResponse, Usage

_Req = Callable[..., CompletionRequest]


def _resp(text: str = "ok") -> ModelResponse:
    return ModelResponse(
        text=text, tool_calls=[], stop_reason="end_turn",
        usage=Usage(input_tokens=1, output_tokens=1), latency_ms=1, raw={},
    )


class FrozenClock:
    """Records requested sleeps and returns immediately — no real waiting."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class _HttpError(Exception):
    """A vendor-shaped error: a status_code, optionally a Retry-After header."""

    def __init__(self, status_code: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code
        if retry_after is not None:
            self.response = SimpleNamespace(headers={"retry-after": str(retry_after)})


class _FlakyGateway:
    name = "anthropic"

    def __init__(self, fail_times: int, exc: Exception, then: ModelResponse | None = None) -> None:
        self.fail_times = fail_times
        self.exc = exc
        self.calls = 0
        self._then = then or _resp()

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self._then

    def is_retryable(self, exc: Exception) -> bool:
        return default_retryable(exc)


def _retrying(inner: Any, clock: FrozenClock, **kw: Any) -> RetryingGateway:
    kw.setdefault("max_retries", 3)
    kw.setdefault("base_delay", 0.5)
    kw.setdefault("jitter", lambda d: d)  # deterministic: no jitter in tests
    return RetryingGateway(inner, clock=clock, **kw)


def test_conforms_to_the_model_gateway_port() -> None:
    gw = _retrying(_FlakyGateway(0, _HttpError(500)), FrozenClock())
    assert isinstance(gw, ModelGateway)
    assert gw.name == "anthropic"


async def test_429_then_success_makes_one_extra_call(make_request: _Req) -> None:
    inner = _FlakyGateway(fail_times=1, exc=_HttpError(429), then=_resp("recovered"))
    clock = FrozenClock()
    resp = await _retrying(inner, clock).complete(make_request())
    assert resp.text == "recovered"
    assert inner.calls == 2  # one failure, one success
    assert clock.sleeps == [0.5]  # one backoff


async def test_401_is_not_retried(make_request: _Req) -> None:
    inner = _FlakyGateway(fail_times=99, exc=_HttpError(401))
    clock = FrozenClock()
    with pytest.raises(_HttpError):
        await _retrying(inner, clock).complete(make_request())
    assert inner.calls == 1  # auth failures are not transient
    assert clock.sleeps == []


async def test_backoff_sequence_is_exponential(make_request: _Req) -> None:
    inner = _FlakyGateway(fail_times=99, exc=_HttpError(503))
    clock = FrozenClock()
    with pytest.raises(_HttpError):
        await _retrying(inner, clock, max_retries=3).complete(make_request())
    assert clock.sleeps == [0.5, 1.0, 2.0]  # base * 2**attempt
    assert inner.calls == 4  # 1 initial + 3 retries


async def test_retry_after_header_is_honoured(make_request: _Req) -> None:
    inner = _FlakyGateway(fail_times=1, exc=_HttpError(503, retry_after=7), then=_resp())
    clock = FrozenClock()
    await _retrying(inner, clock).complete(make_request())
    assert clock.sleeps == [7.0]  # Retry-After overrides the backoff


async def test_an_inner_without_is_retryable_is_not_retried(make_request: _Req) -> None:
    class _Bare:
        name = "x"

        async def complete(self, request: CompletionRequest) -> ModelResponse:
            raise ConnectionError("boom")

    clock = FrozenClock()
    with pytest.raises(ConnectionError):
        await _retrying(_Bare(), clock).complete(make_request())
    assert clock.sleeps == []


# -- The SPEC §5 invariant: retries are not turns ---------------------------


def _resolved_case(**over: Any) -> ResolvedCase:
    base: dict[str, Any] = dict(
        suite_name="s", case_name="c", suite_path=__import__("pathlib").Path("s.yaml"),
        provider="anthropic", model="m", max_turns=10, temperature=0.0,
        on_unmocked="error", system=None, input="hi", expect=[], tools=[],
    )
    base.update(over)
    return ResolvedCase(**base)


async def test_a_retried_call_is_still_one_turn() -> None:
    inner = _FlakyGateway(fail_times=2, exc=_HttpError(500), then=_resp("done"))
    gateway = _retrying(inner, FrozenClock())
    trace = await run_case(_resolved_case(), gateway, MockResolver({}))
    assert len(trace.turns) == 1  # two retries, but one turn
    assert trace.termination == "end_turn"


async def test_exhausted_retries_become_a_provider_error() -> None:
    inner = _FlakyGateway(fail_times=99, exc=_HttpError(500))
    gateway = _retrying(inner, FrozenClock(), max_retries=2)
    trace = await run_case(_resolved_case(), gateway, MockResolver({}))
    assert trace.termination == "provider_error"
    assert len(trace.turns) == 0

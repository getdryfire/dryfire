"""RetryingGateway — transient-failure retries as a decorator over ModelGateway
(DF-206). Like caching, this keeps `application/loop.py` unchanged: the loop calls
`complete()` once and sees either an eventual success or the propagated final
error. Retries are invisible to the loop, so **a retried call is still one turn**.

Composition order is fixed to `Caching(Retrying(Real))`: retries wrap only live
calls, and a cache hit returns before ever reaching this layer.

The decorator holds no vendor knowledge. It asks the wrapped gateway
`is_retryable(exc)` and backs off; classification lives in each provider adapter.
`default_retryable` is the shared HTTP-shaped policy both v0.2 providers use.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from dryfire.application.ports.clock import Clock
from dryfire.application.ports.model_gateway import CompletionRequest, ModelGateway
from dryfire.domain.model.message import ModelResponse


def default_retryable(exc: Exception) -> bool:
    """Retry a 429, any 5xx, or a connection/timeout failure — never a 4xx-other
    (auth, malformed request), where retrying only wastes time and hides a bug.
    Duck-typed on `status_code` so no provider SDK is imported here."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    return type(exc).__name__ in {
        "APIConnectionError", "APITimeoutError", "APIConnectionTimeoutError",
    }


def _retry_after(exc: Exception) -> float | None:
    """The provider's Retry-After in seconds, if it sent one. HTTP-date form is
    unsupported and falls back to normal backoff."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _equal_jitter(delay: float) -> float:
    """Half fixed, half random — spreads retries without collapsing to zero."""
    return delay / 2 + random.random() * delay / 2


class RetryingGateway:
    """Wraps a `ModelGateway`, retrying transient failures with exponential
    backoff. One instance can be shared across cases — it holds no per-call state."""

    def __init__(
        self,
        inner: ModelGateway,
        *,
        clock: Clock,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 60.0,
        jitter: Callable[[float], float] = _equal_jitter,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._jitter = jitter
        self.name: str = inner.name

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        attempt = 0
        while True:
            try:
                return await self._inner.complete(request)
            except Exception as exc:
                if attempt >= self._max_retries or not self.is_retryable(exc):
                    raise  # exhausted or not transient → the loop records provider_error
                await self._clock.sleep(self._delay(attempt, exc))
                attempt += 1

    def is_retryable(self, exc: Exception) -> bool:
        classify = getattr(self._inner, "is_retryable", None)
        return bool(classify(exc)) if callable(classify) else False

    def _delay(self, attempt: int, exc: Exception) -> float:
        after = _retry_after(exc)
        if after is not None:
            return after
        return self._jitter(min(self._max_delay, self._base_delay * (2**attempt)))

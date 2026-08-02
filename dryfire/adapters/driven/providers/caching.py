"""CachingGateway — cassette record/replay as a decorator over ModelGateway (DF-204).

This is the ticket that proves the architecture: cassettes land as a wrapper over
the `ModelGateway` port with **zero changes to `application/loop.py`**. Nothing
above the port learns that caching exists — the loop calls `complete()` and stores
the `ModelResponse` it gets back, whether that came from a live call or a cassette.

Composition order is fixed: `Caching(Retrying(Real))` (ARCHITECTURE §6). A cache
hit returns before ever reaching the retry layer, and retries apply only to live
calls. This class only wraps *a* gateway; that ordering is enforced where the
gateways are wired (`composition.py`).

The four modes (SPEC §9):

    auto    miss → live call + record; hit → serve from cassette
    record  always live, overwrite the cassette
    replay  hit → serve; **miss → CassetteMiss (never a live call)**
    off     bypass entirely

A `replay` miss raising `CassetteMiss` needs no special handling in the loop: the
loop already turns any `complete()` exception into a `provider_error` termination,
which maps to exit code 3 — exactly what SPEC §9 requires for a replay miss.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from dryfire.adapters.driven.spec.models import CassetteMode
from dryfire.application.ports.model_gateway import CompletionRequest, ModelGateway
from dryfire.application.ports.response_cache import CassetteRecord, ResponseCache
from dryfire.domain.fingerprint import fingerprint, hashable_request, storage_key
from dryfire.domain.model.message import Message, ModelResponse


class CassetteMiss(RuntimeError):
    """Raised in `replay` mode when no cassette matches the request. Carries the
    fingerprint and case so the failure names exactly what to record. The loop
    records this as `provider_error` → exit 3, without knowing about cassettes."""

    def __init__(self, *, fingerprint: str, suite: str, case: str) -> None:
        super().__init__(
            f"cassette miss in replay mode: no recording for {suite}::{case} "
            f"(fingerprint {fingerprint}). Record it with --cassette-mode=record."
        )
        self.fingerprint = fingerprint
        self.suite = suite
        self.case = case


def _reduce_message(message: Message) -> dict[str, Any]:
    """A message reduced to what reaches the model — `raw` (the provider's opaque
    passthrough, full of non-reproducible ids) is deliberately excluded."""
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": [call.model_dump() for call in message.tool_calls],
        "tool_results": [result.model_dump() for result in message.tool_results],
    }


def _hash_args(request: CompletionRequest, provider: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": request.model,
        "system": request.system,
        "messages": [_reduce_message(m) for m in request.messages],
        "tools": [tool.model_dump() for tool in request.tools],
        "params": request.params.model_dump(),
    }


class CachingGateway:
    """Wraps a `ModelGateway`, adding cassette record/replay. One instance per
    case (it carries the suite/case identity and a per-case turn counter); the
    wrapped gateway may be shared across cases."""

    def __init__(
        self,
        inner: ModelGateway,
        store: ResponseCache,
        *,
        mode: CassetteMode,
        suite: str,
        case: str,
        repeat_index: int = 0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._inner = inner
        self._store = store
        self._mode = mode
        self._suite = suite
        self._case = case
        # One CachingGateway per repetition (DF-306): its `repeat_index` is fixed for
        # every turn of that run, so a multi-turn repeated case keys all its turns under
        # the same index and replay never mispairs. Index 0 → the bare v0.2 key.
        self._repeat_index = repeat_index
        self._now = now
        self._turn = 0
        # Provider passes through so the fingerprint and downstream logic see the
        # real provider, not a "caching" pseudo-provider.
        self.name: str = inner.name

    def is_retryable(self, exc: Exception) -> bool:
        # Caching is the OUTERMOST decorator (Caching(Retrying(Real))), so this is
        # never consulted; retries live below it. Present only for port conformance.
        return False

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        if self._mode == "off":
            return await self._inner.complete(request)

        args = _hash_args(request, self.name)
        # The repetition index lives in the storage key, not the hash (SPIKE-007): the
        # fingerprint is unchanged, and index 0 leaves the key byte-identical to v0.2.
        key = storage_key(fingerprint(**args), self._repeat_index)
        turn = self._turn
        self._turn += 1

        if self._mode != "record":  # auto / replay both consult the cassette first
            cached = self._store.get(key)
            if cached is not None:
                return cached.model_copy(update={"cache_hit": True})
            if self._mode == "replay":
                raise CassetteMiss(fingerprint=key, suite=self._suite, case=self._case)

        response = await self._inner.complete(request)  # live: auto-miss or record
        self._store.put(
            CassetteRecord(
                fingerprint=key,
                suite=self._suite,
                case=self._case,
                turn=turn,
                provider=self.name,
                model=request.model,
                request_digest=hashable_request(**args),
                response=response,
            ),
            recorded_at=self._now(),
        )
        return response

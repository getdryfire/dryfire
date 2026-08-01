"""DF-203 — the ResponseCache port contract.

Every ResponseCache implementation must round-trip a response by fingerprint and
return None on a miss. Run against the real FileCassetteStore and an InMemoryCache
fake, so the two can never drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dryfire.adapters.driven.cache.file_store import FileCassetteStore
from dryfire.application.ports.response_cache import CassetteRecord, ResponseCache
from dryfire.domain.model.message import ModelResponse, Usage

FIXED = datetime(2026, 7, 30, 14, 22, 10, tzinfo=UTC)


class InMemoryCache:
    """A ResponseCache backed by a dict — keyed by fingerprint alone, exactly as
    the port promises reads to be."""

    def __init__(self) -> None:
        self._store: dict[str, ModelResponse] = {}

    def get(self, fingerprint: str) -> ModelResponse | None:
        return self._store.get(fingerprint)

    def put(self, record: CassetteRecord, *, recorded_at: datetime) -> None:
        self._store[record.fingerprint] = record.response


def _response(text: str = "hi") -> ModelResponse:
    return ModelResponse(
        text=text,
        tool_calls=[],
        stop_reason="end_turn",
        usage=Usage(input_tokens=3, output_tokens=5),
        latency_ms=42,
        raw={"id": "msg_1"},
    )


def _record(fingerprint: str = "f0b4fbe056178ff6", **over: Any) -> CassetteRecord:
    base: dict[str, Any] = dict(
        fingerprint=fingerprint,
        suite="refund_agent",
        case="escalates_refund_over_limit",
        turn=0,
        provider="anthropic",
        model="claude-sonnet-4-6",
        request_digest={"model": "claude-sonnet-4-6", "messages": []},
        response=_response(),
    )
    base.update(over)
    return CassetteRecord(**base)


@pytest.fixture(params=["file", "memory"])
def cache(request: pytest.FixtureRequest, tmp_path: Path) -> ResponseCache:
    if request.param == "file":
        return FileCassetteStore(tmp_path / "cassettes")
    return InMemoryCache()


def test_conforms_to_the_port(cache: ResponseCache) -> None:
    assert isinstance(cache, ResponseCache)


def test_put_then_get_round_trips(cache: ResponseCache) -> None:
    record = _record()
    cache.put(record, recorded_at=FIXED)
    assert cache.get(record.fingerprint) == record.response


def test_get_on_a_miss_returns_none(cache: ResponseCache) -> None:
    assert cache.get("deadbeefdeadbeef") is None


def test_last_write_wins_for_a_fingerprint(cache: ResponseCache) -> None:
    cache.put(_record(response=_response("first")), recorded_at=FIXED)
    cache.put(_record(response=_response("second")), recorded_at=FIXED)
    got = cache.get("f0b4fbe056178ff6")
    assert got is not None and got.text == "second"

"""DF-204 — CachingGateway: cassettes as a decorator over ModelGateway.

The loop never learns caching exists (see the empty `git diff application/loop.py`
in this ticket). These tests pin the four modes, the replay airgap (a miss never
reaches the wrapped gateway), and multi-turn replay (the SPIKE-002 failure mode).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dryfire.adapters.driven.cache.file_store import FileCassetteStore
from dryfire.adapters.driven.providers.caching import CachingGateway, CassetteMiss
from dryfire.adapters.driven.spec.models import CassetteMode
from dryfire.application.ports.model_gateway import CompletionRequest, ModelGateway
from dryfire.domain.model.message import ModelResponse, Usage

_Req = Callable[..., CompletionRequest]
FIXED = datetime(2026, 7, 30, 14, 22, 10, tzinfo=UTC)


def _resp(text: str) -> ModelResponse:
    return ModelResponse(
        text=text, tool_calls=[], stop_reason="end_turn",
        usage=Usage(input_tokens=1, output_tokens=1), latency_ms=7, raw={"id": "x"},
    )


class _CountingGateway:
    """A stand-in real gateway: counts calls, returns a fixed response, or raises
    (to prove replay never touches it)."""

    name = "anthropic"

    def __init__(self, response: ModelResponse | None = None, raises: Exception | None = None):
        self.calls = 0
        self._response = response or _resp("live")
        self._raises = raises

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._response


def _caching(inner: Any, store: Any, mode: CassetteMode) -> CachingGateway:
    return CachingGateway(inner, store, mode=mode, suite="refunds", case="over_limit",
                          now=lambda: FIXED)


def _store(tmp_path: Path) -> FileCassetteStore:
    return FileCassetteStore(tmp_path / "cassettes")


def test_conforms_to_the_model_gateway_port(tmp_path: Path) -> None:
    gw = _caching(_CountingGateway(), _store(tmp_path), "off")
    assert isinstance(gw, ModelGateway)
    assert gw.name == "anthropic"  # provider passes through for the fingerprint


async def test_off_bypasses_the_cache(tmp_path: Path, make_request: _Req) -> None:
    inner = _CountingGateway(_resp("live"))
    gw = _caching(inner, _store(tmp_path), "off")
    resp = await gw.complete(make_request("hi"))
    assert resp.text == "live" and resp.cache_hit is False
    assert inner.calls == 1
    assert list((tmp_path / "cassettes").rglob("*.json")) == []  # nothing recorded


async def test_record_always_calls_live_and_writes(tmp_path: Path, make_request: _Req) -> None:
    inner = _CountingGateway(_resp("live"))
    gw = _caching(inner, _store(tmp_path), "record")
    resp = await gw.complete(make_request("hi"))
    assert resp.cache_hit is False and inner.calls == 1
    assert len(list((tmp_path / "cassettes").rglob("*.json"))) == 1
    await gw.complete(make_request("hi"))  # record overwrites, calls live again
    assert inner.calls == 2


async def test_auto_records_on_miss_then_hits(tmp_path: Path, make_request: _Req) -> None:
    store = _store(tmp_path)
    inner1 = _CountingGateway(_resp("live"))
    first = await _caching(inner1, store, "auto").complete(make_request("hi"))
    assert first.cache_hit is False and inner1.calls == 1

    inner2 = _CountingGateway(_resp("SHOULD NOT BE USED"))
    second = await _caching(inner2, store, "auto").complete(make_request("hi"))
    assert second.cache_hit is True and second.text == "live"
    assert inner2.calls == 0  # served from the cassette


async def test_replay_hit_returns_cached_without_calling_inner(
    tmp_path: Path, make_request: _Req
) -> None:
    store = _store(tmp_path)
    await _caching(_CountingGateway(_resp("live")), store, "record").complete(make_request("hi"))

    # In replay the inner gateway would raise if touched — prove it is not.
    inner = _CountingGateway(raises=ConnectionError("network is off"))
    resp = await _caching(inner, store, "replay").complete(make_request("hi"))
    assert resp.cache_hit is True and resp.text == "live"
    assert inner.calls == 0


async def test_replay_miss_raises_cassette_miss_naming_case(
    tmp_path: Path, make_request: _Req
) -> None:
    inner = _CountingGateway(raises=ConnectionError("network is off"))
    gw = _caching(inner, _store(tmp_path), "replay")
    with pytest.raises(CassetteMiss) as exc:
        await gw.complete(make_request("hi"))
    assert "refunds" in str(exc.value) and "over_limit" in str(exc.value)
    assert inner.calls == 0  # airgap: a miss never reaches the wrapped gateway


async def test_multi_turn_records_and_replays_every_turn(
    tmp_path: Path, make_request: _Req
) -> None:
    store = _store(tmp_path)
    rec = _caching(_CountingGateway(_resp("live")), store, "record")
    await rec.complete(make_request("turn 0"))
    await rec.complete(make_request("turn 1"))  # distinct request → distinct cassette
    assert len(list((tmp_path / "cassettes").rglob("*.json"))) == 2

    inner = _CountingGateway(raises=ConnectionError("network is off"))
    play = _caching(inner, store, "replay")
    assert (await play.complete(make_request("turn 0"))).cache_hit is True
    assert (await play.complete(make_request("turn 1"))).cache_hit is True
    assert inner.calls == 0

"""DF-306 — repetition-aware cassette keys on the real store (EPIC-003, SPIKE-007).

The failure this ticket exists to prevent: if every repetition of a `repeat: N` case
keyed by the bare fingerprint, replay would serve one response N times and every pass
rate would become a comforting `N/N` lie. Here the CachingGateway carries a per-run
`repeat_index`, so repetition i records/replays under `storage_key(fp, i)` — N distinct
cassettes — while `repeat: 1` (index 0) stays byte-for-byte compatible with v0.2.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dryfire.adapters.driven.cache.file_store import FileCassetteStore
from dryfire.adapters.driven.cache.prune import find_prunable
from dryfire.adapters.driven.providers.caching import CachingGateway, CassetteMiss
from dryfire.application.ports.model_gateway import CompletionRequest, ModelParams
from dryfire.domain.model.message import Message, ModelResponse, Usage

_V0_2_FIXTURE = Path(__file__).parents[2] / "fixtures" / "cassettes_v0_2"


def _request() -> CompletionRequest:
    return CompletionRequest(
        model="claude-sonnet-4-6", system="be helpful",
        messages=[Message(role="user", content="ping")], tools=[],
        params=ModelParams(temperature=0),
    )


class _Live:
    """A gateway returning a distinct response per call, to record N distinct cassettes."""

    name = "anthropic"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def is_retryable(self, exc: Exception) -> bool:
        return False

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        text = self._responses[self.calls]
        self.calls += 1
        return ModelResponse(text=text, tool_calls=[], stop_reason="end_turn",
                             usage=Usage(input_tokens=1, output_tokens=1), latency_ms=1, raw={})


class _NoLive:
    name = "anthropic"

    def is_retryable(self, exc: Exception) -> bool:
        return False

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        raise AssertionError("replay must not make a live call")


def _caching(inner: object, store: FileCassetteStore, *, mode: str, i: int) -> CachingGateway:
    return CachingGateway(inner, store, mode=mode, suite="s", case="c", repeat_index=i)  # type: ignore[arg-type]


def _complete(gw: CachingGateway) -> ModelResponse:
    return asyncio.run(gw.complete(_request()))


def _record_first_three(store: FileCassetteStore) -> None:
    live = _Live([f"r{i}" for i in range(3)])
    for i in range(3):
        _complete(_caching(live, store, mode="record", i=i))


def _record_all_five(store: FileCassetteStore) -> None:
    live = _Live([f"r{i}" for i in range(5)])
    for i in range(5):
        _complete(_caching(live, store, mode="record", i=i))


# -- The must-have test: five repetitions replay five DISTINCT responses ------


def test_repeat_5_replay_yields_five_distinct_responses(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    recorded = [f"response-{i}" for i in range(5)]

    # Record: repetition i, through its own CachingGateway(repeat_index=i), stores its
    # own response under storage_key(fp, i).
    live = _Live(recorded)
    for i in range(5):
        assert _complete(_caching(live, store, mode="auto", i=i)).text == recorded[i]

    # Replay: repetition i reads back its OWN response — asserted individually, not by
    # count, because "5 identical responses" would also have length 5 and be the lie.
    replayed = [_complete(_caching(_NoLive(), store, mode="replay", i=i)).text for i in range(5)]
    assert replayed == recorded
    assert len(set(replayed)) == 5


def test_off_mode_bypasses_the_store_entirely(tmp_path: Path) -> None:
    # off: cassettes are not consulted or written — each repetition goes live.
    store = FileCassetteStore(tmp_path)
    live = _Live(["x", "y"])
    assert _complete(_caching(live, store, mode="off", i=0)).text == "x"
    assert _complete(_caching(live, store, mode="off", i=1)).text == "y"
    assert list(tmp_path.rglob("*.json")) == []  # nothing stored


def test_repeat_1_key_is_byte_identical_to_v0_2(tmp_path: Path) -> None:
    # A repeat_index-0 gateway records under the bare fingerprint — the v0.2 filename.
    store = FileCassetteStore(tmp_path)
    _complete(_caching(_Live(["only"]), store, mode="auto", i=0))
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    assert "#" not in files[0].name  # no repetition suffix at index 0


# -- A committed v0.2 cassette still replays under v0.3 ----------------------


def test_committed_v0_2_cassette_replays_under_v0_3() -> None:
    # The fixture was recorded before DF-306 (bare-fingerprint filename, schema 1). A
    # repeat_index-0 replay must still find and serve it — existing cassettes stay valid.
    store = FileCassetteStore(_V0_2_FIXTURE)
    got = _complete(_caching(_NoLive(), store, mode="replay", i=0))
    assert got.text == "pong (recorded under v0.2)"
    assert got.cache_hit


# -- Partial cassettes (3 of 5 recorded) in each mode -----------------------


def test_partial_cassette_replay_serves_present_and_errors_on_missing(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    _record_first_three(store)
    # Repetitions 0–2 replay; 3–4 miss → CassetteMiss (exit 3), never a fabricated rate.
    for i in range(3):
        assert _complete(_caching(_NoLive(), store, mode="replay", i=i)).text == f"r{i}"
    for i in (3, 4):
        with pytest.raises(CassetteMiss):
            _complete(_caching(_NoLive(), store, mode="replay", i=i))


def test_partial_cassette_auto_backfills_the_missing_repetitions(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    _record_first_three(store)
    # auto: 0–2 serve from cassette (no live call); 3–4 go live and record.
    served = _Live([])  # would IndexError if called for a hit
    for i in range(3):
        assert _complete(_caching(served, store, mode="auto", i=i)).text == f"r{i}"
    assert served.calls == 0
    backfill = _Live(["r3", "r4"])
    assert _complete(_caching(backfill, store, mode="auto", i=3)).text == "r3"
    assert _complete(_caching(backfill, store, mode="auto", i=4)).text == "r4"


# -- prune keeps / removes repetition cassettes by case validity ------------


def test_prune_keeps_repetition_cassettes_of_a_valid_case(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    _record_all_five(store)
    candidates = find_prunable(tmp_path, {"s": {"c"}}, had_parse_failure=False)
    assert candidates == []  # all five repetition cassettes are live — none orphaned


def test_prune_removes_repetition_cassettes_of_an_orphaned_case(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    _record_all_five(store)
    # The case no longer exists → all of its cassettes (bare + every #i) are candidates.
    candidates = find_prunable(tmp_path, {"s": set()}, had_parse_failure=False)
    assert len(candidates) == 5

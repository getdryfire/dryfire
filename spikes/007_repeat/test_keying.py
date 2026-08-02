"""SPIKE-007 proof — the repetition-aware scheme preserves every SPIKE-002 property
and stores N distinct responses per logical request.

Not collected by `make test` (pytest `testpaths = ["tests"]`); run explicitly:

    uv run pytest spikes/007_repeat/test_keying.py -q

Part 1 re-runs SPIKE-002's 19 stability + sensitivity tests against the modified
scheme — which, because the index lives in the storage key and not the hash, means
`fingerprint()` is unchanged and they pass by construction. Part 2 covers the new
repetition behaviour and the partial-cassette policy in all four modes.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from keying import fingerprint, parse_storage_key, storage_key  # noqa: E402

BASE: dict[str, Any] = dict(
    provider="anthropic",
    model="claude-sonnet-4-6",
    system="You are a support agent. Never refund over $500.",
    messages=[{"role": "user", "content": "Refund order A-991"}],
    tools=[
        {"name": "lookup_order", "description": "Retrieve order details by order ID.",
         "input_schema": {"type": "object",
                          "properties": {"order_id": {"type": "string"}},
                          "required": ["order_id"]}},
        {"name": "issue_refund", "description": "Issue a refund.",
         "input_schema": {"type": "object", "properties": {"amount": {"type": "number"}}}},
    ],
    params={"temperature": 0, "max_tokens": 1024},
)


def fp(**overrides: Any) -> str:
    req = copy.deepcopy(BASE)
    req.update(overrides)
    return fingerprint(**req)


BASELINE = fp()


# == Part 1: SPIKE-002's 19 tests, re-run against the modified scheme ========
# STABILITY — must NOT change the fingerprint


def test_stable_across_dict_key_order() -> None:
    tools = [{"input_schema": BASE["tools"][0]["input_schema"],
              "description": BASE["tools"][0]["description"], "name": "lookup_order"},
             BASE["tools"][1]]
    assert fp(tools=tools) == BASELINE


def test_stable_across_nested_key_order() -> None:
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["input_schema"] = {"required": ["order_id"],
                                "properties": {"order_id": {"type": "string"}},
                                "type": "object"}
    assert fp(tools=tools) == BASELINE


def test_stable_across_extraneous_request_metadata() -> None:
    req = copy.deepcopy(BASE)
    req["params"] = {**BASE["params"], "api_key": "sk-ant-SECRET", "request_id": "req_0192",
                     "timestamp": "2026-07-30T12:00:00Z", "user_agent": "dryfire/0.1.3"}
    assert fingerprint(**req) == BASELINE


def test_stable_across_provider_generated_call_ids() -> None:
    def convo(call_id: str) -> list[dict[str, Any]]:
        return [
            {"role": "user", "content": "Refund order A-991"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": call_id, "name": "lookup_order",
                 "input": {"order_id": "A-991"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": '{"total": 780.0}'}]},
        ]
    assert fp(messages=convo("toolu_01ABCdefGHI")) == fp(messages=convo("toolu_99ZZZzzzYYY"))


def test_stable_across_unicode_normalisation_form() -> None:
    assert fp(system="café order") == fp(system="café order")


# SENSITIVITY — must change the fingerprint


@pytest.mark.parametrize("overrides", [
    pytest.param({"model": "claude-opus-4-1"}, id="model"),
    pytest.param({"system": "You are a support agent. Never refund over $500. "},
                 id="system_trailing_whitespace"),
    pytest.param({"system": "You are a rude agent."}, id="system_content"),
    pytest.param({"provider": "openai"}, id="provider"),
    pytest.param({"messages": [{"role": "user", "content": "Refund order A-992"}]},
                 id="message_content"),
    pytest.param({"params": {"temperature": 0.7, "max_tokens": 1024}}, id="temperature"),
    pytest.param({"params": {"temperature": 0, "max_tokens": 2048}}, id="max_tokens"),
    pytest.param({"params": {"temperature": 0, "max_tokens": 1024, "top_p": 0.9}}, id="top_p"),
])
def test_sensitive_to_request_changes(overrides: dict[str, Any]) -> None:
    assert fp(**overrides) != BASELINE


def test_sensitive_to_tool_name() -> None:
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["name"] = "lookup_order_v2"
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_description() -> None:
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["description"] = "Retrieve order details. Always call this first."
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_input_schema() -> None:
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["input_schema"]["properties"]["order_id"]["type"] = "integer"
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_order() -> None:
    assert fp(tools=list(reversed(copy.deepcopy(BASE["tools"])))) != BASELINE


def test_sensitive_to_int_vs_float() -> None:
    a = fp(messages=[{"role": "user", "content": "x", "meta": {"amount": 780}}])
    b = fp(messages=[{"role": "user", "content": "x", "meta": {"amount": 780.0}}])
    assert a != b


def test_fingerprint_is_deterministic_in_process() -> None:
    assert fp() == fp() == BASELINE
    assert len(BASELINE) == 16
    int(BASELINE, 16)


# == Part 2: repetition keying (the new behaviour) ===========================


def test_repeat_one_is_byte_identical_to_v2() -> None:
    # repeat: 1 == repeat_index 0 → the key IS the fingerprint, so v0.2 cassettes
    # remain valid without migration.
    assert storage_key(BASELINE, 0) == BASELINE


def test_each_repetition_gets_a_distinct_key() -> None:
    keys = [storage_key(BASELINE, i) for i in range(5)]
    assert len(set(keys)) == 5  # five distinct storage slots for five repetitions
    assert keys[0] == BASELINE   # the first is still the bare fingerprint


def test_storage_key_round_trips() -> None:
    for i in range(5):
        assert parse_storage_key(storage_key(BASELINE, i)) == (BASELINE, i)


def test_negative_index_is_rejected() -> None:
    with pytest.raises(ValueError):
        storage_key(BASELINE, -1)


# -- record → replay of N distinct responses (the failure this prevents) -----


class _SimStore:
    """A minimal cassette store: maps storage key → recorded response string."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def put(self, key: str, response: str) -> None:
        self._data[key] = response


def test_five_distinct_responses_record_and_replay_in_order() -> None:
    store = _SimStore()
    responses = [f"response-{i}" for i in range(5)]

    # Record: repetition i writes its own response under its own key.
    for i, r in enumerate(responses):
        store.put(storage_key(BASELINE, i), r)

    # Replay: repetition i reads back its OWN response — not response-0 five times.
    replayed = [store.get(storage_key(BASELINE, i)) for i in range(5)]
    assert replayed == responses  # five distinct, in order


def test_without_the_index_all_repetitions_would_collide() -> None:
    # The bug the scheme exists to prevent: key everything by the bare fingerprint and
    # every repetition overwrites the last, so replay yields one response N times and
    # every pass rate becomes a comforting N/N lie.
    store = _SimStore()
    for i in range(5):
        store.put(BASELINE, f"response-{i}")  # WRONG: no index
    replayed = [store.get(BASELINE) for _ in range(5)]
    assert replayed == ["response-4"] * 5  # all identical — the lie, demonstrated


# -- partial cassettes (3 of 5) in each of the four modes --------------------


def _action(mode: str, recorded: set[int], index: int) -> str:
    """The DF-204 mode table applied per repetition storage key. Nothing new — the
    per-index key means a missing repetition behaves exactly like any cassette miss."""
    present = index in recorded
    if mode == "off":
        return "live"  # cassettes bypassed entirely
    if mode == "record":
        return "live+record"  # always overwrite
    if mode == "auto":
        return "serve" if present else "live+record"  # backfill the gaps live
    if mode == "replay":
        return "serve" if present else "miss_error"  # refuse to fabricate
    raise AssertionError(mode)


@pytest.mark.parametrize("mode, expected", [
    ("off", ["live"] * 5),
    ("record", ["live+record"] * 5),
    ("auto", ["serve", "serve", "serve", "live+record", "live+record"]),
    ("replay", ["serve", "serve", "serve", "miss_error", "miss_error"]),
])
def test_partial_cassette_policy_per_mode(mode: str, expected: list[str]) -> None:
    recorded = {0, 1, 2}  # 3 of 5 recorded
    assert [_action(mode, recorded, i) for i in range(5)] == expected


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

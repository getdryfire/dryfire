"""DF-202 — request fingerprinting for cassette storage (SPEC §9, SPIKE-002).

Ported from `spikes/002_cassette_fingerprint/test_stability.py` (the 19 stability +
sensitivity tests), plus DF-202's two additional acceptance tests: cross-process
determinism verified in a real subprocess, and stability across a real multi-turn
conversation whose provider-generated tool-call ids differ.

A cassette key must be STABLE under changes that cannot reach the model and
SENSITIVE to anything that does; a false-stable key replays a stale response and
turns green while shipping a regression. Every judgement call resolves toward
sensitivity.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from typing import Any

import pytest

from dryfire.domain.fingerprint import fingerprint, parse_storage_key, storage_key

BASE: dict[str, Any] = dict(
    provider="anthropic",
    model="claude-sonnet-4-6",
    system="You are a support agent. Never refund over $500.",
    messages=[{"role": "user", "content": "Refund order A-991"}],
    tools=[
        {
            "name": "lookup_order",
            "description": "Retrieve order details by order ID.",
            "input_schema": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
        {
            "name": "issue_refund",
            "description": "Issue a refund.",
            "input_schema": {
                "type": "object",
                "properties": {"amount": {"type": "number"}},
            },
        },
    ],
    params={"temperature": 0, "max_tokens": 1024},
)


def fp(**overrides: Any) -> str:
    req = copy.deepcopy(BASE)
    req.update(overrides)
    return fingerprint(**req)


BASELINE = fp()


# ==========================================================================
# STABILITY -- these must NOT change the fingerprint
# ==========================================================================


def test_stable_across_dict_key_order() -> None:
    tools = [
        {
            "input_schema": BASE["tools"][0]["input_schema"],
            "description": BASE["tools"][0]["description"],
            "name": "lookup_order",
        },
        BASE["tools"][1],
    ]
    assert fp(tools=tools) == BASELINE


def test_stable_across_nested_key_order() -> None:
    schema = {
        "required": ["order_id"],
        "properties": {"order_id": {"type": "string"}},
        "type": "object",
    }
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["input_schema"] = schema
    assert fp(tools=tools) == BASELINE


def test_stable_across_extraneous_request_metadata() -> None:
    """API keys, headers, request ids, timestamps never enter the hash."""
    req = copy.deepcopy(BASE)
    req["params"] = {
        **BASE["params"],
        "api_key": "sk-ant-SECRET",
        "request_id": "req_0192",
        "timestamp": "2026-07-30T12:00:00Z",
        "user_agent": "dryfire/0.1.3",
    }
    assert fingerprint(**req) == BASELINE


def test_stable_across_provider_generated_call_ids() -> None:
    """THE critical case: turn 2+ echoes non-reproducible tool-call ids."""

    def convo(call_id: str) -> list[dict[str, Any]]:
        return [
            {"role": "user", "content": "Refund order A-991"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": "lookup_order",
                        "input": {"order_id": "A-991"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": '{"total": 780.0}',
                    }
                ],
            },
        ]

    a = fp(messages=convo("toolu_01ABCdefGHI"))
    b = fp(messages=convo("toolu_99ZZZzzzYYY"))
    assert a == b


def test_stable_across_unicode_normalisation_form() -> None:
    nfc = "café order"  # é as one codepoint
    nfd = "café order"  # e + combining acute
    assert fp(system=nfc) == fp(system=nfd)


# ==========================================================================
# SENSITIVITY -- these MUST change the fingerprint
# ==========================================================================


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"model": "claude-opus-4-1"}, id="model"),
        pytest.param(
            {"system": "You are a support agent. Never refund over $500. "},
            id="system_trailing_whitespace",
        ),
        pytest.param({"system": "You are a rude agent."}, id="system_content"),
        pytest.param({"provider": "openai"}, id="provider"),
        pytest.param(
            {"messages": [{"role": "user", "content": "Refund order A-992"}]},
            id="message_content",
        ),
        pytest.param({"params": {"temperature": 0.7, "max_tokens": 1024}}, id="temperature"),
        pytest.param({"params": {"temperature": 0, "max_tokens": 2048}}, id="max_tokens"),
        pytest.param(
            {"params": {"temperature": 0, "max_tokens": 1024, "top_p": 0.9}},
            id="top_p_added",
        ),
    ],
)
def test_sensitive_to_request_changes(overrides: dict[str, Any]) -> None:
    assert fp(**overrides) != BASELINE


def test_sensitive_to_tool_name() -> None:
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["name"] = "lookup_order_v2"
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_description() -> None:
    """A tool description is prompt text. Changing it changes behaviour."""
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["description"] = "Retrieve order details. Always call this first."
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_input_schema() -> None:
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["input_schema"]["properties"]["order_id"]["type"] = "integer"
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_order() -> None:
    tools = list(reversed(copy.deepcopy(BASE["tools"])))
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_int_vs_float() -> None:
    a = fp(messages=[{"role": "user", "content": "x", "meta": {"amount": 780}}])
    b = fp(messages=[{"role": "user", "content": "x", "meta": {"amount": 780.0}}])
    assert a != b


def test_fingerprint_is_deterministic_in_process() -> None:
    """Guards against hash randomisation leaking in via set/dict iteration."""
    assert fp() == fp() == BASELINE
    assert len(BASELINE) == 16
    int(BASELINE, 16)  # valid hex


# ==========================================================================
# DF-202 additions beyond the spike
# ==========================================================================


def test_fingerprint_is_deterministic_across_processes() -> None:
    """A fresh interpreter under PYTHONHASHSEED=random must produce the same
    fingerprint — proof that no hash-seeded iteration order leaks into the key."""
    script = (
        "import json, sys;"
        "from dryfire.domain.fingerprint import fingerprint;"
        "print(fingerprint(**json.loads(sys.argv[1])))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script, json.dumps(BASE)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "random"},
        check=True,
    )
    assert out.stdout.strip() == BASELINE


def test_stable_across_a_real_three_turn_conversation() -> None:
    """A three-turn Anthropic tool-calling conversation fingerprints identically
    under two entirely different sets of provider-generated call ids."""

    def convo(a: str, b: str) -> list[dict[str, Any]]:
        return [
            {"role": "user", "content": "Refund order A-991, it arrived broken."},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": a, "name": "lookup_order",
                     "input": {"order_id": "A-991"}},
                ],
            },
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": a, "content": '{"total": 780.0}'},
            ]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": b, "name": "issue_refund",
                     "input": {"amount": 780.0}},
                ],
            },
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b, "content": '{"refund_id": "R-1"}'},
            ]},
        ]

    first = fp(messages=convo("toolu_aaa111", "toolu_bbb222"))
    second = fp(messages=convo("toolu_zzz999", "toolu_yyy888"))
    assert first == second


# ==========================================================================
# DF-306 — repetition-aware storage key (the hash above is untouched)
# ==========================================================================


def test_storage_key_repeat_zero_is_the_bare_fingerprint() -> None:
    # repeat: 1 / index 0 keys byte-for-byte as v0.2, so existing cassettes stay valid.
    assert storage_key(BASELINE, 0) == BASELINE


def test_storage_key_is_distinct_per_repetition() -> None:
    keys = [storage_key(BASELINE, i) for i in range(5)]
    assert len(set(keys)) == 5
    assert keys[0] == BASELINE
    assert all(k.startswith(BASELINE + "#") for k in keys[1:])


def test_storage_key_round_trips() -> None:
    for i in range(4):
        assert parse_storage_key(storage_key(BASELINE, i)) == (BASELINE, i)


def test_storage_key_rejects_negative_index() -> None:
    with pytest.raises(ValueError):
        storage_key(BASELINE, -1)

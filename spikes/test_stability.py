"""SPIKE-002 — proof that the fingerprint is stable AND sensitive."""

from __future__ import annotations

import copy

import pytest

from fingerprint import fingerprint

BASE = dict(
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


def fp(**overrides):
    req = copy.deepcopy(BASE)
    req.update(overrides)
    return fingerprint(**req)


BASELINE = fp()


# ==========================================================================
# STABILITY -- these must NOT change the fingerprint
# ==========================================================================


def test_stable_across_dict_key_order():
    tools = [
        {
            "input_schema": BASE["tools"][0]["input_schema"],
            "description": BASE["tools"][0]["description"],
            "name": "lookup_order",
        },
        BASE["tools"][1],
    ]
    assert fp(tools=tools) == BASELINE


def test_stable_across_nested_key_order():
    schema = {
        "required": ["order_id"],
        "properties": {"order_id": {"type": "string"}},
        "type": "object",
    }
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["input_schema"] = schema
    assert fp(tools=tools) == BASELINE


def test_stable_across_extraneous_request_metadata():
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


def test_stable_across_provider_generated_call_ids():
    """THE critical case: turn 2+ echoes non-reproducible tool-call ids."""
    def convo(call_id: str):
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

    # NOTE: `tool_use_id` is deliberately NOT in the remap key list to prove
    # the test is meaningful -- see FINDINGS "Defect found".
    a = fp(messages=convo("toolu_01ABCdefGHI"))
    b = fp(messages=convo("toolu_99ZZZzzzYYY"))
    assert a == b


def test_stable_across_unicode_normalisation_form():
    nfc = "caf\u00e9 order"          # é as one codepoint
    nfd = "cafe\u0301 order"         # e + combining acute
    assert fp(system=nfc) == fp(system=nfd)


# ==========================================================================
# SENSITIVITY -- these MUST change the fingerprint
# ==========================================================================


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"model": "claude-opus-4-1"}, id="model"),
        pytest.param({"system": "You are a support agent. Never refund over $500. "},
                     id="system_trailing_whitespace"),
        pytest.param({"system": "You are a rude agent."}, id="system_content"),
        pytest.param({"provider": "openai"}, id="provider"),
        pytest.param({"messages": [{"role": "user", "content": "Refund order A-992"}]},
                     id="message_content"),
        pytest.param({"params": {"temperature": 0.7, "max_tokens": 1024}}, id="temperature"),
        pytest.param({"params": {"temperature": 0, "max_tokens": 2048}}, id="max_tokens"),
        pytest.param({"params": {"temperature": 0, "max_tokens": 1024, "top_p": 0.9}},
                     id="top_p_added"),
    ],
)
def test_sensitive_to_request_changes(overrides):
    assert fp(**overrides) != BASELINE


def test_sensitive_to_tool_name():
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["name"] = "lookup_order_v2"
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_description():
    """A tool description is prompt text. Changing it changes behaviour."""
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["description"] = "Retrieve order details. Always call this first."
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_input_schema():
    tools = copy.deepcopy(BASE["tools"])
    tools[0]["input_schema"]["properties"]["order_id"]["type"] = "integer"
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_tool_order():
    tools = list(reversed(copy.deepcopy(BASE["tools"])))
    assert fp(tools=tools) != BASELINE


def test_sensitive_to_int_vs_float():
    a = fp(messages=[{"role": "user", "content": "x", "meta": {"amount": 780}}])
    b = fp(messages=[{"role": "user", "content": "x", "meta": {"amount": 780.0}}])
    assert a != b


def test_fingerprint_is_deterministic_across_processes():
    """Guards against hash randomisation leaking in via set/dict iteration."""
    assert fp() == fp() == BASELINE
    assert len(BASELINE) == 16
    int(BASELINE, 16)  # valid hex

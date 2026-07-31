"""SPIKE-002 — canonical request fingerprinting for cassette storage.

A cassette key must be:
  STABLE   under changes that cannot affect the model's response
  SENSITIVE to anything that reaches the model

A false-stable key silently replays a stale response and produces a green test
for code that would fail live. That is the worst failure mode this tool can
have, so every judgement call below resolves toward SENSITIVITY.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

SCHEMA_VERSION = 1
FINGERPRINT_LEN = 16

# Fields of a request that reach the model, and therefore belong in the hash.
_HASHED_PARAMS = ("temperature", "top_p", "max_tokens", "stop_sequences")

# Every key any provider uses to carry a tool-call correlation id.
# This set is VENDOR-COUPLED: adding a provider adapter requires auditing it.
# Anthropic: `id` on tool_use blocks, `tool_use_id` on tool_result blocks.
# OpenAI:    `id` on tool_calls entries, `tool_call_id` on tool messages.
_CALL_ID_KEYS = frozenset({"id", "call_id", "tool_call_id", "tool_use_id"})


# --------------------------------------------------------------------------
# Canonicalisation
# --------------------------------------------------------------------------


def _norm_text(value: str) -> str:
    """NFC-normalise so visually identical strings hash identically."""
    return unicodedata.normalize("NFC", value)


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return _norm_text(value)
    if isinstance(value, dict):
        return {_norm_text(str(k)): _norm(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    return value


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, NFC strings.

    NOTE: int and float are deliberately NOT unified. `780` and `780.0`
    serialise differently on the wire, so they must hash differently.
    """
    return json.dumps(
        _norm(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


# --------------------------------------------------------------------------
# Tool-call id normalisation  (the critical finding of this spike)
# --------------------------------------------------------------------------


def normalise_call_ids(messages: list[dict]) -> list[dict]:
    """Replace provider-generated tool-call ids with positional placeholders.

    Turn 2+ of any agent loop echoes the assistant's tool_calls and their ids
    back to the provider. Those ids are generated per-request and are NOT
    reproducible. Left raw, every multi-turn cassette would miss on replay and
    the whole feature would be useless beyond turn 1.

    Mapping is assigned in first-appearance order across the message list, so
    it is deterministic and preserves the call<->result correspondence.
    """
    mapping: dict[str, str] = {}

    def remap(value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if k in _CALL_ID_KEYS and isinstance(v, str):
                    if v not in mapping:
                        mapping[v] = f"call_{len(mapping)}"
                    out[k] = mapping[v]
                else:
                    out[k] = remap(v)
            return out
        if isinstance(value, list):
            return [remap(v) for v in value]
        return value

    return [remap(m) for m in messages]


# --------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------


def hashable_request(
    *,
    provider: str,
    model: str,
    system: str | None,
    messages: list[dict],
    tools: list[dict],
    params: dict,
) -> dict:
    """Reduce a request to exactly the parts that reach the model."""
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "model": model,
        "system": system,
        "messages": normalise_call_ids(messages),
        # Tool ORDER is preserved: it is sent to the model as a list and we
        # cannot prove position has no effect on selection. See FINDINGS Q2.
        "tools": [
            {
                "name": t["name"],
                # description IS hashed -- the model reads it. See FINDINGS Q1.
                "description": t.get("description"),
                "input_schema": t.get("input_schema"),
            }
            for t in tools
        ],
        "params": {k: params[k] for k in _HASHED_PARAMS if k in params},
    }


def fingerprint(**kwargs: Any) -> str:
    payload = canonical_json(hashable_request(**kwargs))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]

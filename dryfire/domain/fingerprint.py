"""Canonical request fingerprinting for cassette storage (SPEC §9, DF-202).

Lifted essentially verbatim from SPIKE-002 (`spikes/fingerprint.py`, 19 passing
stability + sensitivity tests). A cassette key must be:

  STABLE    under changes that cannot affect the model's response
  SENSITIVE to anything that reaches the model

A false-stable key silently replays a stale response and produces a green test
for code that would fail live — the worst failure mode this tool can have, so
every judgement call below resolves toward SENSITIVITY.

Pure domain: stdlib only, no I/O, no pydantic. Operates on provider-neutral
dicts, so it stays uncoupled from any adapter.
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
# This set is VENDOR-COUPLED: adding a provider adapter (SPEC §3.1 obligation 2)
# requires auditing it.
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
# Tool-call id normalisation  (the critical finding of SPIKE-002)
# --------------------------------------------------------------------------


def normalise_call_ids(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace provider-generated tool-call ids with positional placeholders.

    Turn 2+ of any agent loop echoes the assistant's tool_calls and their ids
    back to the provider. Those ids are generated per-request and are NOT
    reproducible. Left raw, every multi-turn cassette would miss on replay and
    the whole feature would be useless beyond turn 1.

    Mapping is assigned in first-appearance order across the message list, so it
    is deterministic and preserves the call<->result correspondence. Applies to
    the HASH PATH ONLY; the wire path keeps ids verbatim (SPEC §3.1 obligation 4).
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
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Reduce a request to exactly the parts that reach the model."""
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "model": model,
        "system": system,
        "messages": normalise_call_ids(messages),
        # Tool ORDER is preserved: it is sent to the model as a list and we
        # cannot prove position has no effect on selection.
        "tools": [
            {
                "name": t["name"],
                # description IS hashed -- the model reads it (sensitivity wins).
                "description": t.get("description"),
                "input_schema": t.get("input_schema"),
            }
            for t in tools
        ],
        "params": {k: params[k] for k in _HASHED_PARAMS if k in params},
    }


def fingerprint(**kwargs: Any) -> str:
    """The 16-hex-char cassette key for a request. `schema_version` is inside the
    hash input, so bumping it invalidates every cassette globally by construction."""
    payload = canonical_json(hashable_request(**kwargs))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


# --------------------------------------------------------------------------
# Repetition-aware storage key (DF-306, SPIKE-007)
# --------------------------------------------------------------------------

# `#` cannot occur in a 16-hex fingerprint, so the mapping stays unambiguous and
# reversible, and a bare-fingerprint glob never matches a suffixed repetition file.
REPEAT_SEP = "#"


def storage_key(fingerprint: str, repeat_index: int) -> str:
    """The cassette storage key for repetition `repeat_index` of a request whose
    fingerprint is `fingerprint`. The repetition index lives HERE, in the storage key,
    never in the hash — so `fingerprint()` is unchanged (every SPIKE-002 stability and
    sensitivity property holds) and `repeat: 1` keys byte-for-byte as v0.2 did.

    - `repeat_index == 0` → the bare fingerprint, so v0.2 cassettes stay valid.
    - `repeat_index >= 1` → `fingerprint#<index>`, a distinct key per repetition, so a
      `repeat: N` case stores N distinct responses instead of overwriting one N times.
    """
    if repeat_index < 0:
        raise ValueError(f"repeat_index must be >= 0, got {repeat_index}")
    return fingerprint if repeat_index == 0 else f"{fingerprint}{REPEAT_SEP}{repeat_index}"


def parse_storage_key(key: str) -> tuple[str, int]:
    """Inverse of `storage_key`: `(fingerprint, repeat_index)`. Lets tooling recognise a
    repetition cassette as belonging to the same logical request."""
    fp, sep, idx = key.partition(REPEAT_SEP)
    return (fp, int(idx)) if sep else (fp, 0)

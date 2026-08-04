"""Neutral stop reasons and the provider mapping table (SPEC §3.3).

Adapters map their vendor value through `map_stop_reason`; an unrecognised value
maps to ``"error"`` and never raises (SPIKE-001 adapter obligation).
`refusal` and `content_filter` are collapsed for v0.1 — the distinction is
recoverable from `ModelResponse.raw` when a future assertion needs it.
"""

from typing import Final, Literal

StopReason = Literal[
    "end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "error"
]

# provider name -> {vendor raw value -> neutral StopReason}
_TABLE: Final[dict[str, dict[str, StopReason]]] = {
    "anthropic": {
        "end_turn": "end_turn",
        "pause_turn": "end_turn",
        "tool_use": "tool_use",
        "max_tokens": "max_tokens",
        "stop_sequence": "stop_sequence",
        "refusal": "refusal",
    },
    "openai": {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "function_call": "tool_use",
        "length": "max_tokens",
        "content_filter": "refusal",
    },
    # Gemini's `finishReason` is `STOP` even for a tool-call turn (#76 spike), so the
    # adapter infers `tool_use` from the presence of functionCall parts *before*
    # consulting this table — there is deliberately no "tool_use" key here.
    "gemini": {
        "STOP": "end_turn",
        "MAX_TOKENS": "max_tokens",
        "SAFETY": "refusal",
        "RECITATION": "refusal",
        "BLOCKLIST": "refusal",
        "PROHIBITED_CONTENT": "refusal",
        "SPII": "refusal",
        "IMAGE_SAFETY": "refusal",
        "MALFORMED_FUNCTION_CALL": "error",
        "OTHER": "error",
    },
}


def map_stop_reason(provider: str, raw_value: str) -> StopReason:
    """Map a vendor stop reason to a neutral one. Unknown provider or value
    yields ``"error"`` — never raises."""
    return _TABLE.get(provider, {}).get(raw_value, "error")

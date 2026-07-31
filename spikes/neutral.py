"""SPIKE-001 — the proposed provider-neutral types from SPEC.md §3, under test."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StopReason = Literal[
    "end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "error"
]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ToolDef:
    name: str
    input_schema: dict
    description: str | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    # Set when the provider emitted arguments we could not parse as JSON.
    # The loop must be able to see this rather than crash. See FINDINGS Q2.
    malformed_arguments: str | None = None


@dataclass
class ToolResult:
    call_id: str
    content: Any
    is_error: bool = False


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: Any = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    # Provider-opaque passthrough. Populated by from_wire, replayed verbatim by
    # to_wire. Exists because some providers reject an assistant turn that is
    # not echoed back exactly as issued. See FINDINGS Q4.
    raw: dict | None = None


@dataclass
class ModelResponse:
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    usage: Usage
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)

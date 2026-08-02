"""Provider-neutral conversation and response types (SPEC §3)."""

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from dryfire.domain.model.stop_reason import StopReason
from dryfire.domain.model.tooling import ToolCall, ToolResult


class Usage(BaseModel):
    """Token accounting for one model call. Cache fields default to zero for
    providers that do not report them."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def sum_usage(usages: Iterable[Usage]) -> Usage:
    """Field-wise total of several usages — used to total the judge cost channel
    (DF-304). The agent loop keeps its own private summing; this is the reusable one
    for callers above the loop."""
    total = Usage(input_tokens=0, output_tokens=0)
    for u in usages:
        total = Usage(
            input_tokens=total.input_tokens + u.input_tokens,
            output_tokens=total.output_tokens + u.output_tokens,
            cache_read_tokens=total.cache_read_tokens + u.cache_read_tokens,
            cache_write_tokens=total.cache_write_tokens + u.cache_write_tokens,
        )
    return total


class Message(BaseModel):
    """One turn in the conversation, provider-neutral.

    `raw` is a provider-opaque passthrough: Anthropic rejects an assistant turn
    reconstructed from neutral fields, so the original must be echoed verbatim
    on the wire path (SPIKE-001). Nothing consumes it until AC-007.
    """

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    raw: dict[str, Any] | None = None


class ModelResponse(BaseModel):
    """One provider response, normalised. `raw` is the untouched payload kept
    for debugging and to recover distinctions v0.1 collapses (SPEC §3.3)."""

    model_config = ConfigDict(frozen=True)

    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    usage: Usage
    latency_ms: int
    raw: dict[str, Any]
    # Set by the caching gateway (DF-204) when this response was served from a
    # cassette rather than a live call. The loop only stores the response, so it
    # never learns caching exists; reporters read this to show cache hits.
    cache_hit: bool = False

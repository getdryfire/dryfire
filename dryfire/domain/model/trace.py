"""Trace types (SPEC §3). A Trace is the immutable record of one case's run —
the primary surface every structural assertion reads (ARCHITECTURE §4.1)."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall, ToolResult


class Turn(BaseModel):
    """One model call plus the tool results it produced.

    `request_messages` records what was sent this turn; it is load-bearing for
    v0.2 cassettes and must not be dropped as redundant (SPIKE-002).
    """

    model_config = ConfigDict(frozen=True)

    index: int
    request_messages: list[Message]
    response: ModelResponse
    tool_results: list[ToolResult]


TerminationReason = Literal[
    "end_turn",
    "max_turns_exceeded",
    "provider_error",
    "unmocked_tool",
    "max_tokens",
    "refusal",
]


class Trace(BaseModel):
    """The complete record of one case's execution."""

    model_config = ConfigDict(frozen=True)

    case_name: str
    suite_name: str
    turns: list[Turn]
    final_text: str | None
    termination: TerminationReason
    total_usage: Usage
    total_cost_usd: float | None
    duration_ms: int
    error: str | None = None
    # The resolved model, attached with cost when the trace is priced (DF-207) —
    # the loop does not set it, so pricing stays out of the loop. `cost_under`
    # names it when pricing is unavailable.
    model: str | None = None

    @field_validator("total_cost_usd")
    @classmethod
    def _cost_must_be_finite(cls, v: float | None) -> float | None:
        # A non-finite cost would serialise to Infinity/NaN and break v0.2
        # fingerprinting (allow_nan=False). Reject it at the boundary.
        if v is not None and not math.isfinite(v):
            raise ValueError("total_cost_usd must be finite")
        return v

    def tool_calls(self) -> list[ToolCall]:
        """Flattened tool calls in call order across all turns."""
        return [call for turn in self.turns for call in turn.response.tool_calls]

    def tool_names(self) -> list[str]:
        """Ordered tool names — the primary surface for structural assertions."""
        return [call.name for call in self.tool_calls()]

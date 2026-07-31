"""AC-007 — one real two-turn tool-calling exchange against Anthropic.

Skipped unless ANTHROPIC_API_KEY is set; run with `make test-live` (or source
your .env first). Verifies end to end that a tool call is elicited, the assistant
turn is echoed back verbatim, and a tool result round-trips.
"""

import os

import pytest

from agentcheck.adapters.driven.providers.anthropic import AnthropicGateway
from agentcheck.application.ports.model_gateway import CompletionRequest, ModelParams
from agentcheck.domain.model.message import Message
from agentcheck.domain.model.tooling import ToolDef, ToolResult

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"
    ),
]

_MODEL = "claude-sonnet-4-6"
_SYSTEM = "You are a support agent. Use the tools to answer. Be brief."
_TOOLS = [
    ToolDef(
        name="lookup_order",
        description="Retrieve order details by ID.",
        input_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    )
]


async def test_two_turn_tool_calling_exchange() -> None:
    gateway = AnthropicGateway()
    params = ModelParams(max_tokens=512, temperature=0.0)

    # Turn 1 — the model should call lookup_order.
    first = await gateway.complete(
        CompletionRequest(
            model=_MODEL,
            system=_SYSTEM,
            messages=[Message(role="user", content="Look up order A-991.")],
            tools=_TOOLS,
            params=params,
        )
    )
    assert first.stop_reason == "tool_use"
    assert first.tool_calls
    call = first.tool_calls[0]
    assert call.name == "lookup_order"

    # Turn 2 — echo the assistant turn verbatim (raw) and feed a tool result.
    second = await gateway.complete(
        CompletionRequest(
            model=_MODEL,
            system=_SYSTEM,
            messages=[
                Message(role="user", content="Look up order A-991."),
                Message(
                    role="assistant",
                    content=first.text,
                    tool_calls=first.tool_calls,
                    raw=first.raw,
                ),
                Message(
                    role="tool",
                    tool_results=[
                        ToolResult(
                            call_id=call.id,
                            content={"total": 780.0, "status": "delivered"},
                        )
                    ],
                ),
            ],
            tools=_TOOLS,
            params=params,
        )
    )
    # The model consumes the tool result and answers (or calls again) — either way
    # the echoed assistant turn was accepted and the exchange did not error.
    assert second.stop_reason in ("end_turn", "tool_use")
    assert second.usage.input_tokens > 0

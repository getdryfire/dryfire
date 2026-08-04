"""#77 — one real two-turn tool-calling exchange against Gemini `generateContent`.

Skipped unless GEMINI_API_KEY is set; run with `make test-live` (or source .env). Verifies
end to end that a tool call is elicited and that echoing the assistant turn verbatim (via
`raw`, carrying the mandatory `thoughtSignature`) plus a functionResponse round-trips —
without the echo the second turn 400s, so this is the real proof the #76 seam holds.
"""

import os

import pytest

from dryfire.adapters.driven.providers.gemini import GeminiGateway
from dryfire.application.ports.model_gateway import CompletionRequest, ModelParams
from dryfire.domain.model.message import Message
from dryfire.domain.model.tooling import ToolDef, ToolResult

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY"),
]

# gemini-flash-latest is the stable alias; Google 404s dated models for new keys (#76).
_MODEL = os.environ.get("DRYFIRE_GEMINI_MODEL", "gemini-flash-latest")
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
    gateway = GeminiGateway(api_key=os.environ["GEMINI_API_KEY"])
    # Thinking models spend output budget on thoughts — keep max_tokens generous (#76).
    params = ModelParams(max_tokens=512, temperature=0.0)

    first = await gateway.complete(
        CompletionRequest(
            model=_MODEL, system=_SYSTEM,
            messages=[Message(role="user", content="Look up order A-991.")],
            tools=_TOOLS, params=params,
        )
    )
    assert first.stop_reason == "tool_use"
    assert first.tool_calls
    call = first.tool_calls[0]
    assert call.name == "lookup_order"

    second = await gateway.complete(
        CompletionRequest(
            model=_MODEL, system=_SYSTEM,
            messages=[
                Message(role="user", content="Look up order A-991."),
                # raw carries the thoughtSignature — mandatory for the follow-up tool turn.
                Message(role="assistant", content=first.text, tool_calls=first.tool_calls,
                        raw=first.raw),
                Message(role="tool", tool_results=[
                    ToolResult(call_id=call.id, content={"total": 780.0, "status": "delivered"}),
                ]),
            ],
            tools=_TOOLS, params=params,
        )
    )
    assert second.stop_reason in ("end_turn", "tool_use")
    assert second.usage.input_tokens > 0

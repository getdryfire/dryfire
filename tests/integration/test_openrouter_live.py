"""#71 — one real tool-calling exchange through an OpenAI-compatible endpoint.

Exercises the seam end to end: the same `OpenAIGateway` translation, pointed at a
different `base_url` via the `make_gateway` registry, reaches a live provider through
OpenRouter (the one key that fans out to every frontier + open-weight model). This is
the live proof that a compat provider needs zero adapter code above the port.

Skipped unless OPENROUTER_API_KEY is set; run with `make test-live` (or source .env).
Point it at any tool-calling model with DRYFIRE_OPENROUTER_MODEL — the default is a
rock-solid one so the smoke test stays dependable.
"""

import os

import pytest

from dryfire import composition
from dryfire.application.ports.model_gateway import CompletionRequest, ModelParams
from dryfire.domain.model.message import Message
from dryfire.domain.model.tooling import ToolDef, ToolResult

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("OPENROUTER_API_KEY"), reason="needs OPENROUTER_API_KEY"
    ),
]

# Override to prove a specific frontier/open-weight model (e.g. "x-ai/grok-2-1212",
# "deepseek/deepseek-chat", "google/gemini-2.0-flash-001"). Default stays dependable.
_MODEL = os.environ.get("DRYFIRE_OPENROUTER_MODEL", "openai/gpt-4o-mini")
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


async def test_two_turn_tool_calling_through_openrouter() -> None:
    # Built through the registry, so this also exercises make_gateway's compat branch.
    gateway = composition.make_gateway("openrouter")
    assert gateway.name == "openrouter"
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

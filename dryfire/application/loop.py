"""The agent loop (SPEC §5) — the core of the product.

`run_case` drives the provider tool-calling loop with deterministic mocked tools
and produces the `Trace` that assertions, reporters, and cassettes all read. It
never raises for a normal outcome: max_turns_exceeded, provider_error, and
unmocked_tool are recorded terminations, so one failing case can't abort a run.

Pure with respect to the resolver: given a scripted gateway and a resolver, the
returned Trace is deterministic and no network call occurs. `async def`, with no
scheduling inside — AC-012 owns concurrency.
"""

from __future__ import annotations

import json
import time
from typing import Any

from dryfire.application.ports.model_gateway import (
    CompletionRequest,
    ModelGateway,
    ModelParams,
)
from dryfire.application.ports.tool_invoker import ToolInvoker
from dryfire.domain.mocking.resolver import UNMOCKED, MockResolver, Passthrough
from dryfire.domain.model.case import ResolvedCase
from dryfire.domain.model.message import Message, ModelResponse, Usage
from dryfire.domain.model.tooling import ToolResult
from dryfire.domain.model.trace import TerminationReason, Trace, Turn

# StopReason (non-tool_use) -> how the loop terminates.
_TERMINATION: dict[str, TerminationReason] = {
    "end_turn": "end_turn",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
    "stop_sequence": "end_turn",
    "error": "provider_error",
}


def _initial_messages(case_input: str | list[dict[str, Any]]) -> list[Message]:
    if isinstance(case_input, str):
        return [Message(role="user", content=case_input)]
    return [Message(**entry) for entry in case_input]


def _sum_usage(a: Usage, b: Usage) -> Usage:
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_read_tokens=a.cache_read_tokens + b.cache_read_tokens,
        cache_write_tokens=a.cache_write_tokens + b.cache_write_tokens,
    )


def _assistant_message(response: ModelResponse) -> Message:
    # Carry raw so the adapter can echo the assistant turn verbatim (SPIKE-001).
    return Message(
        role="assistant",
        content=response.text,
        tool_calls=response.tool_calls,
        raw=response.raw,
    )


async def run_case(
    resolved_case: ResolvedCase,
    provider: ModelGateway,
    resolver: MockResolver,
    *,
    invoker: ToolInvoker | None = None,
) -> Trace:
    case = resolved_case
    messages = _initial_messages(case.input)  # the loop's own list; never the case's
    params = ModelParams(temperature=case.temperature)

    turns: list[Turn] = []
    total_usage = Usage(input_tokens=0, output_tokens=0)
    termination: TerminationReason = "end_turn"
    error: str | None = None
    turn_index = 0
    start = time.monotonic()

    while True:
        if turn_index >= case.max_turns:
            termination = "max_turns_exceeded"
            break

        request = CompletionRequest(
            model=case.model,
            system=case.system,
            messages=list(messages),  # copy — request holds this turn's state
            tools=case.tools,
            params=params,
        )
        try:
            response = await provider.complete(request)
        except Exception as exc:  # noqa: BLE001 - a provider failure is a recorded outcome
            termination = "provider_error"
            error = f"provider error: {exc!r}"
            break

        request_messages = list(messages)  # copy taken before any mutation this turn
        total_usage = _sum_usage(total_usage, response.usage)

        if response.stop_reason != "tool_use":
            turns.append(
                Turn(
                    index=turn_index,
                    request_messages=request_messages,
                    response=response,
                    tool_results=[],
                )
            )
            termination = _TERMINATION.get(response.stop_reason, "end_turn")
            break

        results: list[ToolResult] = []
        unmocked_error = False
        for call in response.tool_calls:
            resolved = resolver.resolve(call)
            if isinstance(resolved, Passthrough):
                # A passthrough rule delivers its result by running real code — I/O,
                # so the pure resolver only produced a marker; the injected port
                # realizes it. A raise/timeout becomes an error result (SPIKE-004).
                if invoker is None:
                    raise RuntimeError(
                        f"passthrough tool {call.name!r} needs a ToolInvoker "
                        f"but none was wired into run_case"
                    )
                resolved = await invoker.invoke(resolved, call)
            if resolved is UNMOCKED:
                if case.on_unmocked == "error":
                    unmocked_error = True
                    error = (
                        f"unmocked tool {call.name!r} called with "
                        f"{json.dumps(call.arguments)} (on_unmocked=error)"
                    )
                    break
                # on_unmocked == "null": empty result, continue.
                resolved = ToolResult(call_id=call.id, content="")
            results.append(resolved)  # type: ignore[arg-type]

        turns.append(
            Turn(
                index=turn_index,
                request_messages=request_messages,
                response=response,
                tool_results=results,
            )
        )
        if unmocked_error:
            termination = "unmocked_tool"
            break

        messages.append(_assistant_message(response))
        messages.append(Message(role="tool", tool_results=results))
        turn_index += 1

    duration_ms = int((time.monotonic() - start) * 1000)
    final_text = turns[-1].response.text if turns else None
    return Trace(
        case_name=case.case_name,
        suite_name=case.suite_name,
        turns=turns,
        final_text=final_text,
        termination=termination,
        total_usage=total_usage,
        total_cost_usd=None,
        duration_ms=duration_ms,
        error=error,
    )

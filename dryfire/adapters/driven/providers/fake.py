"""FakeGateway — a scripted ModelGateway that makes every downstream ticket
testable offline (SPEC §8.2, AC-006).

Shipped in the package, not test-only: AC-016's keyless scaffold example depends
on it at runtime. Imports no provider SDK.

    gw = FakeGateway.script([
        tool_call("lookup_order", {"order_id": "A-991"}),
        text("Done."),
    ])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dryfire.application.ports.model_gateway import CompletionRequest
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall


class ScriptExhausted(RuntimeError):
    """Raised when the loop requests another completion but the script is spent.
    A silent repeat would mask infinite-loop bugs, so we fail loudly."""


class FakeProviderError(RuntimeError):
    """Default exception raised by a scripted `fails()` entry."""


# -- Script entries (built by the helpers below) ----------------------------


@dataclass(frozen=True)
class _Text:
    text: str


@dataclass(frozen=True)
class _ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Parallel:
    calls: tuple[_ToolCall, ...]


@dataclass(frozen=True)
class _Fail:
    exc: Exception


ScriptEntry = _Text | _ToolCall | _Parallel | _Fail


def text(value: str) -> _Text:
    """A text-only assistant turn (stop_reason end_turn)."""
    return _Text(value)


def tool_call(name: str, arguments: dict[str, Any] | None = None) -> _ToolCall:
    """A single tool call. Usable directly as a one-call turn, or inside parallel()."""
    return _ToolCall(name, arguments or {})


def parallel(*calls: _ToolCall) -> _Parallel:
    """Combine several tool calls into one assistant turn (parallel tool use)."""
    return _Parallel(calls)


def fails(exc: Exception | None = None) -> _Fail:
    """A turn where complete() raises — exercises the provider_error path."""
    return _Fail(exc if exc is not None else FakeProviderError("simulated provider failure"))


class FakeGateway:
    """Returns a pre-scripted sequence of responses and records every request."""

    name = "fake"

    def __init__(self, entries: list[ScriptEntry]) -> None:
        self._entries = entries
        self._requests: list[CompletionRequest] = []
        self._calls_made = 0
        self._next_id = 0

    @classmethod
    def script(cls, entries: list[ScriptEntry]) -> FakeGateway:
        return cls(entries)

    @property
    def requests(self) -> list[CompletionRequest]:
        """Every request received, in order — how tests assert what the loop sent."""
        return self._requests

    def is_retryable(self, exc: Exception) -> bool:
        # Scripted `fails()` outcomes are deterministic, not transient — never retry.
        return False

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        self._requests.append(request)
        if self._calls_made >= len(self._entries):
            raise ScriptExhausted(
                f"FakeGateway script exhausted after {self._calls_made} call(s); "
                "the loop requested another completion"
            )
        entry = self._entries[self._calls_made]
        self._calls_made += 1

        if isinstance(entry, _Fail):
            raise entry.exc
        if isinstance(entry, _Text):
            return self._build(text=entry.text, calls=())
        if isinstance(entry, _ToolCall):
            return self._build(text=None, calls=(entry,))
        return self._build(text=None, calls=entry.calls)

    def _build(self, *, text: str | None, calls: tuple[_ToolCall, ...]) -> ModelResponse:
        tool_calls = []
        for call in calls:
            tool_calls.append(
                ToolCall(id=f"fake_call_{self._next_id}", name=call.name, arguments=call.arguments)
            )
            self._next_id += 1
        return ModelResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0,
            raw={},
        )

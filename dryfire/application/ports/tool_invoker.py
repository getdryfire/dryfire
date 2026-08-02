"""The ToolInvoker driven port (ARCHITECTURE §2, DF-211).

Passthrough mocks (SPEC §4.4) deliver a tool result by invoking a real Python
callable. Importing and calling that code is I/O, so it cannot live in the pure
domain resolver — the resolver returns a `Passthrough` marker and the loop hands
it to this port. The concrete `PassthroughInvoker`
(`adapters/driven/mocking/passthrough.py`) runs sync callables off the event loop
and async ones natively, bounds each by a timeout, and turns any raise into an
error result — the run continues (SPIKE-004's verdict).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from dryfire.domain.mocking.resolver import Passthrough
from dryfire.domain.model.tooling import ToolCall, ToolResult


@runtime_checkable
class ToolInvoker(Protocol):
    """Realize a `Passthrough` marker into a `ToolResult` by calling real code."""

    async def invoke(self, passthrough: Passthrough, call: ToolCall) -> ToolResult:
        """Invoke the callable named by `passthrough.target` with `call.arguments`.
        Never raises for the callable's own failure — a raise or timeout becomes a
        `ToolResult(is_error=True)`."""
        ...

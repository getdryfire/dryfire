"""Shared renderers for structural assertion failures (SPEC §6).

Failure messages are the product's UX: every structural failure shows the actual
ordered tool-call sequence. Built once here so no assertion reimplements it.
"""

from __future__ import annotations

from dryfire.domain.assertions.base import AssertionResult
from dryfire.domain.model.trace import Trace

# Column at which the `expected:`/`actual:` values (and continuation lines) align.
_VALUE_COL = 14


def render_trajectory(trace: Trace) -> str:
    """The ``a → b → (termination)`` line for a trace. With no tool calls, just
    ``(termination)``."""
    names = trace.tool_names()
    termination = f"({trace.termination})"
    if not names:
        return termination
    return " → ".join([*names, termination])


def render_failure(result: AssertionResult) -> str:
    """Render one failed assertion in the SPEC §6 block format:

        ✗ <description>
            expected: <expected>
            actual:   <actual>
                      <message continuation, if any>
    """
    lines = [
        f"✗ {result.description}",
        f"    expected: {result.expected}",
        f"    actual:   {result.actual}",
    ]
    if result.message:
        lines.append(f"{' ' * _VALUE_COL}{result.message}")
    return "\n".join(lines)

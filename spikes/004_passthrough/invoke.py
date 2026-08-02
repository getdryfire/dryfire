"""SPIKE-004 — the passthrough invoker. Reference `invoke()` DF-211 adapts.

This is the execution-model verdict in code (see FINDINGS.md for the prose):

- **Sync callables run in a thread** (`asyncio.to_thread`), never inline — a sync
  `impl` that blocks on a real HTTP call must not freeze the async scheduler while
  the other concurrent cases wait (Q1). We do NOT require users to write async.
- **Async callables are awaited natively.** A callable that merely *returns* an
  awaitable (a sync `def` returning a coroutine) is also awaited — robust to
  `functools.partial`, decorators, and lambdas that `iscoroutinefunction` misses.
- **A raise becomes an error result, never an exception** — the run continues, the
  trace records `is_error=True` with the exception message.
- **A hang is bounded by a per-call timeout** (Q3). Nuance you cannot design away:
  `asyncio.wait_for` bounds the *wait*, not the *work*. An async callable is
  cancelled cleanly; a sync callable in a thread cannot be killed (Python has no
  thread kill), so a wedged sync `impl` leaks its thread until it returns on its
  own. We bound wall-clock and continue; we do not pretend to have stopped the
  work. That honesty is the whole no-sandbox stance (Q5).

The invoker is I/O and impure, so in DF-211 it lives in an **adapter behind a
port**, not in `domain/`. The domain resolver stays pure by resolving a
passthrough rule to a *marker*; this invoker realizes the marker. See FINDINGS.md
"Layering" for the seam that costs.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class PassResult:
    """Shaped like the real `domain.model.tooling.ToolResult` (content + is_error)
    so DF-211's adapter maps it 1:1. Kept local to keep the spike standalone."""

    content: Any
    is_error: bool


async def invoke(
    func: Callable[[dict[str, Any]], Any],
    arguments: dict[str, Any],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> PassResult:
    """Call `func(arguments)` — sync or async — bounded by `timeout_s`, and turn
    any outcome into a PassResult. Never raises for a callable's own failure.

    Calling convention: the tool arguments are passed as a single positional dict.
    JSON object keys are not guaranteed to be valid Python identifiers, so
    `func(**arguments)` is unsafe; `func(arguments)` always works. DF-211 documents
    this as the impl signature: `def my_impl(args: dict) -> Any`.
    """
    try:
        result = await asyncio.wait_for(_call(func, arguments), timeout_s)
    except asyncio.TimeoutError:
        return PassResult(
            content=(
                f"passthrough impl timed out after {timeout_s:g}s "
                f"(the call was abandoned; a sync impl may still be running)"
            ),
            is_error=True,
        )
    except Exception as exc:  # noqa: BLE001 - a callable's failure is a result, not a crash
        return PassResult(content=f"{type(exc).__name__}: {exc}", is_error=True)
    return PassResult(content=result, is_error=False)


async def _call(func: Callable[[dict[str, Any]], Any], arguments: dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(func):
        return await func(arguments)
    # Sync path: run off the event loop so a blocking call can't stall the
    # scheduler. If the sync callable *returns* an awaitable, await it too.
    result = await asyncio.to_thread(func, arguments)
    if inspect.isawaitable(result):
        return await result
    return result

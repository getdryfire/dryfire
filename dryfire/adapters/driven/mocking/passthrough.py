"""PassthroughInvoker + `impl:` resolution (SPEC §4.4, DF-211; SPIKE-004's verdict).

This is the driven adapter behind the `ToolInvoker` port. It is the only place
`impl: pkg.mod:func` code is imported or called, so all of passthrough's I/O and
impurity is quarantined here — the domain resolver only ever produces a
`Passthrough` marker.

Execution model (settled by SPIKE-004, do not re-derive):
- **Resolution** is `importlib.import_module` + `getattr`, with the CWD on
  `sys.path`. It runs at *validate* time (the loader calls `resolve_impl`) so a bad
  `impl:` is a positioned spec error before any API spend; the invoker resolves
  again at run time (importlib caches, so it is a dict lookup).
- **Sync callables run in a thread** (`asyncio.to_thread`) so a blocking impl never
  stalls the shared scheduler event loop; **async callables are awaited natively**.
- **A raise or a timeout becomes `ToolResult(is_error=True)`** — the run continues.
  `asyncio.wait_for` bounds the *wait*; a wedged sync impl still runs to completion
  in its thread (Python cannot kill a thread) and is joined at loop shutdown — the
  honest cost of the no-sandbox stance.

The calling convention is `func(arguments: dict) -> Any`: JSON object keys are not
guaranteed valid Python identifiers, so the arguments are passed as one positional
dict, never `**kwargs`.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import sys
from collections.abc import Callable
from typing import Any

from dryfire.domain.mocking.resolver import Passthrough
from dryfire.domain.model.tooling import ToolCall, ToolResult

DEFAULT_TIMEOUT_S = 30.0

ImplCallable = Callable[[dict[str, Any]], Any]
Resolver = Callable[[str], ImplCallable]


class ImplResolutionError(Exception):
    """`impl:` could not be resolved to a callable. The loader renders this as a
    positioned spec error (exit 2) at validate time; the invoker turns it into an
    error result at run time (defensive — validate should have caught it)."""


def resolve_impl(target: str) -> ImplCallable:
    """``"pkg.mod:func"`` → the callable. Raises `ImplResolutionError` with a message
    a user can act on. Importing the module runs its top-level code (documented in
    the security note); that is inherent to Python import and cannot be avoided."""
    if target.count(":") != 1:
        raise ImplResolutionError(
            f"impl {target!r} must be 'package.module:function' "
            f"(one colon separating the module path from the attribute)"
        )
    module_path, _, attr = target.partition(":")
    if not module_path or not attr:
        raise ImplResolutionError(
            f"impl {target!r} must name both a module and a function, "
            f"e.g. 'mytools.impls:create_ticket'"
        )
    _ensure_cwd_importable()
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImplResolutionError(
            f"impl {target!r}: cannot import module {module_path!r} ({exc})"
        ) from exc
    try:
        func = getattr(module, attr)
    except AttributeError as exc:
        raise ImplResolutionError(
            f"impl {target!r}: module {module_path!r} has no attribute {attr!r}"
        ) from exc
    if not callable(func):
        raise ImplResolutionError(
            f"impl {target!r}: {module_path}.{attr} is not callable "
            f"(got {type(func).__name__})"
        )
    return func  # type: ignore[no-any-return]


def _ensure_cwd_importable() -> None:
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)


class PassthroughInvoker:
    """Concrete `ToolInvoker`. `resolve` is injected for testing; production uses
    `resolve_impl`."""

    def __init__(
        self, *, default_timeout_s: float = DEFAULT_TIMEOUT_S, resolve: Resolver = resolve_impl
    ) -> None:
        self._default_timeout = default_timeout_s
        self._resolve = resolve

    async def invoke(self, passthrough: Passthrough, call: ToolCall) -> ToolResult:
        timeout = (
            passthrough.timeout_s if passthrough.timeout_s is not None else self._default_timeout
        )
        try:
            func = self._resolve(passthrough.target)
        except ImplResolutionError as exc:
            return ToolResult(
                call_id=call.id, content=f"passthrough resolution failed: {exc}", is_error=True
            )
        try:
            result = await asyncio.wait_for(_call(func, call.arguments), timeout)
        except TimeoutError:
            return ToolResult(
                call_id=call.id,
                content=(
                    f"passthrough impl {passthrough.target!r} timed out after {timeout:g}s "
                    f"(the call was abandoned; a sync impl may still be running)"
                ),
                is_error=True,
            )
        except Exception as exc:  # noqa: BLE001 - a callable's failure is a result, not a crash
            message = f"{type(exc).__name__}: {exc}"
            return ToolResult(call_id=call.id, content=message, is_error=True)
        return ToolResult(call_id=call.id, content=_coerce(result), is_error=False)


async def _call(func: ImplCallable, arguments: dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(func):
        return await func(arguments)
    # Sync path: off the event loop so a blocking impl can't stall the scheduler.
    result = await asyncio.to_thread(func, arguments)
    if inspect.isawaitable(result):
        return await result
    return result


def _coerce(value: Any) -> str | dict[str, Any] | None:
    """A callable may return anything; ToolResult content is str | dict | None.
    Keep those as-is; render everything else as JSON text (falling back to str)."""
    if value is None or isinstance(value, (str, dict)):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)

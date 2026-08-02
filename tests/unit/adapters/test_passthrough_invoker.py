"""DF-211 — the PassthroughInvoker adapter (SPIKE-004's verdict, lifted).

Sync callables run off the event loop (they must not stall the scheduler); async
callables are awaited natively; a raise or a timeout becomes a
`ToolResult(is_error=True)` and the run continues. Behavior is tested by injecting
the resolver (target → callable) so these tests need no import gymnastics;
`resolve_impl` has its own tests below.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import pytest

from dryfire.adapters.driven.mocking.passthrough import (
    ImplResolutionError,
    PassthroughInvoker,
    resolve_impl,
)
from dryfire.domain.mocking.resolver import Passthrough
from dryfire.domain.model.tooling import ToolCall


def _call(args: dict[str, Any] | None = None) -> ToolCall:
    return ToolCall(id="c0", name="tool", arguments=args or {})


def _invoker(mapping: dict[str, Callable[..., Any]], **kw: Any) -> PassthroughInvoker:
    return PassthroughInvoker(resolve=lambda target: mapping[target], **kw)


def _run(inv: PassthroughInvoker, target: str, args: dict[str, Any] | None = None,
         timeout_s: float | None = None) -> Any:
    return asyncio.run(inv.invoke(Passthrough(target=target, timeout_s=timeout_s), _call(args)))


# -- sync / async invocation --------------------------------------------------


def test_sync_callable_produces_a_success_result() -> None:
    inv = _invoker({"m:f": lambda a: {"city": a["city"], "temp": 65}})
    res = _run(inv, "m:f", {"city": "SF"})
    assert res.is_error is False
    assert res.content == {"city": "SF", "temp": 65}
    assert res.call_id == "c0"  # carries the originating call id


def test_async_callable_is_awaited_natively() -> None:
    async def impl(a: dict[str, Any]) -> str:
        await asyncio.sleep(0)
        return f"hello {a['name']}"

    res = _run(_invoker({"m:f": impl}), "m:f", {"name": "x"})
    assert res.is_error is False and res.content == "hello x"


def test_non_string_non_dict_return_is_coerced_to_json_text() -> None:
    inv = _invoker({"m:f": lambda a: [1, 2, 3]})
    res = _run(inv, "m:f")
    assert res.is_error is False and res.content == "[1, 2, 3]"


def test_none_return_is_a_legitimate_null_result() -> None:
    inv = _invoker({"m:f": lambda a: None})
    res = _run(inv, "m:f")
    assert res.is_error is False and res.content is None


# -- failures become error results, the run continues -------------------------


def test_raising_callable_becomes_an_error_result() -> None:
    def impl(a: dict[str, Any]) -> str:
        raise RuntimeError("the real tool failed")

    res = _run(_invoker({"m:f": impl}), "m:f")
    assert res.is_error is True and "the real tool failed" in res.content


def test_unresolvable_target_at_invoke_time_becomes_an_error_result() -> None:
    def boom(target: str) -> Callable[..., Any]:
        raise ImplResolutionError("cannot import module 'gone'")

    res = asyncio.run(
        PassthroughInvoker(resolve=boom).invoke(Passthrough(target="gone:f"), _call())
    )
    assert res.is_error is True and isinstance(res.content, str) and "gone" in res.content


# -- timeout bounds a hang (Q3) ----------------------------------------------


def test_async_hang_is_bounded_by_the_timeout() -> None:
    async def impl(a: dict[str, Any]) -> str:
        await asyncio.sleep(5)
        return "never"

    start = time.monotonic()
    res = _run(_invoker({"m:f": impl}), "m:f", timeout_s=0.1)
    assert res.is_error is True and "timed out" in res.content
    assert time.monotonic() - start < 0.35


def test_per_marker_timeout_overrides_the_invoker_default() -> None:
    async def impl(a: dict[str, Any]) -> str:
        await asyncio.sleep(5)
        return "never"

    inv = _invoker({"m:f": impl}, default_timeout_s=10.0)
    res = _run(inv, "m:f", timeout_s=0.1)  # the marker's timeout wins
    assert res.is_error is True and "timed out" in res.content


# -- sync callables do not serialise the scheduler (the DF-211 AC) -----------


def test_four_concurrent_sync_callables_do_not_serialise() -> None:
    def blocking(a: dict[str, Any]) -> str:
        time.sleep(0.2)
        return "done"

    inv = _invoker({"m:f": blocking})

    async def race() -> tuple[list[Any], float]:
        start = time.monotonic()
        results = await asyncio.gather(
            *(inv.invoke(Passthrough(target="m:f"), _call()) for _ in range(4))
        )
        return results, time.monotonic() - start

    results, elapsed = asyncio.run(race())
    assert all(r.is_error is False for r in results)
    assert elapsed < 0.4, f"sync callables serialised: {elapsed:.3f}s"


# -- resolve_impl (used at validate time and by the invoker) ------------------


def test_resolve_impl_returns_the_callable() -> None:
    func = resolve_impl("json:dumps")  # any importable callable
    assert func({"a": 1}) == '{"a": 1}'


@pytest.mark.parametrize(
    "target, needle",
    [
        ("no_colon", "one colon"),
        ("mod:", "both a module and a function"),
        ("nonexistent_xyz:f", "cannot import module"),
        ("json:not_a_function_xyz", "has no attribute"),
        ("json:__doc__", "not callable"),
    ],
)
def test_resolve_impl_reports_bad_targets(target: str, needle: str) -> None:
    with pytest.raises(ImplResolutionError, match=needle):
        resolve_impl(target)

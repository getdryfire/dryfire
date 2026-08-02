"""SPIKE-004 — proves every acceptance criterion. Run: `make spike-passthrough`
or `uv run pytest spikes/004_passthrough/test_passthrough.py -q`.

pytest's default "prepend" import mode puts this file's directory on sys.path, so
`resolve_impl("sample_impls:...")` exercises the real sys.path resolution path.
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
import time
from pathlib import Path

import pytest

from invoke import DEFAULT_TIMEOUT_S, invoke
from resolver import ImplResolutionError, resolve_impl

# --- Q2 / AC: import resolution (validate time, zero network) ----------------


def test_resolves_module_on_syspath() -> None:
    func = resolve_impl("sample_impls:echo_city")
    assert func({"city": "SF"}) == {"city": "SF", "temp_f": 65}


def test_resolves_from_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A module that is NOT on sys.path, only in the current working directory —
    # the shape of a user's own `mytools.py` sitting in their repo root.
    (tmp_path / "cwd_tool.py").write_text(
        textwrap.dedent(
            """
            def make(arguments):
                return {"ok": True}
            """
        )
    )
    monkeypatch.chdir(tmp_path)
    func = resolve_impl("cwd_tool:make")
    assert func({}) == {"ok": True}
    sys.path.remove(str(tmp_path))  # resolver inserted it; don't leak into later tests
    # An editable-installed local package reduces to this same case: the install
    # puts the package on sys.path via a .pth, so there is no separate code path.


@pytest.mark.parametrize(
    "target, needle",
    [
        ("no_colon_here", "one colon"),
        ("mod:", "both a module and a function"),
        (":func", "both a module and a function"),
        ("does_not_exist_xyz:f", "cannot import module"),
        ("sample_impls:not_a_function", "has no attribute"),
        ("sample_impls:DEFAULT_TIMEOUT_S", "no attribute"),  # not defined there
    ],
)
def test_bad_impl_is_reported_not_crashed(target: str, needle: str) -> None:
    with pytest.raises(ImplResolutionError) as exc:
        resolve_impl(target)
    assert needle in str(exc.value)


def test_non_callable_attribute_is_rejected() -> None:
    # A module-level value that exists but is not callable.
    with pytest.raises(ImplResolutionError, match="not callable"):
        resolve_impl("sample_impls:__doc__")


# --- Q1 / AC: sync runs off the loop; async runs natively --------------------


def test_sync_callable_returns_result() -> None:
    func = resolve_impl("sample_impls:echo_city")
    res = asyncio.run(invoke(func, {"city": "NYC"}))
    assert res.is_error is False
    assert res.content == {"city": "NYC", "temp_f": 65}


def test_async_callable_awaited_natively() -> None:
    func = resolve_impl("sample_impls:echo_city_async")
    res = asyncio.run(invoke(func, {"city": "LA"}))
    assert res.is_error is False
    assert res.content == {"city": "LA", "temp_f": 66}


def test_four_sync_impls_do_not_serialise() -> None:
    # AC: 4 concurrent, each sleeping 200ms, wall-clock under 400ms.
    func = resolve_impl("sample_impls:blocking_sleep")

    async def run_four() -> list[object]:
        return await asyncio.gather(
            *(invoke(func, {"seconds": 0.2}) for _ in range(4))
        )

    start = time.monotonic()
    results = asyncio.run(run_four())
    elapsed = time.monotonic() - start
    assert all(r.is_error is False for r in results)
    assert elapsed < 0.4, f"serialised: {elapsed:.3f}s"


# --- AC: a raise becomes an error result, the run continues ------------------


def test_raising_callable_becomes_error_result() -> None:
    func = resolve_impl("sample_impls:boom")
    res = asyncio.run(invoke(func, {}))
    assert res.is_error is True
    assert "the real tool failed" in res.content
    # No exception escaped invoke() — the loop would carry on to the next call.


# --- Q3 / AC: a hang is bounded by the timeout -------------------------------


def test_sync_hang_does_not_block_the_scheduler() -> None:
    # The property that matters: a wedged sync impl must not stall the other
    # concurrent cases. `wait_for` returns control to the loop at the timeout;
    # a fast call running alongside it completes on schedule. Measured INSIDE the
    # loop, because loop *teardown* separately joins the abandoned thread (below).
    hang = resolve_impl("sample_impls:hangs")
    fast = resolve_impl("sample_impls:echo_city")

    async def race() -> tuple[object, object, float]:
        start = time.monotonic()
        wedged, quick = await asyncio.gather(
            invoke(hang, {"seconds": 0.5}, timeout_s=0.1),
            invoke(fast, {"city": "SF"}),
        )
        return wedged, quick, time.monotonic() - start

    wedged, quick, elapsed = asyncio.run(race())
    assert wedged.is_error is True and "timed out" in wedged.content
    assert quick.is_error is False  # the neighbour was not held hostage
    assert elapsed < 0.35, f"scheduler blocked by the hang: {elapsed:.3f}s"


def test_abandoned_sync_thread_is_joined_at_loop_shutdown() -> None:
    # The nuance you cannot design away: `wait_for` bounds the *wait*, not the
    # *work*. Python cannot kill a thread, so a wedged sync impl runs to
    # completion; `asyncio.run`'s executor shutdown joins it. So while the loop
    # lives the scheduler is bounded (test above), the *process* still pays the
    # abandoned thread's full runtime on teardown. This is the honest cost of the
    # no-sandbox stance — FINDINGS.md Q1/Q3 document it; DF-211 must not hide it.
    func = resolve_impl("sample_impls:hangs")
    start = time.monotonic()
    asyncio.run(invoke(func, {"seconds": 0.4}, timeout_s=0.05))
    total = time.monotonic() - start
    assert total >= 0.4, f"expected the thread to be joined on shutdown, got {total:.3f}s"


def test_async_hang_is_bounded_and_cancelled() -> None:
    func = resolve_impl("sample_impls:hangs_async")
    start = time.monotonic()
    res = asyncio.run(invoke(func, {"seconds": 5}, timeout_s=0.1))
    elapsed = time.monotonic() - start
    assert res.is_error is True
    assert elapsed < 0.35


def test_default_timeout_is_per_call() -> None:
    # Q3 verdict: the bound is per invocation, not per case. The default is a
    # constant on invoke(), applied to each call independently.
    assert DEFAULT_TIMEOUT_S == 30.0

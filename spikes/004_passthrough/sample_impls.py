"""SPIKE-004 — sample passthrough impls used to prove the acceptance criteria.

These stand in for user code named by `impl: sample_impls:func`. Each takes the
tool arguments as a single dict (the calling convention `invoke()` fixes).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


def echo_city(arguments: dict[str, Any]) -> dict[str, Any]:
    """A plain sync impl — the common case (looks up something, returns a dict)."""
    return {"city": arguments.get("city", "?"), "temp_f": 65}


async def echo_city_async(arguments: dict[str, Any]) -> dict[str, Any]:
    """A native async impl — awaited directly, no thread."""
    await asyncio.sleep(0)
    return {"city": arguments.get("city", "?"), "temp_f": 66}


def blocking_sleep(arguments: dict[str, Any]) -> str:
    """A sync impl that blocks (stands in for a real, slow HTTP call). Proves that
    four of these run concurrently rather than serialising."""
    time.sleep(arguments.get("seconds", 0.2))
    return "done"


def boom(arguments: dict[str, Any]) -> str:
    """A raising impl — becomes ToolResult(is_error=True); the run continues."""
    raise RuntimeError("the real tool failed")


def hangs(arguments: dict[str, Any]) -> str:
    """A sync impl that hangs far longer than any timeout — proves the bound."""
    time.sleep(arguments.get("seconds", 30))
    return "eventually"


async def hangs_async(arguments: dict[str, Any]) -> str:
    """An async impl that hangs — cancelled cleanly by the timeout (unlike sync)."""
    await asyncio.sleep(arguments.get("seconds", 30))
    return "eventually"

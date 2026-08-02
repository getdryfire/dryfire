"""The real Clock: `asyncio.sleep` (DF-206)."""

from __future__ import annotations

import asyncio


class SystemClock:
    """A Clock backed by the event loop. The only clock used in production;
    tests inject a FrozenClock so backoff never actually waits."""

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

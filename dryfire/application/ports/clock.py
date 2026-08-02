"""The Clock driven port (ARCHITECTURE §2, DF-206).

The only place the system waits on wall-clock time is retry backoff. Routing that
sleep through a port lets the retry tests assert the backoff *sequence* without
actually sleeping — a `FrozenClock` records the requested delays and returns
immediately, so the suite stays fast and deterministic.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """A source of delay. Kept to the single operation the system needs."""

    async def sleep(self, seconds: float) -> None:
        """Wait `seconds` (a real clock actually waits; a fake records and returns)."""
        ...

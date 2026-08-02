"""Budget assertions: cost_under, latency_under_ms (SPEC §6.2, DF-207).

Cost is **advisory** (SPEC §3.2): the bundled price table can be stale and an
unknown model has no price at all. So a cost gate on an unpriced model does not
quietly pass — it fails, names the model, and says the number is advisory. A
green check that proves nothing is worse than a red one.

Latency is the summed **model** latency across turns — it excludes mock
resolution and retry backoff (those are not the model's time). Under cassette
replay it is the *recorded* latency, not replay time; a replayed run is not a
latency measurement.

Adding these touched two things (SPEC §6.3): this file and one import in the
registry. Nothing in the loop, scheduler, or reporters.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import RootModel

from dryfire.domain.assertions.base import AssertionResult, register
from dryfire.domain.assertions.trajectory import render_trajectory
from dryfire.domain.model.trace import Trace


@register
class CostUnder:
    """Advisory cost must be under a USD limit. An unpriced model fails loudly."""

    kind: ClassVar[str] = "cost_under"

    class Args(RootModel[float]):
        pass

    def __init__(self, args: Any) -> None:
        self._limit: float = args.root

    def evaluate(self, trace: Trace) -> AssertionResult:
        trajectory = render_trajectory(trace)
        description = f"cost_under: ${self._limit}"
        expected = f"advisory cost under ${self._limit}"
        cost = trace.total_cost_usd
        if cost is None:
            model = trace.model or "unknown"
            return AssertionResult(
                kind=self.kind, description=description, passed=False,
                message=(
                    f"pricing unavailable for model {model!r}; cost is advisory "
                    "(SPEC §3.2), so an unpriced model cannot satisfy a cost gate"
                ),
                expected=expected, actual=trajectory,
            )
        passed = cost < self._limit
        return AssertionResult(
            kind=self.kind, description=description, passed=passed,
            message="" if passed else f"advisory cost ${cost:.6f} is not under ${self._limit}",
            expected=expected, actual=f"{trajectory}\n${cost:.6f}",
        )


@register
class LatencyUnderMs:
    """Summed per-turn model latency must be under a millisecond limit. Excludes
    mock resolution and retry backoff."""

    kind: ClassVar[str] = "latency_under_ms"

    class Args(RootModel[int]):
        pass

    def __init__(self, args: Any) -> None:
        self._limit: int = args.root

    def evaluate(self, trace: Trace) -> AssertionResult:
        latency = sum(turn.response.latency_ms for turn in trace.turns)
        passed = latency < self._limit
        trajectory = render_trajectory(trace)
        return AssertionResult(
            kind=self.kind, description=f"latency_under_ms: {self._limit}", passed=passed,
            message=(
                "" if passed else
                f"model latency {latency}ms is not under {self._limit}ms "
                "(sums per-turn model latency; excludes mock resolution and retry backoff)"
            ),
            expected=f"model latency under {self._limit}ms",
            actual=f"{trajectory}\n{latency}ms",
        )

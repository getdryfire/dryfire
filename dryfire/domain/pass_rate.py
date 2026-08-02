"""Pass-rate statistics for `repeat: N` (DF-305, SPIKE-007). Pure domain arithmetic.

`repeat` reports `k/N`. A bare `3/5` printed as if it were a measurement, when its
confidence interval spans most of the unit interval, is the kind of number that drives
bad decisions. The Wilson score interval is the honest companion — well-behaved at the
small N and extreme p̂ (0/N, N/N) where the naive normal interval breaks — and needs
nothing but `math.sqrt`.
"""

from __future__ import annotations

import math

# The smallest N SPIKE-007 found worth reporting: below it the interval is so wide the
# rate is a smoke signal, not a measurement. The tool WARNS below this, never refuses.
MIN_MEANINGFUL_REPEAT = 5

# 95% two-sided. The z for other levels is the only knob; kept explicit, not a dependency.
Z_95 = 1.959963984540054


def wilson_interval(passes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval for `passes` successes in `total` trials, clamped to
    [0, 1]. Correct at the boundaries a normal approximation gets wrong: `(5, 5)` is not
    `(1.0, 1.0)` — it honestly reports residual uncertainty below 1.0."""
    if total <= 0:
        raise ValueError("total must be positive")
    if not 0 <= passes <= total:
        raise ValueError("need 0 <= passes <= total")
    p = passes / total
    z2 = z * z
    denom = 1 + z2 / total
    centre = (p + z2 / (2 * total)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total))
    return (max(0.0, centre - half), min(1.0, centre + half))

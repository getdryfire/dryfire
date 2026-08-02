"""SPIKE-007 — pass-rate statistics (no dependency, this is arithmetic).

`repeat: N` reports `k/N`. A bare `3/5` printed as if it were a measurement, when the
confidence interval spans most of the unit interval, is the kind of number that drives
bad decisions. The Wilson score interval is the honest companion: it is well-behaved at
the small N and extreme p̂ (0/N, N/N) where the naive normal interval breaks, and it
needs nothing but `math.sqrt`.
"""

from __future__ import annotations

import math

# 95% two-sided. z for other levels is the only knob; kept explicit, not a dependency.
Z_95 = 1.959963984540054


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval for `k` successes in `n` trials, clamped to [0, 1].

    Correct at the boundaries a normal approximation gets wrong: `wilson_interval(5, 5)`
    is not (1.0, 1.0) — it honestly reports residual uncertainty below 1.0."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= k <= n:
        raise ValueError("need 0 <= k <= n")
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def interval_width(k: int, n: int, z: float = Z_95) -> float:
    """How wide the 95% interval is — the single number that says whether `k/N` means
    anything. A width near 1.0 means the pass rate is essentially unconstrained."""
    lo, hi = wilson_interval(k, n, z)
    return hi - lo


def meaningfulness_note(n: int, *, min_n: int) -> str | None:
    """A one-line warning when N is below the recommended minimum — the tool warns, it
    never refuses (a user measuring flakiness at N=3 is doing something, just not much)."""
    if n >= min_n:
        return None
    return (
        f"repeat: {n} is below the recommended minimum of {min_n}; the pass rate has a "
        f"wide confidence interval and should be read as a smoke signal, not a measurement"
    )

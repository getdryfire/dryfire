"""SPIKE-007 proof — the Wilson pass-rate interval (no dependency).

    uv run pytest spikes/007_repeat/test_stats.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from stats import interval_width, meaningfulness_note, wilson_interval  # noqa: E402


def test_interval_is_within_the_unit_interval() -> None:
    for n in range(1, 30):
        for k in range(n + 1):
            lo, hi = wilson_interval(k, n)
            assert 0.0 <= lo <= hi <= 1.0


def test_boundaries_report_residual_uncertainty() -> None:
    # The reason to use Wilson over the naive interval: 5/5 is NOT (1.0, 1.0).
    lo, hi = wilson_interval(5, 5)
    assert hi == 1.0 and lo < 1.0
    lo0, hi0 = wilson_interval(0, 5)
    assert lo0 == 0.0 and hi0 > 0.0


def test_width_shrinks_as_n_grows() -> None:
    # Observed ~80%: the interval only tightens slowly. This is the honesty the
    # reported number needs — even N=20 is ±0.17.
    widths = {n: interval_width(k, n) for n, k in [(5, 4), (10, 8), (20, 16)]}
    assert widths[5] > widths[10] > widths[20]
    assert widths[5] > 0.55   # 4/5 is almost unconstrained
    assert widths[20] < 0.40  # 16/20 still ±0.17


def test_small_n_gets_a_warning_but_never_a_refusal() -> None:
    assert meaningfulness_note(3, min_n=5) is not None
    assert meaningfulness_note(5, min_n=5) is None
    assert meaningfulness_note(20, min_n=5) is None


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError):
        wilson_interval(3, 0)
    with pytest.raises(ValueError):
        wilson_interval(6, 5)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

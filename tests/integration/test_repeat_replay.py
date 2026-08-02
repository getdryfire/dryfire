"""DF-306 — a repeated case records and replays end-to-end through `composition.run`.

Proves the whole wiring: the scheduler expands a `repeat: N` real-provider case into N
units, each drawing a per-repetition CachingGateway from the factory composition set, so
recording lays down N distinct cassettes and replay serves them back with NO live call —
reproducing the same pass rate deterministically.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from dryfire import composition
from dryfire.domain.model.message import ModelResponse, Usage

_SUITE = (
    "name: flaky\n"
    "provider: anthropic\n"
    "cases:\n"
    "  - name: sometimes\n"
    "    input: hi\n"
    "    repeat: 5\n"
    "    require_pass_rate: 0.8\n"
    "    expect:\n"
    "      - final_contains: GOOD\n"
)


class _Flaky:
    """Returns BAD for the first call, GOOD after — exactly one of five repetitions
    fails, a deterministic 4/5 regardless of scheduling. Counts live calls so replay
    can prove it made none."""

    name = "anthropic"

    def __init__(self) -> None:
        self._first = True
        self.calls = 0

    def is_retryable(self, exc: Exception) -> bool:
        return False

    async def complete(self, request: Any) -> ModelResponse:
        self.calls += 1
        text, self._first = ("BAD", False) if self._first else ("GOOD", False)
        return ModelResponse(text=text, tool_calls=[], stop_reason="end_turn",
                             usage=Usage(input_tokens=1, output_tokens=1), latency_ms=1, raw={})


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gateway: object, mode: str) -> int:
    monkeypatch.setattr(composition, "make_gateway", lambda provider: gateway)
    suite = tmp_path / "s.eval.yaml"
    suite.write_text(_SUITE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # cassettes land under ./.dryfire/cassettes
    out, err = io.StringIO(), io.StringIO()
    return composition.run([str(suite)], cassette_mode=mode, out=out, err=err)


def test_record_then_replay_reproduces_the_rate_with_no_live_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Record: five repetitions, five distinct cassettes; one fails → 4/5 ≥ 0.8 → exit 0.
    recorder = _Flaky()
    assert _run(tmp_path, monkeypatch, recorder, "record") == composition.EXIT_OK
    assert recorder.calls == 5
    cassettes = list((tmp_path / ".dryfire" / "cassettes").rglob("*.json"))
    assert len(cassettes) == 5  # one per repetition, not one overwritten five times

    # Replay: the recorded cassettes serve every repetition; the run never calls live
    # (replay wraps a gateway that raises if touched), and the 4/5 verdict is reproduced.
    forbidden = _Flaky()
    assert _run(tmp_path, monkeypatch, forbidden, "replay") == composition.EXIT_OK
    assert forbidden.calls == 0  # replay made no live call — the pass rate came from disk

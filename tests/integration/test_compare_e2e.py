"""DF-307 — `compare` execution end-to-end through `composition.compare`.

Offline: `make_gateway` is monkeypatched to a request-driven gateway that varies its
answer by the requested model, so `--models` produces genuinely different columns
without a network. Verifies the matrix shape, failed-column isolation, the pre-execution
cost gate, and the one-axis-at-a-time rule.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from dryfire import composition
from dryfire.domain.model.message import ModelResponse, Usage

_SUITE = (
    "name: compare_me\n"
    "provider: anthropic\n"
    "cases:\n"
    "  - name: a\n    input: hi\n    expect:\n      - final_contains: GOOD\n"
    "  - name: b\n    input: hi\n    expect:\n      - final_contains: GOOD\n"
)


class _ByModel:
    """Answers GOOD for `good_model`, BAD for anything else, and raises for 'boom' — so
    columns diverge by model and a bad model surfaces as provider errors."""

    name = "anthropic"

    def __init__(self, good_model: str) -> None:
        self._good = good_model
        self.models_seen: list[str] = []

    def is_retryable(self, exc: Exception) -> bool:
        return False

    async def complete(self, request: Any) -> ModelResponse:
        self.models_seen.append(request.model)
        if request.model == "boom":
            raise RuntimeError("kaboom")
        text = "GOOD" if request.model == self._good else "BAD"
        return ModelResponse(text=text, tool_calls=[], stop_reason="end_turn",
                             usage=Usage(input_tokens=1, output_tokens=1), latency_ms=1, raw={})


def _compare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gateway: object,
             **kw: Any) -> tuple[int, str, str]:
    monkeypatch.setattr(composition, "make_gateway", lambda provider: gateway)
    suite = tmp_path / "s.eval.yaml"
    suite.write_text(_SUITE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    code = composition.compare([str(suite)], out=out, err=err, **kw)
    return code, out.getvalue(), err.getvalue()


def test_models_axis_produces_a_column_per_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _compare(tmp_path, monkeypatch, _ByModel("opus"),
                            models=["opus", "haiku", "sonnet"])
    # opus passes both cases; the others fail both. All three columns report.
    assert "opus" in out and "haiku" in out and "sonnet" in out
    assert "100% pass" in out  # opus column
    assert "0% pass" in out    # a losing column still reported, not aborted
    assert code == composition.EXIT_ASSERTION  # some column had a failing case


def test_a_failing_model_is_a_failed_column_others_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = _compare(tmp_path, monkeypatch, _ByModel("opus"), models=["opus", "boom"])
    assert "opus" in out and "boom" in out  # both columns present
    assert "100% pass" in out               # opus still completed
    assert code == composition.EXIT_PROVIDER  # the boom column errored → exit 3


def test_models_and_prompts_together_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _, err = _compare(tmp_path, monkeypatch, _ByModel("opus"),
                            models=["a"], prompts=["p.txt"])
    assert code == composition.EXIT_CONFIG
    assert "one axis" in err.lower()


def test_no_axis_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err = _compare(tmp_path, monkeypatch, _ByModel("opus"))
    assert code == composition.EXIT_CONFIG
    assert "--models" in err


def test_cost_estimate_is_shown_and_the_threshold_gate_blocks_without_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gw = _ByModel("opus")
    # 3 models × 2 cases = 6 runs; threshold 3 → blocked, and nothing runs.
    code, out, err = _compare(tmp_path, monkeypatch, gw,
                              models=["opus", "haiku", "sonnet"], threshold=3)
    assert "6 runs" in out                 # the estimate is shown before execution
    assert code == composition.EXIT_CONFIG  # blocked
    assert "--yes" in err
    assert gw.models_seen == []             # nothing was executed


def test_yes_bypasses_the_threshold_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gw = _ByModel("opus")
    code, out, _ = _compare(tmp_path, monkeypatch, gw,
                            models=["opus", "haiku", "sonnet"], threshold=3, yes=True)
    assert gw.models_seen  # it ran
    assert "opus" in out


def test_cli_compare_command_is_wired_and_maps_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from dryfire.adapters.driving.cli.app import app

    monkeypatch.setattr(composition, "make_gateway", lambda provider: _ByModel("opus"))
    suite = tmp_path / "s.eval.yaml"
    suite.write_text(_SUITE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["compare", "--models", "opus,haiku", str(suite)])
    assert result.exit_code == composition.EXIT_ASSERTION  # haiku fails a case
    assert "opus" in result.output and "haiku" in result.output

"""DF-204 — the cassette headline: record a suite, then replay it fully offline.

Replay must serve every turn from disk with no live call — the value proposition
is a CI run that is free, deterministic, and airgapped. Proven two ways: the
replay gateway (`_NoLiveGateway`) raises if a live call is attempted, and
`make_gateway` is patched to raise during replay, so a green replay proves nothing
live was built or called. Covers the multi-turn (turn 2+) case — the SPIKE-002
failure mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dryfire import composition
from dryfire.adapters.driving.cli.app import app
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall

runner = CliRunner()

# An Anthropic (real-provider) suite: two turns — a tool call, then a text answer.
_SUITE = (
    "name: lookup_suite\n"
    "tools:\n  - name: lookup\n    input_schema: {type: object}\n"
    "mocks:\n  lookup:\n    - return: {found: true}\n"
    "cases:\n  - name: does_lookup\n    input: find it\n"
    "    expect:\n      - calls_tool: lookup\n"
)


def _response(text: str | None = None, calls: list[ToolCall] | None = None) -> ModelResponse:
    tool_calls = calls or []
    return ModelResponse(
        text=text, tool_calls=tool_calls,
        stop_reason="tool_use" if tool_calls else "end_turn",
        usage=Usage(input_tokens=1, output_tokens=1), latency_ms=5, raw={"id": "m"},
    )


class _TurnGateway:
    """Turn 0: call `lookup`. Turn 1: a text answer. Two turns → two cassettes."""

    name = "anthropic"

    async def complete(self, request: Any) -> ModelResponse:
        if (len(request.messages) - 1) // 2 == 0:
            return _response(calls=[ToolCall(id="c0", name="lookup", arguments={})])
        return _response(text="done")


def test_record_then_replay_is_fully_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    suite = tmp_path / "lookup.eval.yaml"
    suite.write_text(_SUITE, encoding="utf-8")
    cassettes = tmp_path / ".dryfire" / "cassettes"

    # RECORD: a live (injected) gateway drives two turns onto disk.
    monkeypatch.setattr(composition, "make_gateway", lambda provider: _TurnGateway())
    rec = runner.invoke(app, ["run", str(suite), "--cassette-mode", "record"])
    assert rec.exit_code == 0, rec.output
    assert len(list(cassettes.rglob("*.json"))) == 2  # both turns recorded

    # REPLAY: no gateway may even be built. A green run proves full airgap.
    def forbidden(provider: str) -> Any:
        raise AssertionError("replay must not build a live gateway")

    monkeypatch.setattr(composition, "make_gateway", forbidden)
    play = runner.invoke(app, ["run", str(suite), "--cassette-mode", "replay"])
    assert play.exit_code == 0, play.output
    assert "cached" in play.output.lower()  # cache hits are visible (DF-204 piece 4)

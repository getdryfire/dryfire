"""AC-015 — the CLI surface and contractual exit codes (SPEC §7, §7.1).

Driven through `typer.testing.CliRunner`. Exit codes are the public interface, so
there is one test per code. The gateway factory is monkeypatched so nothing here
touches the network — and `validate` is asserted to never build one at all.
"""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dryfire import composition
from dryfire.adapters.driving.cli.app import app
from dryfire.domain.model.message import ModelResponse, Usage
from dryfire.domain.model.tooling import ToolCall

runner = CliRunner()

_BROKEN = Path(__file__).parent.parent / "fixtures" / "broken" / "all_five.eval.yaml"

_PASS = (
    "name: passing\ncases:\n  - name: greets\n    input: hi\n"
    "    expect:\n      - final_contains: done\n"
)
_FAIL = (
    "name: failing\ncases:\n  - name: needs_tool\n    input: hi\n"
    "    expect:\n      - calls_tool: issue_refund\n"
)
_TAGGED = (
    "name: tagged\ntags: [smoke]\ncases:\n  - name: greets\n    input: hi\n    expect: []\n"
)
_TOOL_SUITE = (
    "name: traced\n"
    "tools:\n  - name: lookup\n    input_schema: {type: object}\n"
    "mocks:\n  lookup:\n    - return: {found: true}\n"
    "cases:\n  - name: does_lookup\n    input: find it\n    expect: []\n"
)


def _response(text: str | None = None, calls: list[ToolCall] | None = None) -> ModelResponse:
    tool_calls = calls or []
    return ModelResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason="tool_use" if tool_calls else "end_turn",
        usage=Usage(input_tokens=1, output_tokens=1),
        latency_ms=0,
        raw={},
    )


class _TextGateway:
    """Always answers with the same text turn."""

    name = "fake"

    def __init__(self, text: str = "done") -> None:
        self._text = text
        self.models: list[str] = []

    async def complete(self, request: Any) -> ModelResponse:
        self.models.append(request.model)
        return _response(text=self._text)


class _RaisingGateway:
    name = "fake"

    async def complete(self, request: Any) -> ModelResponse:
        raise ConnectionError("provider unreachable")


class _TurnGateway:
    """One tool call, then a text turn — for the trace command."""

    name = "fake"

    async def complete(self, request: Any) -> ModelResponse:
        if (len(request.messages) - 1) // 2 == 0:
            return _response(calls=[ToolCall(id="c0", name="lookup", arguments={})])
        return _response(text="done")


def _use_gateway(monkeypatch: pytest.MonkeyPatch, gateway: object) -> None:
    monkeypatch.setattr(composition, "make_gateway", lambda provider: gateway)


def _write(tmp_path: Path, body: str, name: str = "s.eval.yaml") -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


# -- One test per exit code -------------------------------------------------


def test_exit_0_when_all_cases_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_gateway(monkeypatch, _TextGateway("done"))
    result = runner.invoke(app, ["run", _write(tmp_path, _PASS)])
    assert result.exit_code == 0


def test_exit_1_on_assertion_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_gateway(monkeypatch, _TextGateway("done"))  # never calls issue_refund
    result = runner.invoke(app, ["run", _write(tmp_path, _FAIL)])
    assert result.exit_code == 1


def test_exit_2_on_spec_error() -> None:
    result = runner.invoke(app, ["run", str(_BROKEN)])
    assert result.exit_code == 2


def test_exit_3_on_provider_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_gateway(monkeypatch, _RaisingGateway())
    result = runner.invoke(app, ["run", _write(tmp_path, _PASS)])
    assert result.exit_code == 3


def test_spec_error_beats_an_unreachable_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The provider would raise (→ 3), but config is checked first → 2.
    _use_gateway(monkeypatch, _RaisingGateway())
    result = runner.invoke(app, ["run", str(_BROKEN)])
    assert result.exit_code == 2


# -- validate ---------------------------------------------------------------


def test_validate_ok_makes_zero_network_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(provider: str) -> object:
        raise AssertionError("validate must not build a gateway")

    monkeypatch.setattr(composition, "make_gateway", explode)
    result = runner.invoke(app, ["validate", _write(tmp_path, _PASS)])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_validate_broken_fixture_prints_positioned_errors() -> None:
    result = runner.invoke(app, ["validate", str(_BROKEN)])
    assert result.exit_code == 2
    assert "error:" in result.output
    assert "-->" in result.output  # positioned caret output


# -- trace ------------------------------------------------------------------


def test_trace_prints_every_turn_including_tool_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_gateway(monkeypatch, _TurnGateway())
    result = runner.invoke(app, ["trace", "traced::does_lookup", _write(tmp_path, _TOOL_SUITE)])
    assert result.exit_code == 0
    assert "lookup" in result.output
    assert "tool_result" in result.output
    assert "found" in result.output  # the mock's return value


# -- filtering, overrides, errors, help -------------------------------------


def test_filter_and_tag_compose_zero_match_is_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_gateway(monkeypatch, _TextGateway())
    # Right tag, but a filter that matches no case name → 0 with a clear message.
    result = runner.invoke(
        app, ["run", _write(tmp_path, _TAGGED), "--tag", "smoke", "--filter", "nonexistent"]
    )
    assert result.exit_code == 0
    assert "no cases matched" in result.output


def test_model_flag_overrides_project_and_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _TextGateway("done")
    _use_gateway(monkeypatch, gateway)
    suite = (
        "name: passing\nmodel: suite-model\ncases:\n"
        "  - name: greets\n    input: hi\n    expect: []\n"
    )
    result = runner.invoke(app, ["run", _write(tmp_path, suite), "--model", "cli-model"])
    assert result.exit_code == 0
    assert gateway.models == ["cli-model"]  # the override reached the wire, not "suite-model"


def test_internal_error_is_clean_and_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(provider: str) -> object:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(composition, "make_gateway", boom)
    result = runner.invoke(app, ["run", _write(tmp_path, _PASS)])
    assert result.exit_code == 2
    assert "please report" in result.output.lower()
    # The RuntimeError was handled into a clean exit, not surfaced as a traceback.
    assert not isinstance(result.exception, RuntimeError)


def test_debug_flag_surfaces_the_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(provider: str) -> object:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(composition, "make_gateway", boom)
    result = runner.invoke(app, ["run", _write(tmp_path, _PASS), "--debug"])
    assert isinstance(result.exception, RuntimeError)


@pytest.mark.parametrize("argv", [[], ["init"], ["run"], ["validate"], ["trace"], ["prune"]])
def test_help_exits_zero_for_every_command(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--help"])
    assert result.exit_code == 0


# -- AC-016: scripted fake provider + skip-on-missing-key -------------------

_FAKE_SUITE = (
    "name: hello\n"
    "provider: fake\n"
    "tools:\n  - name: get_weather\n    input_schema: {type: object}\n"
    "mocks:\n  get_weather:\n    - return: {temp_f: 65}\n"
    "cases:\n  - name: reports_weather\n    input: weather in SF?\n"
    "    script:\n"
    "      - tool_call: {name: get_weather, arguments: {city: SF}}\n"
    '      - text: "It is 65F in SF."\n'
    "    expect:\n"
    "      - calls_tool: get_weather\n"
    "      - tool_args: {tool: get_weather, match: {city: SF}}\n"
    '      - final_contains: "65"\n'
)

_ANTHROPIC_SUITE = (
    "name: needs_key\nprovider: anthropic\n"
    "cases:\n  - name: c\n    input: hi\n    expect: []\n"
)


def test_fake_scripted_suite_runs_green_with_no_key_and_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No monkeypatch of make_gateway: the fake gateway is built from the script,
    # so this is a genuinely offline run. Prove no key is needed.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(app, ["run", _write(tmp_path, _FAKE_SUITE)])
    assert result.exit_code == 0, result.output


def test_missing_key_skips_the_case_with_a_note_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(app, ["run", _write(tmp_path, _ANTHROPIC_SUITE)])
    assert result.exit_code == 0, result.output
    assert "skip" in result.output.lower()
    assert "ANTHROPIC_API_KEY" in result.output


def test_cost_under_passes_for_a_priced_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pricing runs before assertions (DF-207), so cost_under sees a real cost.
    _use_gateway(monkeypatch, _TextGateway("done"))
    suite = (
        "name: cost\nmodel: claude-sonnet-4-6\ncases:\n  - name: cheap\n    input: hi\n"
        "    expect:\n      - cost_under: 1.0\n"
    )
    result = runner.invoke(app, ["run", _write(tmp_path, suite)])
    assert result.exit_code == 0, result.output


def test_cost_under_fails_loudly_for_an_unknown_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_gateway(monkeypatch, _TextGateway("done"))
    suite = (
        "name: cost\nmodel: gpt-9-does-not-exist\ncases:\n  - name: unpriced\n    input: hi\n"
        "    expect:\n      - cost_under: 1.0\n"
    )
    result = runner.invoke(app, ["run", _write(tmp_path, suite)])
    assert result.exit_code == 1  # must not silently pass
    assert "pricing unavailable" in result.output


def test_max_retries_zero_disables_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The gateway is wrapped in RetryingGateway; with --max-retries 0 a retryable
    # failure is not retried, so the provider is called exactly once (exit 3).
    class _RetryableGateway:
        name = "anthropic"

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, request: Any) -> ModelResponse:
            self.calls += 1
            raise RuntimeError("transient")

        def is_retryable(self, exc: Exception) -> bool:
            return True

    gateway = _RetryableGateway()
    _use_gateway(monkeypatch, gateway)
    result = runner.invoke(app, ["run", _write(tmp_path, _PASS), "--max-retries", "0"])
    assert result.exit_code == 3
    assert gateway.calls == 1  # no retries


def test_provider_openai_runs_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A `provider: openai` suite, driven by a REAL recorded OpenAI payload parsed
    # by the adapter's from_wire — proves the second provider wires end to end.
    import json as _json

    from dryfire.adapters.driven.providers.openai import from_wire

    fixture = _json.loads(
        (Path(__file__).parents[1] / "fixtures" / "openai" / "text_only.json").read_text()
    )

    class _OpenAIFixtureGateway:
        name = "openai"

        async def complete(self, request: Any) -> ModelResponse:
            return from_wire(fixture, latency_ms=1)

    _use_gateway(monkeypatch, _OpenAIFixtureGateway())
    suite = (
        "name: oai\nprovider: openai\ncases:\n  - name: c\n    input: hi\n"
        "    expect:\n      - final_contains: Tuesday\n"
    )
    result = runner.invoke(app, ["run", _write(tmp_path, suite)])
    assert result.exit_code == 0, result.output


def test_cassette_replay_miss_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No cassettes exist → a replay miss → provider_error → exit 3, and no gateway
    # is ever built (replay is airgapped).
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def forbidden(provider: str) -> object:
        raise AssertionError("replay must not build a gateway")

    monkeypatch.setattr(composition, "make_gateway", forbidden)
    result = runner.invoke(app, ["run", _write(tmp_path, _PASS), "--cassette-mode", "replay"])
    assert result.exit_code == 3, result.output


def test_invalid_cassette_mode_is_a_config_error_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", _write(tmp_path, _PASS), "--cassette-mode", "nonsense"])
    assert result.exit_code == 2
    assert "cassette-mode" in result.output


def test_mixed_run_fake_passes_while_keyless_anthropic_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(
        app,
        [
            "run",
            _write(tmp_path, _FAKE_SUITE, "hello.eval.yaml"),
            _write(tmp_path, _ANTHROPIC_SUITE, "needs_key.eval.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "skip" in result.output.lower()
    assert "needs_key" in result.output

"""AC-016 — `init` scaffold and the 60-second target (SPEC §1.6).

The load-bearing acceptance test: `init` then `run` goes green with no API key
and no network, driven end-to-end through the CLI. The measured cold-start number
is produced separately by `scripts/measure_cold_start.sh`; this proves the
*behaviour* the stopwatch depends on.
"""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agentcheck.adapters.driving.cli.app import app

runner = CliRunner()

# The exact command `init` tells the user to run next, in the in-place case.
NEXT_COMMAND = "agentcheck run"

_SCAFFOLDED = [
    "agentcheck.yaml",
    "evals/hello.eval.yaml",
    "evals/refund_agent.eval.yaml",
    "evals/schemas/escalate_to_human.json",
    "evals/README.md",
]


def _init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> Result:
    monkeypatch.chdir(tmp_path)
    return runner.invoke(app, ["init", *args])


def test_init_creates_the_whole_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _init(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    for rel in _SCAFFOLDED:
        assert (tmp_path / rel).is_file(), f"missing {rel}"


def test_init_prints_the_exact_next_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _init(tmp_path, monkeypatch)
    assert NEXT_COMMAND in result.output


def test_init_then_run_is_green_with_no_key_and_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This is the acceptance criterion: the printed command, run verbatim, passes.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    init_result = _init(tmp_path, monkeypatch)
    assert init_result.exit_code == 0

    # `agentcheck run` — the command init told us to run — with cwd in the project.
    run_result = runner.invoke(app, NEXT_COMMAND.split()[1:])
    assert run_result.exit_code == 0, run_result.output
    assert "hello_weather" in run_result.output


def test_keyed_example_is_skipped_not_failed_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _init(tmp_path, monkeypatch)

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0, result.output
    assert "skip" in result.output.lower()
    assert "refund_agent" in result.output


def test_both_scaffolded_suites_validate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0, result.output
    assert "2 suite(s)" in result.output


def test_init_refuses_a_non_empty_dir_and_lists_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agentcheck.yaml").write_text("PRECIOUS", encoding="utf-8")

    result = _init(tmp_path, monkeypatch)

    assert result.exit_code == 2
    assert "agentcheck.yaml" in result.output
    assert (tmp_path / "agentcheck.yaml").read_text(encoding="utf-8") == "PRECIOUS"
    assert not (tmp_path / "evals").exists()  # nothing else was laid down


def test_init_force_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "agentcheck.yaml").write_text("STALE", encoding="utf-8")

    result = _init(tmp_path, monkeypatch, "--force")

    assert result.exit_code == 0, result.output
    assert (tmp_path / "agentcheck.yaml").read_text(encoding="utf-8") != "STALE"


# -- Scaffolded YAML doubles as documentation: comment every top-level key --

_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_][\w-]*):")


@pytest.mark.parametrize(
    "rel", ["agentcheck.yaml", "evals/hello.eval.yaml", "evals/refund_agent.eval.yaml"]
)
def test_every_top_level_key_is_commented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel: str
) -> None:
    _init(tmp_path, monkeypatch)
    lines = (tmp_path / rel).read_text(encoding="utf-8").splitlines()

    for i, line in enumerate(lines):
        if not _TOP_LEVEL_KEY.match(line):
            continue
        inline = "#" in line
        prev = next((p for p in reversed(lines[:i]) if p.strip()), "")
        assert inline or prev.lstrip().startswith("#"), (
            f"{rel}: top-level key {line.split(':')[0]!r} has no explanatory comment"
        )

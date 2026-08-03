"""DF-212 / DF-310 — v0.1 and v0.2 suites run unchanged on the current version.

The YAML spec is a public contract. `v0_1_compat.eval.yaml` uses every v0.1 feature and
no later syntax; `v0_2_compat.eval.yaml` uses v0.2 features (extended + budget assertions)
and no v0.3 syntax. Both are frozen: if either ever needs editing to keep passing, that
edit is a breaking spec change and belongs in a major version — not a minor.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dryfire.adapters.driving.cli.app import app

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_V01_SUITE = _FIXTURES / "v0_1_compat.eval.yaml"
_V02_SUITE = _FIXTURES / "v0_2_compat.eval.yaml"
runner = CliRunner()


def test_v0_1_suite_validates_on_current() -> None:
    result = runner.invoke(app, ["validate", str(_V01_SUITE)])
    assert result.exit_code == 0, result.output


def test_v0_1_suite_runs_green_on_current() -> None:
    # provider: fake → no key, no network; the scripted turns drive the whole loop.
    result = runner.invoke(app, ["run", str(_V01_SUITE)])
    assert result.exit_code == 0, result.output


def test_v0_2_suite_validates_on_current() -> None:
    result = runner.invoke(app, ["validate", str(_V02_SUITE)])
    assert result.exit_code == 0, result.output


def test_v0_2_suite_runs_green_on_current() -> None:
    result = runner.invoke(app, ["run", str(_V02_SUITE)])
    assert result.exit_code == 0, result.output

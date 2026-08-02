"""DF-212 — a v0.1 suite runs unchanged on v0.2.

The v0.1 YAML spec is a public contract. `tests/fixtures/v0_1_compat.eval.yaml` uses
every v0.1 feature and no v0.2 syntax; it is frozen. If this test ever needs the
fixture edited to keep passing, that edit is a breaking spec change and belongs in a
major version — not a v0.2.x minor.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dryfire.adapters.driving.cli.app import app

_V01_SUITE = Path(__file__).parent.parent / "fixtures" / "v0_1_compat.eval.yaml"
runner = CliRunner()


def test_v0_1_suite_validates_on_v0_2() -> None:
    result = runner.invoke(app, ["validate", str(_V01_SUITE)])
    assert result.exit_code == 0, result.output


def test_v0_1_suite_runs_green_on_v0_2() -> None:
    # provider: fake → no key, no network; the scripted turns drive the whole loop.
    result = runner.invoke(app, ["run", str(_V01_SUITE)])
    assert result.exit_code == 0, result.output

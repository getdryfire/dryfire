"""AC-017 — `--version` surfaces the bundled pricing date so users can see how
stale the advisory prices are (SPEC §3.2). The CLI is a driving adapter and may
read the pricing adapter directly."""

from typer.testing import CliRunner

from agentcheck.__about__ import __version__
from agentcheck.adapters.driving.cli.app import app


def test_version_shows_app_version_and_pricing_date() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
    assert "2026-07-31" in result.stdout  # the bundled pricing _meta.updated date

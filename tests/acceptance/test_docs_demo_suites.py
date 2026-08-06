"""Every suite shipped in `docs/demo/` still parses on the current version.

The demo suites are quoted in the docs (`docs/compare.md`, `docs/redteam.md`), so a spec
change that breaks one silently ships a tutorial nobody can run. `validate` is offline and
keyless, so this guard costs nothing and belongs in `make check` rather than a workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dryfire.adapters.driving.cli.app import app

_DEMO = Path(__file__).parent.parent.parent / "docs" / "demo"
_SUITES = sorted(_DEMO.glob("*.eval.yaml"))
runner = CliRunner()


def test_demo_directory_is_not_empty() -> None:
    # Guards the glob itself: a moved directory would otherwise pass by parametrising zero cases.
    assert _SUITES, f"no demo suites found under {_DEMO}"


@pytest.mark.parametrize("suite", _SUITES, ids=lambda path: path.name)
def test_demo_suite_validates(suite: Path) -> None:
    result = runner.invoke(app, ["validate", str(suite)])
    assert result.exit_code == 0, result.output

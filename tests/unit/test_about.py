"""Smoke test: the package imports with no provider SDK and exposes its identity."""

from agentcheck.__about__ import APP_NAME, CONFIG_DIR, __version__


def test_about_constants() -> None:
    assert APP_NAME == "agentcheck"
    assert CONFIG_DIR == f".{APP_NAME}"
    assert __version__

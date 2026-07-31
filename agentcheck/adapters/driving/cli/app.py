"""Typer application. Parses flags and maps results to exit codes — no logic (AC-015)."""

import typer

from agentcheck.__about__ import APP_NAME, __version__
from agentcheck.adapters.driven.pricing.bundled import BundledPricingCatalog

app = typer.Typer(
    name=APP_NAME,
    help=f"{APP_NAME} — assert on the trajectory, not the output.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(False, "--version", help="Print the version and exit."),
) -> None:
    if version:
        # Surface how stale the bundled advisory prices are (AC-017, SPEC §3.2).
        updated = BundledPricingCatalog().updated or "unknown"
        typer.echo(f"{APP_NAME} {__version__} (pricing updated {updated})")
        raise typer.Exit(0)

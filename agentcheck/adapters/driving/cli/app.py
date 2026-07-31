"""Typer application. Parses flags and maps results to exit codes — no logic (AC-015)."""

import typer

from agentcheck.__about__ import APP_NAME, __version__

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
        typer.echo(f"{APP_NAME} {__version__}")
        raise typer.Exit(0)

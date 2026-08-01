"""Typer application. Parses flags and maps results to exit codes — no logic (AC-015).

Every command delegates to `dryfire.composition`; this module only wires flags to
those calls and turns the returned int into `typer.Exit` (SPEC §7.1 exit codes).
"""

import sys

import typer

from dryfire import composition
from dryfire.__about__ import APP_NAME, __version__
from dryfire.adapters.driven.pricing.bundled import BundledPricingCatalog

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


@app.command()
def init(
    dir_: str = typer.Option(".", "--dir", help="Directory to scaffold into."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Scaffold a runnable example project (no API key needed to run it)."""
    code = composition.init(dir_, force=force, out=sys.stdout, err=sys.stderr)
    raise typer.Exit(code)


@app.command()
def run(
    paths: list[str] = typer.Argument(None, help="Suite files to run."),
    filter_: str = typer.Option(None, "--filter", help="Substring match on case name."),
    tag: list[str] = typer.Option(None, "--tag", help="Filter by suite tag (repeatable)."),
    model: str = typer.Option(None, "--model", help="Override the model for this run."),
    concurrency: int = typer.Option(None, "--concurrency", help="Concurrent cases (default 4)."),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first failing case."),
    reporter: str = typer.Option("terminal", "--reporter", help="terminal | json."),
    json_out: str = typer.Option(None, "--json-out", help="Write full traces as JSON to PATH."),
    cassette_mode: str = typer.Option(
        None, "--cassette-mode", help="auto | record | replay | off (default off)."
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Print traces for failing cases."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks on internal errors."),
) -> None:
    """Execute suites and assert on their trajectories."""
    code = composition.run(
        paths or [],
        filter_text=filter_,
        tags=tag or [],
        model=model,
        concurrency=concurrency,
        fail_fast=fail_fast,
        reporter=reporter,
        json_out=json_out,
        cassette_mode=cassette_mode,
        verbose=verbose,
        debug=debug,
        out=sys.stdout,
        err=sys.stderr,
    )
    raise typer.Exit(code)


@app.command()
def prune(
    yes: bool = typer.Option(False, "--yes", help="Actually delete (default: dry run)."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks on internal errors."),
) -> None:
    """Delete orphaned or stale cassettes (dry run unless --yes)."""
    code = composition.prune(yes=yes, debug=debug, out=sys.stdout, err=sys.stderr)
    raise typer.Exit(code)


@app.command()
def validate(
    paths: list[str] = typer.Argument(None, help="Suite files to validate."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks on internal errors."),
) -> None:
    """Parse and validate specs — zero network calls."""
    code = composition.validate(paths or [], debug=debug, out=sys.stdout, err=sys.stderr)
    raise typer.Exit(code)


@app.command()
def trace(
    address: str = typer.Argument(..., help="The case to trace, as suite::case."),
    paths: list[str] = typer.Argument(None, help="Suite files to search."),
    model: str = typer.Option(None, "--model", help="Override the model for this run."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks on internal errors."),
) -> None:
    """Run one case and print every turn — the debugging command."""
    code = composition.trace(
        address, paths or [], model=model, debug=debug, out=sys.stdout, err=sys.stderr
    )
    raise typer.Exit(code)

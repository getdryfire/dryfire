"""Typer application. Parses flags and maps results to exit codes — no logic (AC-015).

Every command delegates to `dryfire.composition`; this module only wires flags to
those calls and turns the returned int into `typer.Exit` (SPEC §7.1 exit codes).
"""

import sys

import typer

from dryfire import composition
from dryfire.__about__ import APP_NAME, __version__
from dryfire.adapters.driven.pricing.bundled import BundledPricingCatalog
from dryfire.adapters.driven.spec.config import BUILTIN_CONCURRENCY
from dryfire.composition import BUILTIN_MAX_RETRIES

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
    concurrency: int = typer.Option(
        None, "--concurrency",
        help=f"Concurrent cases (default {BUILTIN_CONCURRENCY}).",
    ),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first failing case."),
    reporter: str = typer.Option("terminal", "--reporter", help="terminal | json | junit."),
    json_out: str = typer.Option(None, "--json-out", help="Write full traces as JSON to PATH."),
    junit_out: str = typer.Option(None, "--junit-out", help="Write JUnit XML to PATH (for CI)."),
    cassette_mode: str = typer.Option(
        None, "--cassette-mode", help="auto | record | replay | off (default off)."
    ),
    max_retries: int = typer.Option(
        None, "--max-retries",
        help=f"Retries on transient provider errors (default {BUILTIN_MAX_RETRIES}).",
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
        junit_out=junit_out,
        cassette_mode=cassette_mode,
        max_retries=max_retries,
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


def _csv(value: str | None) -> list[str]:
    """Split a comma-separated CLI value into trimmed, non-empty items."""
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


@app.command()
def compare(
    paths: list[str] = typer.Argument(None, help="Suite files to compare."),
    models: str = typer.Option(None, "--models", help="Comma-separated models (one axis)."),
    prompts: str = typer.Option(
        None, "--prompts", help="Comma-separated prompt files (the other axis)."
    ),
    concurrency: int = typer.Option(
        None, "--concurrency",
        help=f"Concurrent cases (default {BUILTIN_CONCURRENCY}).",
    ),
    cassette_mode: str = typer.Option(
        None, "--cassette-mode", help="auto | record | replay | off (default off)."
    ),
    max_retries: int = typer.Option(
        None, "--max-retries",
        help=f"Retries (default {BUILTIN_MAX_RETRIES}).",
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip the cost-confirmation prompt."),
    html_out: str = typer.Option(None, "--html-out", help="Write the matrix as HTML to PATH."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks on internal errors."),
) -> None:
    """Run one suite across N models (or prompt variants) and print the matrix."""
    code = composition.compare(
        paths or [],
        models=_csv(models),
        prompts=_csv(prompts),
        concurrency=concurrency,
        cassette_mode=cassette_mode,
        max_retries=max_retries,
        yes=yes,
        html_out=html_out,
        debug=debug,
        out=sys.stdout,
        err=sys.stderr,
    )
    raise typer.Exit(code)


@app.command()
def report(
    json_path: str = typer.Argument(..., help="A run JSON artifact (from --json-out)."),
    html_out: str = typer.Option(None, "--html-out", help="Write HTML to PATH (else stdout)."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks on internal errors."),
) -> None:
    """Regenerate a self-contained HTML report from a recorded JSON artifact — offline."""
    code = composition.report(
        json_path, html_out=html_out, debug=debug, out=sys.stdout, err=sys.stderr
    )
    raise typer.Exit(code)

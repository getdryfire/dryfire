"""DF-205 — `dryfire prune`: delete orphaned or stale cassettes.

Dry-run by default; `--yes` deletes. The load-bearing safety rule: a cassette
belonging to a suite that fails to parse is NEVER pruned — a broken spec must not
cause data loss.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dryfire.adapters.driving.cli.app import app

runner = CliRunner()


def _project(tmp_path: Path, suites: dict[str, list[str]], *, broken: bool = False) -> None:
    config = "version: 1\nsuites: [evals/*.eval.yaml]\n"
    (tmp_path / "dryfire.yaml").write_text(config, encoding="utf-8")
    evals = tmp_path / "evals"
    evals.mkdir(exist_ok=True)
    for name, cases in suites.items():
        body = f"name: {name}\ncases:\n"
        for case in cases:
            body += f"  - name: {case}\n    input: hi\n    expect: []\n"
        (evals / f"{name}.eval.yaml").write_text(body, encoding="utf-8")
    if broken:
        # Valid YAML, invalid spec (no `cases`) → load_suite returns errors.
        (evals / "broken.eval.yaml").write_text("name: broken\n", encoding="utf-8")


def _cassette(tmp_path: Path, suite: str, case: str, turn: int, fp: str, schema: int = 1) -> Path:
    directory = tmp_path / ".dryfire" / "cassettes" / suite / case
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{turn:02d}-{fp}.json"
    path.write_text(json.dumps({"schema_version": schema, "fingerprint": fp}), encoding="utf-8")
    return path


def test_dry_run_lists_candidates_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, {"good": ["c1"]})
    keep = _cassette(tmp_path, "good", "c1", 0, "aaaa000000000000")
    orphan_case = _cassette(tmp_path, "good", "gone", 0, "bbbb000000000000")
    orphan_suite = _cassette(tmp_path, "dead", "c1", 0, "cccc000000000000")

    result = runner.invoke(app, ["prune"])
    assert result.exit_code == 0, result.output
    assert "gone" in result.output and "orphaned case" in result.output
    assert "dead" in result.output and "orphaned suite" in result.output
    assert "good/c1" not in result.output  # the valid cassette is not a candidate
    # Nothing deleted on a dry run.
    assert keep.exists() and orphan_case.exists() and orphan_suite.exists()


def test_yes_deletes_only_the_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, {"good": ["c1"]})
    keep = _cassette(tmp_path, "good", "c1", 0, "aaaa000000000000")
    orphan = _cassette(tmp_path, "dead", "c1", 0, "cccc000000000000")

    result = runner.invoke(app, ["prune", "--yes"])
    assert result.exit_code == 0, result.output
    assert keep.exists()
    assert not orphan.exists()


def test_stale_schema_version_is_identified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, {"good": ["c1"]})
    _cassette(tmp_path, "good", "c1", 0, "aaaa000000000000", schema=1)
    stale = _cassette(tmp_path, "good", "c1", 1, "dddd000000000000", schema=999)

    result = runner.invoke(app, ["prune"])
    assert result.exit_code == 0
    assert "stale schema_version" in result.output
    assert stale.name in result.output


def test_a_failed_to_parse_suite_is_never_pruned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, {"good": ["c1"]}, broken=True)
    # A cassette dir we cannot match to any *parsed* suite — it might belong to the
    # broken one, so it must be protected.
    protected = _cassette(tmp_path, "mystery", "c", 0, "eeee000000000000")

    result = runner.invoke(app, ["prune", "--yes"])
    assert result.exit_code == 0, result.output
    assert "mystery" not in result.output
    assert protected.exists()  # not deleted


def test_empty_dirs_are_cleaned_after_pruning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, {"good": ["c1"]})
    _cassette(tmp_path, "good", "c1", 0, "aaaa000000000000")
    _cassette(tmp_path, "dead", "c1", 0, "cccc000000000000")

    runner.invoke(app, ["prune", "--yes"])
    assert not (tmp_path / ".dryfire" / "cassettes" / "dead").exists()  # emptied dir removed
    assert (tmp_path / ".dryfire" / "cassettes" / "good" / "c1").exists()  # kept


def test_nothing_to_prune(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, {"good": ["c1"]})
    _cassette(tmp_path, "good", "c1", 0, "aaaa000000000000")

    result = runner.invoke(app, ["prune"])
    assert result.exit_code == 0
    assert "nothing to prune" in result.output.lower()

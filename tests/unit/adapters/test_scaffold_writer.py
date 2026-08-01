"""AC-016 — the scaffold writer: copies the bundled template into a target dir.

Copies the packaged `dryfire/scaffold/template/**` tree, refuses to clobber
existing files without `--force`, and never leaves a half-written scaffold when
it refuses.
"""

from pathlib import Path

import pytest

from dryfire.adapters.driven.scaffold.writer import ScaffoldConflict, scaffold

_EXPECTED = {
    Path("dryfire.yaml"),
    Path("evals/hello.eval.yaml"),
    Path("evals/refund_agent.eval.yaml"),
    Path("evals/schemas/escalate_to_human.json"),
    Path("evals/README.md"),
}


def test_writes_the_whole_template_tree(tmp_path: Path) -> None:
    written = scaffold(tmp_path)
    assert set(written) == _EXPECTED
    for rel in _EXPECTED:
        assert (tmp_path / rel).is_file()
    # A nested file proves directories were created.
    assert (tmp_path / "evals" / "schemas" / "escalate_to_human.json").read_text(
        encoding="utf-8"
    ).strip().startswith("{")


def test_returned_paths_are_sorted_and_relative(tmp_path: Path) -> None:
    written = scaffold(tmp_path)
    assert written == sorted(written)
    assert all(not p.is_absolute() for p in written)


def test_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    (tmp_path / "dryfire.yaml").write_text("KEEP ME", encoding="utf-8")

    with pytest.raises(ScaffoldConflict) as exc:
        scaffold(tmp_path)

    assert Path("dryfire.yaml") in exc.value.conflicts
    # The existing file is untouched and nothing else was written.
    assert (tmp_path / "dryfire.yaml").read_text(encoding="utf-8") == "KEEP ME"
    assert not (tmp_path / "evals").exists()


def test_force_overwrites_conflicts(tmp_path: Path) -> None:
    (tmp_path / "dryfire.yaml").write_text("STALE", encoding="utf-8")

    written = scaffold(tmp_path, force=True)

    assert set(written) == _EXPECTED
    assert (tmp_path / "dryfire.yaml").read_text(encoding="utf-8") != "STALE"


def test_scaffolded_project_is_valid(tmp_path: Path) -> None:
    # The strongest writer test: what it lays down actually parses. Full run/skip
    # behaviour is covered by the init integration test.
    from dryfire import composition

    scaffold(tmp_path)
    import io

    out, err = io.StringIO(), io.StringIO()
    code = composition.validate(
        [
            str(tmp_path / "evals" / "hello.eval.yaml"),
            str(tmp_path / "evals" / "refund_agent.eval.yaml"),
        ],
        out=out,
        err=err,
    )
    assert code == 0, err.getvalue()

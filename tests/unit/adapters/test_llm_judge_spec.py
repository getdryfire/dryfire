"""DF-303 — spec-level validation of the `llm_judge` assertion.

A rubric is required and non-empty; a bad one is a positioned spec error at *load*
time (exit 2), before any run and with zero network — `load_suite` never touches a
provider. This is the guard that stops a misconfigured judge from spending money to
discover it was misconfigured.
"""

from __future__ import annotations

from pathlib import Path

from dryfire.adapters.driven.spec.loader import load_suite


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "s.eval.yaml"
    p.write_text(text, encoding="utf-8")
    return p


_HEAD = "name: s\ncases:\n  - name: c\n    input: hi\n    expect:\n"


def test_valid_llm_judge_loads_clean(tmp_path: Path) -> None:
    src = _HEAD + '      - llm_judge: {rubric: "Was the agent helpful?", threshold: 0.8}\n'
    suite, errors = load_suite(_write(tmp_path, src))
    assert errors == []
    assert suite is not None


def test_rubric_only_is_valid_model_and_threshold_default(tmp_path: Path) -> None:
    src = _HEAD + '      - llm_judge: {rubric: "Was the agent helpful?"}\n'
    suite, errors = load_suite(_write(tmp_path, src))
    assert errors == []
    assert suite is not None


def test_missing_rubric_is_a_positioned_spec_error(tmp_path: Path) -> None:
    src = _HEAD + "      - llm_judge: {threshold: 0.8}\n"
    suite, errors = load_suite(_write(tmp_path, src))
    assert suite is None
    assert len(errors) == 1
    assert "llm_judge" in errors[0].message
    assert "rubric" in errors[0].message
    assert errors[0].position is not None  # points at the entry


def test_empty_rubric_is_a_positioned_spec_error(tmp_path: Path) -> None:
    src = _HEAD + '      - llm_judge: {rubric: "   "}\n'
    suite, errors = load_suite(_write(tmp_path, src))
    assert suite is None
    assert len(errors) == 1
    assert "rubric" in errors[0].message
    assert "empty" in errors[0].message.lower()
    assert errors[0].position is not None


def test_unknown_arg_is_rejected(tmp_path: Path) -> None:
    src = _HEAD + '      - llm_judge: {rubric: "ok", weight: 3}\n'
    suite, errors = load_suite(_write(tmp_path, src))
    assert suite is None
    assert len(errors) == 1

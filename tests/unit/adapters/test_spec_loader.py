"""AC-004 — the three-stage spec load pipeline."""

import socket
from pathlib import Path

import pytest

from dryfire.adapters.driven.spec.errors import render
from dryfire.adapters.driven.spec.loader import load_suite, load_suites

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "broken"

VALID = """\
name: refund_agent
system: be nice
tools:
  - name: lookup_order
    input_schema: {type: object}
cases:
  - name: c1
    input: hi
    expect:
      - calls_tool: lookup_order
"""


def _write(dir_: Path, name: str, text: str) -> Path:
    p = dir_ / name
    p.write_text(text, encoding="utf-8")
    return p


class TestValidLoad:
    def test_valid_suite_loads_with_no_errors(self, tmp_path: Path) -> None:
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", VALID))
        assert errors == []
        assert suite is not None
        assert suite.name == "refund_agent"
        assert suite.tools[0].name == "lookup_order"


class TestEnvInterpolation:
    def test_env_var_is_substituted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUITE_NAME", "resolved_name")
        src = "name: ${SUITE_NAME}\ncases:\n  - name: c\n    input: hi\n    expect: []\n"
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", src))
        assert errors == []
        assert suite is not None
        assert suite.name == "resolved_name"

    def test_missing_env_var_is_a_positioned_error_not_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NOPE_VAR", raising=False)
        src = "name: ${NOPE_VAR}\ncases:\n  - name: c\n    input: hi\n    expect: []\n"
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", src))
        assert suite is None
        assert len(errors) == 1
        assert "NOPE_VAR" in errors[0].message
        assert errors[0].position is not None
        assert errors[0].position.line == 1


class TestRefResolution:
    def test_valid_ref_is_inlined(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "escalate.json",
            '{"name": "escalate_to_human", "input_schema": {"type": "object"}}',
        )
        src = (
            "name: s\ntools:\n  - $ref: ./escalate.json\n"
            "cases:\n  - name: c\n    input: hi\n    expect: []\n"
        )
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", src))
        assert errors == []
        assert suite is not None
        assert suite.tools[0].name == "escalate_to_human"

    def test_missing_ref_produces_exactly_one_error(self, tmp_path: Path) -> None:
        src = (
            "name: s\ntools:\n  - $ref: ./missing.json\n"
            "cases:\n  - name: c\n    input: hi\n    expect: []\n"
        )
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", src))
        assert suite is None
        # Cascade suppression: the placeholder tool must NOT also raise
        # "missing name/input_schema" errors.
        assert len(errors) == 1
        assert "missing.json" in errors[0].message


class TestAssertionKindPrePass:
    def test_unknown_kind_suggests_by_edit_distance(self, tmp_path: Path) -> None:
        src = (
            "name: s\ncases:\n  - name: c\n    input: hi\n"
            "    expect:\n      - calls_tolo: lookup_order\n"
        )
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", src))
        assert suite is None
        assert len(errors) == 1
        assert "calls_tolo" in errors[0].message
        assert errors[0].hint is not None
        assert "calls_tool" in errors[0].hint


class TestPydanticStage:
    def test_missing_required_field_is_inexact_position(self, tmp_path: Path) -> None:
        src = "name: s\ncases:\n  - name: c\n    expect: []\n"  # case missing `input`
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", src))
        assert suite is None
        assert len(errors) == 1
        assert "input" in errors[0].message
        assert errors[0].position is not None
        assert errors[0].position.exact is False

    def test_all_errors_collected_and_sorted_by_position(self, tmp_path: Path) -> None:
        # Unknown top-level key on line 2; bad type on line 3.
        src = "name: s\nmodle: x\nmax_turns: six\ncases: []\n"
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", src))
        assert suite is None
        assert len(errors) == 2
        lines = [e.position.line for e in errors if e.position]
        assert lines == sorted(lines)
        assert lines[0] == 2


class TestRefRelativeToSuiteNotCwd:
    def test_ref_resolves_from_a_different_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        suite_dir = tmp_path / "evals"
        suite_dir.mkdir()
        _write(
            suite_dir,
            "escalate.json",
            '{"name": "escalate_to_human", "input_schema": {"type": "object"}}',
        )
        src = (
            "name: s\ntools:\n  - $ref: ./escalate.json\n"
            "cases:\n  - name: c\n    input: hi\n    expect: []\n"
        )
        suite_path = _write(suite_dir, "s.eval.yaml", src)
        elsewhere = tmp_path / "cwd"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        suite, errors = load_suite(suite_path)
        assert errors == []
        assert suite is not None


class TestOffline:
    def test_valid_load_makes_zero_network_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _no_network(*_a: object, **_k: object) -> None:
            raise AssertionError("spec loading must not touch the network")

        monkeypatch.setattr(socket.socket, "connect", _no_network)
        suite, errors = load_suite(_write(tmp_path, "s.eval.yaml", VALID))
        assert errors == []
        assert suite is not None


class TestLoadSuites:
    def test_aggregates_valid_and_broken_files(self, tmp_path: Path) -> None:
        good = _write(tmp_path, "good.eval.yaml", VALID)
        bad = _write(tmp_path, "bad.eval.yaml", "name: s\ncases: []\nmodle: x\n")
        suites, errors = load_suites([good, bad])
        assert len(suites) == 1
        assert suites[0].name == "refund_agent"
        assert len(errors) == 1


class TestGoldenAllFive:
    """The five error classes in one file (criterion 1) and the exact rendered
    output (criterion 9)."""

    FIXTURE = _FIXTURES / "all_five.eval.yaml"
    EXPECTED = _FIXTURES / "all_five.expected.txt"

    def test_each_of_the_five_classes_is_reported_with_a_position(self) -> None:
        suite, errors = load_suite(self.FIXTURE)
        assert suite is None
        assert len(errors) == 5
        msgs = [e.message for e in errors]
        assert any("unknown field 'modle'" in m for m in msgs)  # unknown top-level key
        assert any("expected an integer" in m for m in msgs)  # wrong field type
        assert any("$ref target not found" in m for m in msgs)  # missing $ref file
        assert any("required field 'input' is missing" in m for m in msgs)  # missing field
        assert any("unknown assertion kind" in m for m in msgs)  # unknown assertion
        assert all(e.position is not None for e in errors)

    def test_rendered_output_matches_golden(self) -> None:
        _, errors = load_suite(self.FIXTURE)
        out = render(errors, self.FIXTURE.read_text().splitlines()).replace(
            str(self.FIXTURE), "all_five.eval.yaml"
        )
        assert out == self.EXPECTED.read_text(encoding="utf-8")

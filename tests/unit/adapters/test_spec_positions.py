"""AC-004 — source-position mapping (SPIKE-003, lifted). Schema-agnostic."""

from pathlib import Path

from dryfire.adapters.driven.spec.positions import (
    Position,
    load_positioned,
    locate,
)


class TestPosition:
    def test_from_lc_none_is_none(self) -> None:
        assert Position.from_lc(None) is None

    def test_from_lc_converts_zero_based_to_one_based(self) -> None:
        p = Position.from_lc((0, 0))
        assert p == Position(line=1, col=1, exact=True)

    def test_from_lc_carries_exact_flag(self) -> None:
        p = Position.from_lc((2, 4), exact=False)
        assert p == Position(line=3, col=5, exact=False)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "s.eval.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class TestLocate:
    SRC = "name: refund_agent\ncases:\n  - name: c1\n    input: hi\n"

    def test_top_level_key_resolves_exactly(self, tmp_path: Path) -> None:
        root = load_positioned(_write(tmp_path, self.SRC))
        pos = locate(root, ("name",))
        assert pos == Position(line=1, col=1, exact=True)

    def test_nested_key_resolves_exactly(self, tmp_path: Path) -> None:
        root = load_positioned(_write(tmp_path, self.SRC))
        pos = locate(root, ("cases", 0, "name"))
        assert pos is not None
        assert pos.line == 3
        assert pos.col == 5
        assert pos.exact is True

    def test_missing_key_falls_back_to_ancestor_inexact(self, tmp_path: Path) -> None:
        root = load_positioned(_write(tmp_path, self.SRC))
        pos = locate(root, ("cases", 0, "input", "deeper"))
        assert pos is not None
        assert pos.exact is False

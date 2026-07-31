"""AC-004 — SpecError and the rendered caret output (SPIKE-003 format)."""

from pathlib import Path

from agentcheck.adapters.driven.spec.errors import SpecError, render
from agentcheck.adapters.driven.spec.positions import Position


class TestLocStr:
    def test_root_when_empty(self) -> None:
        assert SpecError(Path("s"), (), "m", None).loc_str == "<root>"

    def test_dotted_and_indexed(self) -> None:
        e = SpecError(Path("s"), ("cases", 0, "name"), "m", None)
        assert e.loc_str == "cases[0].name"


class TestRender:
    def _err(self, exact: bool = True, hint: str | None = None) -> SpecError:
        return SpecError(
            path=Path("s.eval.yaml"),
            loc=("max_turns",),
            message="expected an integer",
            position=Position(line=2, col=12, exact=exact),
            hint=hint,
        )

    SOURCE = ["name: x", "max_turns: six"]

    def test_header_and_location_line(self) -> None:
        lines = render([self._err()], self.SOURCE).splitlines()
        assert lines[0] == "error: expected an integer"
        assert lines[1] == "  --> s.eval.yaml:2:12   (max_turns)"

    def test_source_line_and_caret_alignment(self) -> None:
        lines = render([self._err()], self.SOURCE).splitlines()
        assert lines[3] == "   2 | max_turns: six"
        # Caret sits under the offending token ("six" starts at col 12).
        assert lines[4].index("^") == lines[3].index("six")

    def test_inexact_position_gets_nearest_enclosing_marker(self) -> None:
        lines = render([self._err(exact=False)], self.SOURCE).splitlines()
        assert "(nearest enclosing node)" in lines[4]

    def test_hint_is_rendered_as_help(self) -> None:
        lines = render([self._err(hint="did you mean 'calls_tool'?")], self.SOURCE).splitlines()
        assert "   = help: did you mean 'calls_tool'?" in lines

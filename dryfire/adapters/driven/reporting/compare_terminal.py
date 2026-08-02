"""Compare matrix reporter (DF-308) — the screenshot artifact (SPEC §9).

Models are columns, cases are rows, and the load-bearing design goal is that the
**disagreement is obvious**: a case that passes on one model and fails on another is the
whole reason someone ran `compare`, and a wall of uniform checkmarks teaches nothing. A
disagreement row is marked with a `~` (a real character, not just colour, so it survives
a non-TTY CI log and a grep) and its cells still read `✓`/`✗`.

Like the run reporter, this is a **pure** function emitting zero ANSI unless `color=True`.
Cost is shown prominently per model (the usual question is "is the cheap model good
enough"); an unknown cost renders `—`, never a fabricated `$0.0000`.

**Wide-matrix strategy (documented choice):** columns beyond `_MAX_COLS` are dropped with
a note pointing at `--json-out` for the full matrix, and long model names are truncated to
keep columns aligned. Transposition was rejected — cases-as-columns reads worse when a
suite has many cases, which is the common shape.
"""

from __future__ import annotations

from dryfire.application.scheduler import CaseResult, RunResult
from dryfire.application.usecases.compare import CompareColumn, CompareResult

_PASS = "✓"
_FAIL = "✗"
_NOCELL = "·"  # a failed column has no per-case result
_DISAGREE = "~"
_MAX_COLS = 8  # beyond this, truncate columns with a note (wide-matrix strategy)
_MAX_NAME = 28
_MAX_LABEL = 12
_GAP = "  "

_YELLOW = "\x1b[33m"
_RESET = "\x1b[0m"


def _cases(run: RunResult) -> list[CaseResult]:
    return [c for suite in run.suites for c in suite.cases]


def _row_labels(columns: list[CompareColumn]) -> list[str]:
    """Case names in spec order, taken from the first column that actually ran. All
    columns run the same suite, so their case lists align."""
    for col in columns:
        if col.run is not None:
            return [c.case_name for c in _cases(col.run)]
    return []


def _verdict(col: CompareColumn, case_name: str) -> bool | None:
    """Whether `case_name` passed in this column — None if the column failed or the case
    is absent (both render as `·`)."""
    if col.run is None:
        return None
    for c in _cases(col.run):
        if c.case_name == case_name:
            return c.passed
    return None


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _cost(value: float | None) -> str:
    return "—" if value is None else f"${value:.4f}"


def render_compare(result: CompareResult, *, color: bool = False) -> str:
    columns = result.columns
    shown = columns[:_MAX_COLS]
    dropped = len(columns) - len(shown)
    labels = [_truncate(c.label, _MAX_LABEL) for c in shown]
    rows = _row_labels(columns)

    name_w = max([len("case"), *(len(r) for r in rows)] + [len("mean latency")])
    name_w = min(name_w, _MAX_NAME)
    col_w = [max(len(lbl), 9) for lbl in labels]

    def cells(values: list[str]) -> str:
        return _GAP.join(v.ljust(w) for v, w in zip(values, col_w, strict=True))

    lines: list[str] = [
        f"compare by {result.axis} — {len(columns)} {result.axis}s × {len(rows)} cases",
        "",
        f"  {'case'.ljust(name_w)}{_GAP}{cells(labels)}",
        f"  {'─' * name_w}{_GAP}{cells(['─' * w for w in col_w])}",
    ]

    for case_name in rows:
        verdicts = [_verdict(col, case_name) for col in shown]
        present = [v for v in verdicts if v is not None]
        disagree = len(set(present)) > 1
        marker = _DISAGREE if disagree else " "
        glyphs = [_PASS if v else _FAIL if v is False else _NOCELL for v in verdicts]
        if color and disagree:
            glyphs = [f"{_YELLOW}{g}{_RESET}" if v is False else g
                      for g, v in zip(glyphs, verdicts, strict=True)]
        # Pad glyphs to column width using the UNcoloured length (ANSI has zero width).
        padded = [g + " " * (w - 1) for g, w in zip(glyphs, col_w, strict=True)]
        name = _truncate(case_name, name_w).ljust(name_w)
        row = f"{marker} {name}{_GAP}{_GAP.join(padded)}"
        lines.append(f"{_YELLOW}{row}{_RESET}" if color and disagree else row)

    lines.append(f"  {'─' * name_w}{_GAP}{cells(['─' * w for w in col_w])}")
    lines.append(f"  {'pass rate'.ljust(name_w)}{_GAP}"
                 f"{cells([_rate(c) for c in shown])}")
    lines.append(f"  {'cost'.ljust(name_w)}{_GAP}{cells([_col_cost(c) for c in shown])}")
    lines.append(f"  {'mean latency'.ljust(name_w)}{_GAP}"
                 f"{cells([_latency(c) for c in shown])}")

    if dropped > 0:
        lines += ["", f"… {dropped} more {result.axis}(s) not shown — use --json-out "
                      "for the full matrix"]
    return "\n".join(lines) + "\n"


def _rate(col: CompareColumn) -> str:
    return "FAILED" if col.metrics is None else f"{col.metrics.pass_rate:.0%}"


def _col_cost(col: CompareColumn) -> str:
    return "—" if col.metrics is None else _cost(col.metrics.total_cost_usd)


def _latency(col: CompareColumn) -> str:
    return "—" if col.metrics is None else f"{col.metrics.mean_latency_ms:.0f}ms"

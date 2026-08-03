#!/usr/bin/env python
"""Benchmark: a structural-only suite must run at v0.2 speed and cost (EPIC-003
success criterion 2). Offline, deterministic — a `provider: fake` suite of N cases with
only structural assertions.

The guarantee is architectural first: a suite with no `llm_judge` and no `repeat`
takes `judge=None` (composition wires the judge callback ONLY when a case uses
`llm_judge`) and `repeat: 1` (the v0.2 scheduler path, byte-identical). No judge stage
runs, no judge cost is accounted, no repetition units are expanded. This script confirms
it empirically: it runs the suite, asserts zero judge activity and zero cost, and prints
the wall-clock so a regression shows up as a number.

    uv run python scripts/benchmark_structural.py [N]
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from dryfire import composition

_CASE = """\
  - name: case_{i}
    input: hi
    script:
      - tool_call: {{name: lookup, arguments: {{q: "{i}"}}}}
      - text: done
    expect:
      - calls_tool: lookup
      - not_calls_tool: delete_everything
      - call_order: [lookup]
      - max_turns: 5
      - final_contains: done
"""


def _suite(n: int) -> str:
    header = (
        "name: bench\nprovider: fake\n"
        "tools:\n  - name: lookup\n    input_schema: {type: object}\n"
        "mocks:\n  lookup:\n    - return: {ok: true}\n"
        "cases:\n"
    )
    return header + "".join(_CASE.format(i=i) for i in range(n))


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    with TemporaryDirectory() as d:
        suite = Path(d) / "bench.eval.yaml"
        suite.write_text(_suite(n), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()

        start = time.perf_counter()
        code = composition.run([str(suite)], reporter="json", out=out, err=err)
        elapsed = time.perf_counter() - start

    import json as _json

    doc = _json.loads(out.getvalue())
    cases = [c for s in doc["suites"] for c in s["cases"]]
    passed = sum(1 for c in cases if c["passed"])
    # Structural-only guarantees: no judge channel touched, no cost accrued offline.
    judged = [c for c in cases if c["trace"] and c["trace"].get("judge_verdicts")]
    costs = [c["trace"]["total_cost_usd"] for c in cases if c["trace"]]

    print(f"cases          {len(cases)}")
    print(f"passed         {passed}")
    print(f"exit code      {code}")
    print(f"wall clock     {elapsed * 1000:.0f} ms  ({elapsed / n * 1000:.2f} ms/case)")
    print(f"judge activity {len(judged)} cases  (must be 0 — structural-only fast path)")
    print(f"total cost     {sum(c for c in costs if c) if any(costs) else 0.0}  (offline → 0)")

    assert code == 0, "structural-only suite should pass"
    assert not judged, "structural-only suite must not touch the judge channel"
    assert not any(costs), "offline structural run must cost nothing"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

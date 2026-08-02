"""DF-303 — an end-to-end judged run, fully offline (EPIC-003).

The whole judge pipeline exercised through `composition.run`: agent loop → pricing →
judge enrichment → assertion → contractual exit code. A `provider: fake` case scripts
both the agent turn AND the judge's JSON response through one gateway (the judge reuses
the case's gateway, which is why judge calls are cassette-backed for free), so no
network and no key are needed.
"""

from __future__ import annotations

import io

from dryfire import composition

_JUDGED = """\
name: judged
provider: fake
cases:
  - name: refund
    model: fake-judge-1
    script:
      - text: "I'm so sorry for the trouble — I've issued your refund."
      - text: '{{"score": {score}, "reasoning": "{reasoning}"}}'
    input: I want a refund
    expect:
      - llm_judge: {{rubric: "Did the agent apologise and resolve the issue?", threshold: 0.7}}
"""


def _run(source: str) -> tuple[int, str]:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        suite = Path(d) / "s.eval.yaml"
        suite.write_text(source, encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        code = composition.run([str(suite)], out=out, err=err)
    return code, out.getvalue() + err.getvalue()


def test_judged_run_passes_when_the_judge_scores_above_threshold() -> None:
    code, output = _run(_JUDGED.format(score=0.95, reasoning="apologised and refunded"))
    assert code == composition.EXIT_OK, output


def test_judged_run_fails_when_the_judge_scores_below_threshold() -> None:
    code, output = _run(_JUDGED.format(score=0.4, reasoning="never apologised"))
    assert code == composition.EXIT_ASSERTION, output

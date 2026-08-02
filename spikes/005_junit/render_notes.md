# SPIKE-005 — rendered behaviour per consumer

**Read the evidence label on every row.** This spike settles offline everything that lives in
the XML (well-formedness, escaping, the `→` arrow, attribute-vs-text newlines — all proven by
`verify.py`). What lives in a consumer's **UI** (does dorny truncate the body, does GitLab's
widget show the second `<failure>`) cannot be produced from this environment — it needs the
report fed to a live pipeline. Those rows are marked **DOCUMENTED — LIVE CAPTURE PENDING** and
the kit to capture them is at the bottom. Nothing here is a fabricated screenshot.

Evidence labels:

- **[OFFLINE]** — proven by `verify.py` in this repo; parser-independent (XML 1.0 mandates it).
- **[PYTEST]** — corroborated by the shape `pytest --junitxml` itself emits, which every
  consumer in scope is calibrated against (see "Why pytest's shape is the tie-breaker" below).
- **[DOC]** — from the consumer's published docs/parser source; **not yet captured live**.

The scenario in every candidate: suite `refunds`, three cases — one **failing** on two
assertions (`not_calls_tool: issue_refund` — the safety regression that is the whole point —
and `calls_tool: escalate_to_human`), one passing, one **errored** (`provider_error`).

---

## The moment that matters: a failing `not_calls_tool` in a PR check

| Consumer | A — case=testcase, 1 failure, concatenated | B — assertion=testcase | C — case=testcase, N failures |
|---|---|---|---|
| **GitHub / dorny/test-reporter** | Check lists **1 failed test** = the case name; annotation title = the one-line `message` summary; body shows **both** assertion blocks with trajectories. Most legible. **[PYTEST][DOC]** | Lists **5 tests, 2 failed**; the case is split into `not_calls_tool: issue_refund` and `calls_tool: escalate_to_human`, case name only in `classname`. You lose "which scenario" at a glance. **[DOC]** | Lists 1 failed test; dorny's parser surfaces the **first** `<failure>` only → `escalate_to_human` **silently dropped**. Looks complete, isn't. **[OFFLINE risk][DOC]** |
| **GitLab CI (Tests tab + MR widget)** | MR widget names the failed case; detail modal shows the concatenated body (newlines preserved — text body). **[OFFLINE][DOC]** | Widget shows two failed "tests"; grouping relies on `classname`. Scenario fragmented. **[DOC]** | Detail modal shows failure text; second `<failure>` handling is parser-version-dependent → drop risk. **[DOC]** |
| **Jenkins JUnit plugin** | One `<failure>` per testcase is exactly the Ant/Surefire schema → renders cleanly in `<pre>`, newlines kept. **[PYTEST][DOC]** | Each assertion a testcase under a per-case class; counts inflated; errored case needs a synthetic testcase. **[DOC]** | Schema permits **at most one** `<failure>`; Jenkins ignores extras or warns → `escalate_to_human` dropped. Strongest evidence against C. **[OFFLINE risk][DOC]** |

**Verdict driver:** A is the only mapping where *nothing is silently lost* and the *case stays
the unit*. B trades the scenario for per-assertion addressability and inflates counts; C reads
as clean but drops every assertion after the first on the strictest (and most common) parsers.

---

## Confirmed cross-cutting behaviours (the four the ticket names)

### Trajectory `→` arrows and newlines surviving XML escaping — **[OFFLINE]**
- `→` (U+2192) and `✗` (U+2717) are legal XML chars in UTF-8; written literally, they round-trip.
  No `&#8594;` needed and no consumer in scope requires ASCII (Q5).
- Newlines **survive in `<failure>` text** and **collapse to a space in the `message` attribute**
  (XML 1.0 §3.3.3 attribute-value normalization). → the multi-line block belongs in the body; the
  `message` attribute is a one-line summary. `verify.py` §4 proves both directions.
- `&`, `<`, `>` inside tool-arg JSON escape to `&amp;`/`&lt;`/`&gt;` and round-trip (`verify.py` §3).

### A case that errored rather than failed — **[PYTEST][DOC]**
`<error>` (not `<failure>`) for `provider_error` and `unmocked_tool` — the run could not be
evaluated, distinct from "the agent did the wrong thing." Consumers colour `error` differently
(often yellow vs red) and count it separately, which is exactly the signal you want: an errored
case is not a caught regression. See FINDINGS Q3.

### A zero-case run — **[OFFLINE][DOC]**
`zero_cases.xml` (empty `<testsuite tests="0">`) parses everywhere. The trap: `failures="0"`
reads as **green**. DF-209 must emit a visible "0 cases matched" note so an empty glob is not a
silent pass. `verify.py` §6.

### Attributes needed for grouping — **[DOC]** (Q4)
- `name` (required, everywhere), `classname` (Jenkins class tree; GitLab/dorny grouping — emit
  `classname` = suite name), `time` (expected; absence renders as 0.000).
- `file` is **not** needed — a case has no source line; optionally point it at the `.eval.yaml`
  so dorny can drop a file annotation, but that is a nicety, not a requirement.

---

## Why pytest's shape is the tie-breaker (offline, strong)

Every consumer here is tuned against the two most common JUnit *producers*: Ant/Surefire and
`pytest --junitxml`. Inspect what pytest emits for a failing test: **one `<failure>` per
`<testcase>`, `message` = a short one-line repr, the full detail in the element text**. That is
candidate **A** exactly. Candidates B and C both deviate from the shape consumers are most
battle-tested against — B in structure, C in cardinality. Choosing A means choosing the shape
the ecosystem already renders well, which is why the verdict is defensible before the live
captures land, not after.

(To see it yourself: `pytest --junitxml=/tmp/j.xml` on any failing test, then read `/tmp/j.xml`.)

---

## Live-capture kit (the part that needs a real pipeline)

The rows marked **[DOC]** assert how each UI *renders* — truncation thresholds, whether the
second `<failure>` shows, exact colours. Confirm them by feeding these candidates to real
pipelines in a throwaway repo (same requirement DF-210 has). ~30 minutes, owner's hands.

**GitHub / dorny** — commit the candidates and a workflow:
```yaml
# .github/workflows/junit-spike.yml
on: [push]
jobs:
  render:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/test-reporter@v1
        with:
          name: junit-A
          path: spikes/005_junit/candidates/A.xml   # repeat for B.xml, C.xml
          reporter: java-junit
```
Capture: the Checks tab for A/B/C. Confirm — does C show one failure or two? Does A's body
truncate, and at what length? Does the `message` summary survive truncation?

**GitLab** — `.gitlab-ci.yml`:
```yaml
render:
  script: "true"
  artifacts:
    reports:
      junit: spikes/005_junit/candidates/A.xml   # one job per candidate
```
Capture: the pipeline **Tests** tab and the MR widget. Confirm the second `<failure>` and any
system-output truncation.

**Jenkins** — a freestyle/pipeline job with `junit 'spikes/005_junit/candidates/*.xml'`. Capture
the test result tree; confirm C's extra `<failure>` is dropped/warned (the offline prediction).

Record each as a screenshot or transcript in this file under a new "## Captured" heading, keeping
the evidence label honest (**[LIVE]** once done).

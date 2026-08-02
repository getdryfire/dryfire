# SPIKE-005 — JUnit XML mapping across CI consumers

**Status:** complete (offline empiricism) · **Time-box:** half day · **Consumed by:** DF-209
**Deliverables:** `candidates/{A,B,C,zero_cases}.xml`, `verify.py` (offline-decidable facts,
all green via `make spike-junit`), `render_notes.md` (per-consumer matrix + live-capture kit),
this file.

**Scope honesty up front.** The ticket asks for a verdict grounded in *rendered* output from
three live consumers. Everything that lives in the **XML** — well-formedness, escaping, the `→`
arrow, attribute-vs-text newlines, the multiple-`<failure>` cardinality risk — is settled here
**empirically and authoritatively** (`verify.py`, parser-independent per XML 1.0). Everything
that lives in a consumer's **UI** — truncation thresholds, whether dorny shows the second
`<failure>`, exact colours — cannot be produced from this environment; it is predicted from
(a) the shape `pytest --junitxml` emits, which every consumer is calibrated against, and (b)
each consumer's published parser behaviour, and the **30-minute throwaway-repo capture kit** to
confirm it live is in `render_notes.md`. No screenshot in this spike is fabricated. The verdict
is safe to build on now; the captures are confirmation, not discovery.

---

## Verdict — the mapping DF-209 implements

**Candidate A: case = `<testcase>`, one `<failure>` per failing case, all failed assertions
concatenated into the failure text body.** This is the shape `pytest` itself emits, refined.

Concretely, the reference document is **`candidates/A.xml`** — DF-209 matches its structure:

1. **`<testsuites>` → run, `<testsuite name={suite}>` → suite, `<testcase name={case}
   classname={suite}>` → case.** The case is the unit of pass/fail — it is one agent scenario,
   and that is what a human reads in a PR check.
2. **A failing case gets exactly one `<failure>`.** Its **text body** holds the multi-line
   block — every failed assertion's `✗ description / expected / actual (trajectory) / message`,
   concatenated. Its **`message` attribute** is a purpose-built **one-line summary**
   (`"2 assertions failed: not_calls_tool: issue_refund; calls_tool: escalate_to_human"`).
   - *Why one line:* XML attribute-value normalization (§3.3.3) collapses newlines in an
     attribute to spaces on parse — proven in `verify.py` §4. pytest ignores this and dumps a
     multi-line message that arrives space-mushed; A does better by writing a clean summary and
     keeping all fidelity in the text body.
3. **An errored case gets `<error>`, not `<failure>`** (Q3).
4. **A passing case is a bare `<testcase/>`.** A zero-case run is a valid empty `<testsuite
   tests="0">` **plus a visible "0 cases matched" note** from DF-209 so it cannot read as a
   silent green (Q4/§6).
5. **Emit `name`, `classname`, `time`.** Skip `file` (a case has no source line); optionally
   point it at the `.eval.yaml` later for dorny file-annotations.

---

## Questions FINDINGS.md must answer

### Q1 — Which mapping, and what did the other two lose?

**A.** What the others lose, concretely:

- **B (assertion = testcase, case = testsuite)** loses the **case as the unit**: one scenario
  fragments into N "tests", the failing case reads as "1 of 2 tests failed", and the case name
  survives only in `classname`. It **inflates test counts** (3 cases → 5+ tests) so a pass-rate
  badge stops meaning "scenarios passing". And an **errored case has no assertions**, so it must
  be forced into a synthetic testcase — the tell that the mapping doesn't fit the domain.
- **C (case = testcase, one `<failure>` per assertion)** loses **every assertion after the
  first** on the strictest and most common parsers. The Ant/Surefire schema permits **at most
  one** `<failure>` per `<testcase>`; Jenkins and pytest emit one; consumers calibrated on that
  drop the extras. `verify.py` §5 shows C emitting two `<failure>` children where a
  first-failure-only consumer surfaces `not_calls_tool: issue_refund` and **silently drops**
  `calls_tool: escalate_to_human`. Silent partial loss that *looks* complete is worse than no
  reporter — the exact failure the ticket warns about.

A keeps the case as the unit and loses nothing: both assertions live in one body no parser can
partially drop.

### Q2 — Does any consumer truncate the failure body? At what length? Does the trajectory survive?

**Truncation is real and consumer-specific; exact thresholds are the [DOC] rows pending live
capture.** Documented limits to confirm: GitHub check-run output is capped at **65,535 chars
total** (dorny writes all annotations into that budget), and dorny truncates long annotation
bodies; GitLab truncates large system-output in the test-detail modal; Jenkins renders the full
body in `<pre>`. **The trajectory line itself is short and always survives**; the risk is only a
case with very many assertions overflowing the body. **A mitigates this structurally:** the
one-line `message` summary carries the verdict even when the body is truncated, so the PR check
never degrades to "something failed, detail lost". Confirm exact cut points with the kit.

### Q3 — `<error>` vs `<failure>` for `provider_error` and `unmocked_tool`?

**`<error>` for both.** `<failure>` means the agent's behaviour was evaluated and was wrong (an
assertion did not hold). `<error>` means the case **could not be evaluated**: `provider_error`
(the model call failed) and `unmocked_tool` (the trajectory hit a tool with no rule and was
cut short) are infrastructure/spec problems, not caught regressions. Consumers count and colour
`error` separately from `failure`, which is exactly the signal wanted — an errored case must not
masquerade as a caught safety regression. (`max_turns_exceeded`, `max_tokens`, `refusal` still
run assertions against the truncated trace; they surface as `<failure>` only if an assertion
fails, else pass.)

### Q4 — Are `time`, `classname`, or `file` attributes needed for grouping?

- **`name`** — required by every consumer.
- **`classname`** — **needed.** Jenkins builds its class/package tree from it; GitLab and dorny
  group by it. Emit `classname` = suite name so cases group under their suite.
- **`time`** — expected; its absence renders as 0.000 but some consumers warn. Emit it.
- **`file`** — **not needed.** A case is not a source location. Optional future nicety: set it to
  the `.eval.yaml` path so dorny can attach a file-level annotation.

### Q5 — Does any consumer choke on `→`, or require ASCII?

**No.** `→` (U+2192) and `✗` (U+2717) are legal XML characters; in a UTF-8 document they are
written literally and round-trip (`verify.py` §2). All three consumers are UTF-8 and render
them; `pytest` itself emits `→` literally into JUnit (verified by generating its output). No
ASCII fallback is needed. DF-209 must only ensure the declared encoding is UTF-8.

---

## Corroboration: what `pytest --junitxml` actually emits (run, not recalled)

Generating pytest's own JUnit for a failing assertion produced:

```xml
<testcase classname="test_probe" file="test_probe.py" line="0" name="test_regression" time="0.002">
  <failure message="AssertionError: issue_refund called at turn 3\n  expected: never called\n...">
    def test_regression():
    ...
    E       AssertionError: issue_refund called at turn 3
  </failure>
</testcase>
```

Three things this pins down, offline: **one `<failure>` per `<testcase>`** (A's cardinality,
against C); **`classname`/`name`/`time` present** (Q4); **`→` written literally** (Q5). And the
refinement A makes over pytest: pytest crams a multi-line string into `message` that
attribute-normalization then space-collapses on the consumer side — A instead writes a clean
one-line `message` and keeps the full block in the text body. A is pytest's battle-tested shape,
done a little better.

---

## For DF-209 (implementation notes, not decisions)

- Match `candidates/A.xml` structurally. It is the reference.
- Reuse the existing failure renderer (`domain/assertions/trajectory.render_failure`) for the
  per-assertion blocks — do not reimplement the `✗ / expected / actual` format; the JUnit body
  is that same text, XML-escaped, concatenated.
- The sink is an **event sink adapter** (like `reporting/json_sink.py`), not a domain concern —
  it reads the same results the terminal/JSON reporters do. No new domain type.
- Escape `&`, `<`, `>` in all text and `"` in attributes; declare `encoding="UTF-8"`; do not
  emit character references for `→`.
- Surface a zero-case run with an explicit note (do not let `failures="0"` read as green).
- **Live-confirm the [DOC] rows** (`render_notes.md` kit) before DF-212 ships the `docs/ci.md`
  screenshots — same throwaway-repo discipline DF-210 carries.

# EPIC-001 — Tickets AC-010 … AC-019

Continues `TICKETS-AC-001-009.md`. The global constraints at the top of that file apply
here unchanged. `SPEC.md` is authoritative and carries the six post-spike amendments.

**Ordering wrinkle to know about before you start.** AC-004 (spec loader) already consumes
an assertion-kind registry in its pre-pass, but the assertions themselves are built in
AC-010/AC-011. Resolution: AC-004 creates `assertions/registry.py` exposing `known_kinds()`
backed by a hardcoded set. AC-010 replaces the backing with real self-registration
**without changing that public surface**. If AC-004's tests break during AC-010, the
registry surface was changed and should be restored instead.

---

### AC-010 — Assertion framework
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-002, AC-004   **Spec:** §6, §6.3

**Prompt:**
> **Context.** Assertions are the extension point of this product — `SPEC.md` §6.3 requires
> that adding one touches exactly two files, and EPIC-001 success criterion 7 tests exactly
> that. This ticket builds the framework; AC-011 builds the six v0.1 assertions on top of
> it. Assertions read the whole `Trace` (AC-002) and never touch the loop.
>
> **Task.** Implement the assertion protocol, `AssertionResult`, and a self-registering
> registry that also serves spec-time kind validation.
>
> **Constraints.**
> - An assertion receives the **entire `Trace`**, not just final text. That is the product
>   thesis; do not narrow the interface for convenience.
> - `AssertionResult` carries `kind`, `description`, `passed`, `message`, `expected`,
>   `actual` per SPEC §6. `description` is the rendered human form (e.g.
>   `not_calls_tool: issue_refund`) and is what reporters print.
> - Registration is by kind string via a decorator. Adding an assertion = one new file in
>   `assertions/` + one import line. **No changes to the loop, the loader, or reporters.**
> - Each assertion declares an args model (pydantic) so malformed assertion arguments are a
>   **spec error caught by `validate`**, not a runtime failure mid-run.
> - `known_kinds()` must keep the exact public surface AC-004 already imports. Replace its
>   backing, not its signature.
> - An assertion must never raise. An internal failure becomes
>   `AssertionResult(passed=False)` with a message identifying it as an internal error — one
>   broken assertion must not abort a run.
> - Assertions are pure: `Trace` in, `AssertionResult` out. No I/O, no clock, no randomness.
>   (`llm_judge` in v0.3 breaks this and will need an explicit async variant — do not design
>   it in now, but do not make it impossible either.)
>
> **Files.**
> - `agentcheck/assertions/base.py` — `Assertion` protocol, `AssertionResult`, `@register` decorator.
> - `agentcheck/assertions/registry.py` — replace AC-004's stub backing; `known_kinds()`, `get(kind)`, `validate_args(kind, args)`.
> - `tests/unit/test_assertion_framework.py`.
>
> **Acceptance criteria.**
> - [ ] A toy assertion registered in a test module is discoverable via `get()` and appears
>       in `known_kinds()`.
> - [ ] Registering a duplicate kind raises at import time, naming both sources.
> - [ ] Malformed assertion args are caught by `validate_args()` and surface as a spec
>       error through AC-004's pipeline — test end to end from a broken YAML fixture.
> - [ ] An assertion that raises internally yields `passed=False` with an internal-error
>       message; the run continues.
> - [ ] AC-004's existing loader tests still pass unmodified.
> - [ ] `mypy --strict` clean, with the protocol satisfied structurally rather than by
>       inheritance.
>
> **Out of scope.** The six concrete assertions (AC-011). `llm_judge` (v0.3). Reporting.
>
> **Deliverable.** A framework where AC-011 is six small files and a registry import.

---

### AC-011 — Structural assertions
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-009, AC-010   **Spec:** §6, §6.1

**Prompt:**
> **Context.** These six assertions are the product. Everything else exists to get a `Trace`
> in front of them. **`SPEC.md` §6 states that failure messages are the UX** and mandates
> that every structural failure show the actual ordered tool-call sequence. Read that
> section's required output sample before writing code — matching it is an acceptance
> criterion, not a suggestion.
>
> **Task.** Implement the six v0.1 assertions from SPEC §6.1: `calls_tool`,
> `not_calls_tool`, `tool_args`, `call_order`, `max_turns`, `final_contains`.
>
> **Constraints.**
> - Required failure format, reproduced from SPEC §6:
>   ```
>   ✗ not_calls_tool: issue_refund
>       expected: issue_refund never called
>       actual:   lookup_order → issue_refund → (end_turn)
>                 issue_refund called at turn 2 with {"order_id": "A-991", "amount": 780.0}
>   ```
>   The trajectory line (`a → b → (termination)`) appears on **every** structural failure.
>   Build it once as a shared helper; do not reimplement per assertion.
> - `calls_tool` accepts a bare string or `{tool, count}` for an exact count.
> - `not_calls_tool` is the highest-value assertion in the set — it is the safety-regression
>   case. Its message must name the turn index and the offending arguments.
> - `tool_args` does a **deep subset** match, same semantics as AC-008's `when`. Reuse that
>   matcher; do not write a second one that can drift.
> - `call_order` is a **subsequence** check, not contiguity: `[a, c]` passes for
>   `a → b → c`.
> - `final_contains` is case-insensitive and accepts a string or list (all must be present).
> - **Malformed arguments (SPIKE-001):** `tool_args` against a call whose
>   `malformed_arguments` is set must fail with a message naming *malformed arguments* as
>   the cause and showing the raw string — never a confusing empty-dict mismatch.
> - Assertions against a trace that terminated abnormally (`provider_error`,
>   `unmocked_tool`) must still produce a coherent result, not crash on a short trace.
>
> **Files.**
> - `agentcheck/assertions/structural.py` (or one file per assertion — your call, but §6.3's two-file rule must still hold).
> - `agentcheck/assertions/_trajectory.py` — the shared `a → b → (end_turn)` renderer.
> - `tests/unit/test_assertions_structural.py`.
>
> **Acceptance criteria — pass and fail case for each of the six, plus:**
> - [ ] Golden-file test pinning the exact rendered failure of the SPEC §6 example. Byte-for-byte.
> - [ ] Every structural failure message contains the trajectory line — parametrised test across all six.
> - [ ] `calls_tool` with `count` fails when the count differs, and the message states both numbers.
> - [ ] `tool_args` deep subset: `{a: 1}` passes against `{a: 1, b: 2}`.
> - [ ] `tool_args` on a malformed-arguments call fails naming malformed arguments and shows the raw string.
> - [ ] `call_order` passes for a non-contiguous subsequence and fails for a true reordering.
> - [ ] `final_contains` with a list fails when only some strings are present, and names which were missing.
> - [ ] Each assertion produces a coherent result against a `provider_error` trace with zero turns.
> - [ ] Adding a seventh (throwaway) assertion in the test suite requires exactly two files — EPIC-001 success criterion 7.
>
> **Out of scope.** `cost_under` / `latency_under_ms` / `min_tool_calls` / regex / JSON-schema (v0.2). `llm_judge` (v0.3).
>
> **Deliverable.** Six assertions whose failure output a user can act on without opening the trace.

---

### AC-012 — Concurrent case scheduler
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-009   **Spec:** §5

**Prompt:**
> **Context.** `run_case` (AC-009) is `async` and deliberately owns no scheduling. Cases are
> independent and network-bound, so running them concurrently is most of the wall-clock win.
> SPEC §5 sets default concurrency 4 and requires results reported in **spec order, not
> completion order**.
>
> **Task.** Implement the scheduler that runs many cases concurrently and returns ordered
> results.
>
> **Constraints.**
> - `asyncio` with a `Semaphore`. Default concurrency 4, overridable.
> - Results returned in **spec order** regardless of completion order. Reporters depend on
>   this for stable, diffable output.
> - Per-case failures are isolated: a case that raises unexpectedly becomes a failed result
>   with the exception recorded, and the remaining cases still run.
> - **`--fail-fast` semantics (decide and document):** on first failure, cancel in-flight
>   tasks and report only completed results, clearly marking the run as incomplete. Do not
>   silently present a partial run as a full one.
> - Each case gets a **fresh `MockResolver`** — AC-008 requires per-case `sequence` state and
>   concurrent cases must not interfere.
> - Progress output goes through an injected callback, never printed directly. The reporter
>   (AC-013) owns all output.
> - Deterministic under `FakeProvider`: same input, same ordered results, every run.
>
> **Files.**
> - `agentcheck/runner/scheduler.py` — `run_suites()`, `RunResult`, `SuiteResult`, `CaseResult`.
> - `tests/unit/test_scheduler.py`.
>
> **Acceptance criteria.**
> - [ ] 10 cases with staggered fake delays return in spec order — assert the exact name list.
> - [ ] Concurrency is genuinely bounded: instrument the provider to record max in-flight calls and assert it never exceeds N.
> - [ ] A case raising an unexpected exception is isolated; the other 9 complete.
> - [ ] `--fail-fast` cancels in-flight work and marks the run incomplete; a test asserts fewer results than cases.
> - [ ] Each case receives a distinct resolver instance — verify `sequence` state does not bleed across concurrent cases.
> - [ ] 50 cases at concurrency 4 complete without unbounded task creation.
> - [ ] Two identical runs against `FakeProvider` produce equal results.
>
> **Out of scope.** Reporting, progress rendering, retries (v0.2).
>
> **Deliverable.** `run_suites()` returning an ordered, isolated, bounded result set.

---

### AC-013 — Terminal reporter
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-011, AC-012, AC-017   **Spec:** §7.2

**Prompt:**
> **Context.** This is what people screenshot. `SPEC.md` §7.2 gives the exact target layout.
> The failure rendering comes from AC-011's `AssertionResult`s; the cost column comes from
> AC-017 and may legitimately be `None`.
>
> **Task.** Implement the `rich`-based terminal reporter matching SPEC §7.2.
>
> **Constraints.**
> - Reproduce the §7.2 layout: suite header with file path, per-case line with status glyph,
>   turn count, tokens, cost, duration; indented assertion failures beneath a failing case;
>   a summary line with totals.
> - **Must degrade cleanly when stdout is not a TTY** — no ANSI, no spinners, no cursor
>   control. CI logs are a primary consumer and this is an acceptance criterion, not a nicety.
> - Unknown cost renders as `—`, never `$0.0000`. A fabricated zero is worse than an honest blank.
> - Failure blocks come from `AssertionResult` verbatim. The reporter **formats**, it does not
>   compose messages — if a message needs improving, fix AC-011.
> - Long argument dicts truncate with an ellipsis and a note, but the trajectory line is
>   **never** truncated.
> - Non-`end_turn` terminations are surfaced explicitly on the case line (e.g.
>   `max_turns_exceeded`), not hidden as a generic failure.
> - Respect `NO_COLOR` and `--no-color`.
>
> **Files.**
> - `agentcheck/reporters/terminal.py`.
> - `tests/unit/test_terminal_reporter.py`, `tests/fixtures/expected_output/*.txt`.
>
> **Acceptance criteria.**
> - [ ] Golden-file test: a 2-case run (1 pass, 1 fail) renders byte-identically to the SPEC §7.2 sample.
> - [ ] Non-TTY output contains zero ANSI escape sequences — assert on the raw bytes.
> - [ ] `NO_COLOR=1` produces plain output.
> - [ ] `cost=None` renders `—`.
> - [ ] `max_turns_exceeded` is visible on the case line.
> - [ ] A 200-character tool-args dict truncates while the trajectory line stays whole.
> - [ ] Summary totals equal the sum of case values — property test over generated results.
> - [ ] A zero-case run prints a clear "no cases matched" message and does not crash.
>
> **Out of scope.** JSON (AC-014), JUnit/HTML (v0.2/v0.3), progress spinners.
>
> **Deliverable.** A reporter whose golden files make regressions in output obvious in a diff.

---

### AC-014 — JSON reporter and trace serialization
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-013   **Spec:** §7

**Prompt:**
> **Context.** `--json-out` is how the tool feeds anything that isn't a human: CI scripts,
> the v0.3 compare command, the v0.3 HTML report. Its schema is a **public interface** from
> the moment it ships.
>
> **Task.** Implement the JSON reporter and full trace serialization.
>
> **Constraints.**
> - Top-level `schema_version: 1`. Anything consuming this can then version-guard.
> - Emit the **complete** `Trace` per case, including every turn, `request_messages`,
>   `Message.raw`, `malformed_arguments`, usage, and all `AssertionResult`s. This file must
>   be sufficient to re-render the terminal report offline.
> - Deterministic key order (sorted) so two runs of the same suite produce a diffable file.
> - No non-finite floats — required for v0.2 fingerprint compatibility.
> - Timestamps ISO-8601 UTC with an explicit `Z`.
> - Written atomically (temp file + rename): a killed run must not leave a truncated JSON.
> - `--json-out` composes with the terminal reporter rather than replacing it; `--reporter json`
>   sends JSON to stdout and suppresses terminal output.
>
> **Files.**
> - `agentcheck/reporters/json_reporter.py`.
> - `tests/unit/test_json_reporter.py`.
>
> **Acceptance criteria.**
> - [ ] Output validates against a committed JSON Schema in `tests/fixtures/run_schema.json`.
> - [ ] Round-trip: serialize → deserialize → re-render terminal output identical to the original.
> - [ ] Two identical runs produce byte-identical JSON except timestamps.
> - [ ] `Message.raw` and `malformed_arguments` survive serialization.
> - [ ] No `NaN` / `Infinity` in output — property test over generated traces.
> - [ ] Interrupting mid-write leaves either no file or a complete one, never a partial.
> - [ ] `--json-out` plus terminal output both work in one run.
>
> **Out of scope.** JUnit XML (v0.2), HTML (v0.3).
>
> **Deliverable.** A stable, schema-validated run artifact.

---

### AC-015 — CLI surface and exit codes
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-014   **Spec:** §7, §7.1

**Prompt:**
> **Context.** Everything built so far is libraries. This ticket exposes them. `SPEC.md` §7.1
> declares exit codes **contractual** — they are the primary interface for CI and changing
> them later is a breaking change.
>
> **Task.** Implement `run`, `validate`, and `trace` with all flags from SPEC §7 and exact
> exit-code behaviour from §7.1.
>
> **Constraints.**
> - Exit codes, no exceptions: `0` all passed · `1` assertion failures · `2` spec/config
>   error · `3` provider/network error. **One test per code.**
> - Ordering matters: a spec error is `2` **even if** a provider is also unreachable. Config
>   validity is checked before anything network-touching happens.
> - `validate` makes **zero** network calls, ever. Assert this with a patched transport.
> - `trace <suite::case>` runs one case and prints every turn: request messages, response,
>   tool calls, tool results. This is the debugging command — verbosity is the point.
> - An unhandled internal exception exits `2` with a short message plus a "please report
>   this" line, never a raw traceback, unless `--debug` is passed.
> - No business logic in `cli.py`. It parses flags, calls libraries, maps results to exit
>   codes. If logic wants to live here, it belongs in a module.
> - `--filter` and `--tag` compose (AND). Matching nothing is exit `0` with a clear
>   "no cases matched" message — not a silent success.
>
> **Files.**
> - `agentcheck/cli.py`.
> - `tests/integration/test_cli.py` — via `typer.testing.CliRunner`.
>
> **Acceptance criteria.**
> - [ ] Four tests, one per exit code, asserting the numeric code.
> - [ ] A suite with both a spec error and an unreachable provider exits `2`.
> - [ ] `validate` on a valid suite exits `0` and makes zero network calls.
> - [ ] `validate` on the AC-004 broken fixture exits `2` and prints positioned errors.
> - [ ] `trace suite::case` prints all turns including tool results.
> - [ ] `--filter` and `--tag` compose; a zero-match run exits `0` with the explicit message.
> - [ ] `--model` overrides both project and suite settings.
> - [ ] An injected internal exception yields a clean message and exit `2`; `--debug` shows the traceback.
> - [ ] `--help` for every command exits `0`.
>
> **Out of scope.** `init` (AC-016). `compare` / `export` (v0.3/v0.4).
>
> **Deliverable.** A CLI whose exit codes are individually tested and safe to depend on.

---

### AC-016 — `init` scaffold and the 60-second target
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-015   **Spec:** §1.6

**Prompt:**
> **Context.** SPEC §1.6 makes this a **hard acceptance criterion**: `uvx agentcheck init`
> to a green test in under 60 seconds on a clean machine, **with no API key**. For a
> developer tool this single number outweighs the next twenty features. It is achievable
> only because AC-006 shipped `FakeProvider` inside the package.
>
> **Task.** Implement `agentcheck init` and the bundled example that makes the target real.
>
> **Constraints.**
> - Scaffold: `agentcheck.yaml`, `evals/hello.eval.yaml` (keyless, `FakeProvider`-backed),
>   `evals/refund_agent.eval.yaml` (the real SPEC §4.3 example, requires a key), and a short
>   `evals/README.md`.
> - **The default example must pass with no API key and no network.** That is what makes the
>   60 seconds achievable and it is the whole design of this ticket.
> - `init` prints exactly what to run next — one command, copy-pasteable.
> - The keyed example is clearly marked as needing `ANTHROPIC_API_KEY` and does not fail the
>   default run: skipped with a visible note, not a failure.
> - `init` refuses to overwrite existing files unless `--force`, and lists what it would
>   have touched.
> - The scaffolded YAML is **commented** — it doubles as documentation and is many users'
>   first and only encounter with the spec format. Write those comments as carefully as the code.
> - Both scaffolded suites must be valid per `validate`.
>
> **Files.**
> - `agentcheck/scaffold/template/**` — the files as data.
> - `agentcheck/cli.py` — the `init` command.
> - `tests/integration/test_init.py`.
> - `scripts/measure_cold_start.sh` — the timing harness.
>
> **Acceptance criteria.**
> - [ ] **Stopwatch criterion:** in a clean container with no `ANTHROPIC_API_KEY`,
>       `scripts/measure_cold_start.sh` performs install → `init` → `run` and reports total
>       wall-clock. **Must be under 60s.** Record the measured number in the PR description.
>       This is a measurement, not a judgement call.
> - [ ] `agentcheck init && agentcheck run` exits `0` with no API key and no network.
> - [ ] The keyed example is skipped with a visible note, not a failure.
> - [ ] `init` into a non-empty directory refuses without `--force` and lists the conflicts.
> - [ ] Both scaffolded suites pass `agentcheck validate`.
> - [ ] The command printed by `init` is the one the tests actually run — assert the string.
> - [ ] Scaffolded YAML contains explanatory comments on every top-level key.
>
> **Out of scope.** README (AC-019). The GIF (AC-019).
>
> **Deliverable.** A measured cold-start number under 60 seconds, recorded in the PR.

---

### AC-017 — Pricing data and cost computation
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-002   **Spec:** §3.2

**Prompt:**
> **Context.** SPEC §3.2 makes cost **advisory**: stale pricing is a documented, accepted
> limitation, and an unknown model yields `None` — never an exception, never a guess. AC-013
> renders `None` as `—`. Cost assertions arrive in v0.2; this ticket only computes.
>
> **Task.** Implement the bundled pricing table and cost calculation.
>
> **Constraints.**
> - `agentcheck/data/pricing.yaml`, keyed `provider:model` → `{input, output, cache_read,
>   cache_write}` in **USD per million tokens**.
> - Unknown model → `None`. Never raise, never fall back to a similar model, never zero.
> - User override via `pricing_file:` in project config **replaces** the bundled table for
>   matching keys and merges for the rest.
> - Include a `_meta.updated` date in the bundled file and surface it in `--version` so users
>   can see how stale it is.
> - Cache tokens are priced separately; a model without cache pricing uses input pricing for
>   cache reads and records that it did so.
> - Return `Decimal` internally to avoid float drift over long runs; convert at the display
>   boundary only.
> - Model matching is **exact string match**. No prefix matching, no fuzzy matching — a
>   near-miss silently pricing against the wrong model is worse than `None`.
>
> **Files.**
> - `agentcheck/data/pricing.yaml`, `agentcheck/pricing.py`.
> - `tests/unit/test_pricing.py`.
>
> **Acceptance criteria.**
> - [ ] Known model + known usage returns the hand-computed expected value.
> - [ ] Unknown model returns `None` and does not raise.
> - [ ] A near-miss model name (`claude-sonnet-4-6-typo`) returns `None`, not a fuzzy match.
> - [ ] User `pricing_file` overrides a bundled entry and leaves others intact.
> - [ ] Cache read/write tokens are priced separately when the model defines them.
> - [ ] Summing 1,000 case costs shows no float drift (`Decimal` throughout).
> - [ ] `pricing.yaml` parses and every entry has all four keys — schema test over the file.
> - [ ] `--version` shows the pricing `_meta.updated` date.
>
> **Out of scope.** `cost_under` assertion (v0.2). Fetching live prices — ever.
>
> **Deliverable.** Honest advisory costs that degrade to `—` rather than lying.

---

### AC-018 — Dogfood suite in CI
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-016   **Spec:** §8.2

**Prompt:**
> **Context.** SPEC §8.2 requires agentcheck to run its own eval suite in CI against
> `FakeProvider`. Beyond testing, this is the credibility artifact: a tool that does not use
> itself is hard to recommend, and the CI badge is a claim you want to be able to make.
>
> **Task.** Write an eval suite exercising agentcheck's own features and wire it into CI as a
> required check.
>
> **Constraints.**
> - `evals/self/*.eval.yaml`, run against `FakeProvider`. No API key, no network.
> - Cover every one of the six assertions in both a passing and a failing case. Failing cases
>   run under a harness asserting the **expected** failure — the CI job is green when the
>   failures fail correctly.
> - Cover each termination reason: `end_turn`, `max_turns_exceeded`, `unmocked_tool`,
>   `provider_error`.
> - Cover `sequence` mocks (error-then-success) — the differentiating feature deserves a
>   dogfood case.
> - Runs as a separate CI job from `pytest`, so a dogfood failure is distinguishable at a
>   glance from a unit-test failure.
> - Runtime under 30 seconds.
> - These suites are also **documentation**: they are what users will read to learn the
>   format. Comment them accordingly.
>
> **Files.**
> - `evals/self/*.eval.yaml`, `scripts/run_dogfood.sh`.
> - `.github/workflows/ci.yml` — new `dogfood` job.
>
> **Acceptance criteria.**
> - [ ] All six assertions appear in both a passing and a deliberately-failing case.
> - [ ] All four termination reasons are exercised.
> - [ ] A `sequence` error-then-success case is present.
> - [ ] The whole dogfood run completes in under 30 seconds with no network.
> - [ ] The CI job fails if an expected-pass case fails **or** an expected-fail case passes.
> - [ ] Every suite file carries explanatory comments.
>
> **Out of scope.** Live-provider evals — separate manual pre-release step.
>
> **Deliverable.** A CI job proving the tool works by using it.

---

### AC-019 — README, demo GIF, and PyPI release
**Type:** chore   **Milestone:** v0.1
**Depends on:** AC-018   **Spec:** §1.6, §9

**Prompt:**
> **Context.** Final ticket of EPIC-001. SPEC §1.6 identifies three things that matter more
> for dev-tool adoption than the next twenty features: sub-60-second time-to-green, a
> runnable example above the fold, and a demo GIF. AC-016 delivered the first. This ticket
> delivers the other two and ships.
>
> **Task.** Write the README, record the demo, publish to PyPI.
>
> **Constraints.**
> - **A runnable example must appear above the fold** — before installation instructions,
>   before the feature list, before badges beyond a single CI badge. A visitor should see
>   what a suite looks like and what failure output looks like within one screen.
> - Lead with the **differentiator**: assertions on the tool-call trajectory, not on final
>   text. The `not_calls_tool` safety-regression example is the strongest hook — put it in
>   the first example, not in a features table.
> - Include a real failure-output block. Showing good failure output is more persuasive than
>   describing it.
> - Demo GIF via `vhs` (scripted and committed, so it can be re-recorded on change) or
>   `asciinema`. Under 30 seconds, showing `init` → `run` → a failure → a fix → green.
> - State honestly what this is **not**: not an observability platform, not hosted, not a
>   prompt-management system. Cite SPEC §1.5. Being explicit about non-goals earns more
>   trust than implying you do everything.
> - Comparison table against Promptfoo / Langfuse must be **fair** — name what they do
>   better. An unfair table is the fastest way to get dismissed by the exact people whose
>   opinion carries.
> - PyPI: verify the name is available **before** anything else in this ticket. If taken, stop
>   and escalate — the rename touches `pyproject.toml`, the CLI entry point, and `.agentcheck/`
>   paths across the whole epic.
> - Tag `v0.1.0`, publish via a GitHub Action on tag using trusted publishing, not a token.
>
> **Files.**
> - `README.md`, `docs/demo.tape` (vhs script), `docs/demo.gif`, `CONTRIBUTING.md`, `CHANGELOG.md`.
> - `.github/workflows/release.yml`.
>
> **Acceptance criteria.**
> - [ ] PyPI name availability confirmed and recorded before other work starts.
> - [ ] A runnable suite example and a failure-output block both appear within the first screen.
> - [ ] The comparison table names at least one thing each competitor does better.
> - [ ] Non-goals section present, citing SPEC §1.5.
> - [ ] Demo GIF under 30s, its source script committed.
> - [ ] `uvx agentcheck@0.1.0 init` works from PyPI on a clean machine after publish.
> - [ ] `CHANGELOG.md` covers v0.1.0.
> - [ ] Release workflow publishes on tag via trusted publishing.
>
> **Out of scope.** Docs site, blog post, launch posts — separate from shipping the package.
>
> **Deliverable.** `pip install agentcheck` works, and the README earns a second look from
> someone who found it through a search result.

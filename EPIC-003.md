# EPIC-003 — dryfire v0.3: Judgment & Comparison

**Spec:** `SPEC.md` §9 (v0.3) · **Architecture:** `ARCHITECTURE.md`
**Depends on:** EPIC-002 shipped
**Status:** Ready for spikes

---

## 1. Epic goal

Three capabilities that share one theme — measuring things that are not boolean:

- **`llm_judge`** — rubric-graded assertions for behaviour no structural check can express.
- **`compare`** — run one suite across N models or N prompt variants and print the matrix.
- **`repeat: N`** — run a case N times and report a pass rate, because agent behaviour is
  stochastic and a single green run can be luck.

## 2. The tension this epic has to resolve

v0.1 and v0.2 sold one property above all others: **runs are deterministic, free, and never
flaky.** Every capability in v0.3 attacks that property.

- A judge is a model call: it costs money, adds latency, and its verdicts vary run to run.
- `repeat` exists precisely to *measure* nondeterminism, so it cannot be replayed from a
  single cassette.
- `compare` multiplies every case by every model.

**The resolution is segregation, not compromise.** Structural assertions stay pure, free,
and deterministic — that is the merge-gate path and it must not regress. Judged assertions
are opt-in, cassette-backed, and separately cost-accounted. `repeat` is an explicit,
labelled departure from determinism. A suite with no judge and no `repeat` must behave
identically to v0.2 in every respect, including runtime and cost.

If at the end of this epic a default `dryfire run` is slower or more expensive than it was
in v0.2, the epic failed regardless of what shipped.

## 3. Success criteria

1. Import-linter contract 3 still passes: **`domain/` imports only pydantic and stdlib.** A
   judge needs I/O, and the domain must not acquire it. This is the architectural test of
   this epic, the way the empty loop diff was EPIC-002's.
2. A suite with no `llm_judge` and no `repeat` runs at v0.2 speed and cost — benchmarked,
   not assumed.
3. Judge cost is reported **separately** from case cost and never silently folded into the
   total (SPEC §9).
4. Every judged result carries the judge model version and a rubric hash. A score without
   both is not comparable to any other score.
5. `compare` output is legible enough to screenshot without editing — it is the most
   shareable artifact the tool produces.
6. `repeat` results state a pass rate as `k/N`, never a bare pass/fail.
7. Full offline test suite still passes with no API key.

## 4. In scope

SPEC §9 (v0.3): `llm_judge` · `compare` · `repeat` · HTML report.

## 5. Out of scope

Code export (v0.4) · trend storage, dashboards, or any time-series database · production
monitoring · judge fine-tuning · human labelling UI · statistical significance testing
beyond a reported pass rate.

> **The dashboard trap.** `repeat` produces pass rates, and pass rates over time produce a
> chart, and a chart wants a database. That path ends at Langfuse, which is a different
> product built by more people. dryfire emits a JSON artifact per run and stops there — what
> a user does with a directory of those artifacts is their business. SPEC §1.5 is binding.

## 6. Sequencing

```
  SPIKE-006 (async assertions) ──┐
  SPIKE-007 (repeat + cassettes) ┼──┐
                                 │  │
  DF-301 (judge domain model) ───┘  │
        ↓                           │
  DF-302 (judge evaluator port)     │
        ↓                           │
  DF-303 (llm_judge assertion)      │
        ↓                           │
  DF-304 (judge cost accounting)    │
                                    ↓
  DF-305 (repeat execution) ────────┤
  DF-306 (repetition cassette keys) ┘
        ↓
  DF-307 (compare execution)
        ↓
  DF-308 (compare matrix output)
        ↓
  DF-309 (HTML report sink)
        ↓
  DF-310 (docs + v0.3.0 release)
```

---

## 7. Spike tickets

### SPIKE-006 — Async assertion execution model
**Type:** spike   **Time-box:** 1 day   **Depends on:** none

**Prompt:**
> **Context.** `ARCHITECTURE.md` §4.3 and §5.1 state that assertions are **pure**: `Trace`
> in, `AssertionResult` out, no I/O, no clock, no randomness. Contract 3 in `.importlinter`
> enforces that `domain/` imports only pydantic and the stdlib. §5.1 explicitly flagged that
> `llm_judge` breaks this and deferred the decision to now: *"do not design it in now, but
> do not make it impossible either."*
>
> A judged assertion needs a model call. That is I/O, in the domain, in a layer that
> forbids it. This spike decides how it fits without either weakening the contract or
> bolting an exception onto it.
>
> **Task.** Prototype and evaluate at least three execution models, then recommend one.
>
> **Models to evaluate.**
> - **(A) Two-phase evaluation.** Pure assertions run in the domain as today. Judged
>   assertions are collected as *requests*, executed by the application layer (which has
>   gateway access), and their verdicts fed back into pure threshold assertions. The domain
>   never performs I/O; it only declares what it needs.
> - **(B) All assertions async.** `evaluate()` becomes `async`. Domain gains an async
>   surface; pure assertions simply never await. Contract 3 survives only if the gateway is
>   injected rather than imported.
> - **(C) Judge as a pre-assertion enrichment stage.** The application layer runs judges
>   after the loop and attaches `JudgeVerdict` objects to the `Trace`. Assertions stay
>   entirely pure and merely read a field that is already populated.
>
> **Constraints.** Contract 3 must still pass under the recommended model — no exemptions
> added to `.importlinter`. Judged assertions must be batchable: N judged assertions across
> M cases should not be N×M serial round trips. Judge calls must be cassette-backed through
> the existing `CachingGateway`, not a parallel caching path. Structural-only suites must
> take **zero** additional code paths.
>
> **Files.** `spikes/006_async_assertions/` with one prototype module per model, `bench.py`, `FINDINGS.md`.
>
> **Acceptance criteria.**
> - [ ] All three models prototyped against a real `Trace` and a `FakeGateway` judge.
> - [ ] Contract-3 compliance verified per model by actually running import-linter against each prototype.
> - [ ] A benchmark showing the overhead each model adds to a **structural-only** suite of 50 cases. Model (C) should be ~zero; measure, do not assume.
> - [ ] Batching demonstrated: 20 judged assertions across 10 cases issue fewer than 20 sequential round trips.
> - [ ] The interaction with `CachingGateway` shown to work — a judged assertion replays from a cassette.
>
> **Questions FINDINGS.md must answer.**
> 1. Which model, and what specifically do the other two cost?
> 2. Does the recommended model require any change to the `Assertion` protocol? If yes, does it break the two-file rule for adding an assertion (SPEC §6.3)?
> 3. Where does a judge failure (provider error, timeout) surface — as a failed assertion, an errored case, or a distinct third state? Argue for one.
> 4. Can judge calls be batched across cases, or only within one? What does that imply for the scheduler?
> 5. Does the `Trace` model need a new field, and if so does it affect the v0.2 JSON schema version?
>
> **Out of scope.** Rubric design, threshold selection, the assertion itself.
>
> **Deliverable.** `FINDINGS.md` with a **Verdict** naming the model and a reference implementation of the seam, plus any required amendment to ARCHITECTURE §4.3 / §5.1 stated explicitly.

---

### SPIKE-007 — Repetition, cassette keying, and pass-rate meaning
**Type:** spike   **Time-box:** half day   **Depends on:** none

**Prompt:**
> **Context.** `repeat: N` runs a case N times and reports a pass rate, to measure the
> flakiness that a single run hides. It collides directly with cassettes: SPIKE-002's
> fingerprint is a hash of the request, so N identical requests produce **one** key. You
> cannot store N different responses under it. SPEC §9 (v0.3) hand-waved this as "`repeat`
> forces `cassette-mode=off` unless N cassette variants exist" — that is a placeholder, not
> a design.
>
> There is a second, sharper question underneath: **what does a pass rate from N runs
> actually tell you, and what is the smallest N that means anything?** Reporting `3/5` as if
> it were a measurement, when the confidence interval spans most of the unit interval, is
> the kind of number that gets used to make bad decisions.
>
> **Task.** Settle both the cassette keying scheme and the statistical honesty of the
> reported number.
>
> **Constraints.** Any keying change must preserve every SPIKE-002 stability and sensitivity
> property — re-run its 19 tests against the modified scheme. `repeat: 1` must produce a
> key byte-identical to today's, so existing cassettes stay valid. No new dependency for
> the statistics; this is arithmetic.
>
> **Files.** `spikes/007_repeat/` with `keying.py`, `test_keying.py` (SPIKE-002's suite plus new cases), `stats.py`, `FINDINGS.md`.
>
> **Acceptance criteria.**
> - [ ] A repetition-aware key that stores N distinct responses per logical request, with `repeat: 1` unchanged from v0.2.
> - [ ] All 19 SPIKE-002 tests pass against the modified scheme.
> - [ ] Replaying a `repeat: 5` case reproduces the same 5 responses in the same order.
> - [ ] A `repeat: 5` case with only 3 cassettes recorded behaves per a documented policy in each of the four cassette modes.
> - [ ] A confidence interval computed for a `k/N` pass rate (Wilson score, no dependency).
>
> **Questions FINDINGS.md must answer.**
> 1. The keying scheme, stated as pseudocode. Where does the repetition index live — in the hash input, in the filename, or in the file body?
> 2. Does replay of a repeated case preserve response *order*, and does order matter for a pass rate? (It does not, but state why.)
> 3. What is the smallest N that produces a meaningful rate? Give the interval width at N=3, 5, 10, 20 for an observed 80% pass rate.
> 4. Should the terminal reporter show the interval alongside `k/N`, or is that noise for the merge-gate audience? Recommend, with a reason.
> 5. Does `repeat` interact with `compare`? A repeated case across four models is 4N runs — is that combination allowed, warned about, or refused?
>
> **Out of scope.** Implementing `repeat` execution, reporter changes.
>
> **Deliverable.** `FINDINGS.md` with a **Verdict** giving the keying scheme, the recommended minimum N (with the tool warning below it), and the reporting format.

---

## 8. Feature tickets

### DF-301 — Judge domain model and rubric versioning
**Depends on:** SPIKE-006   **Spec:** §9 (v0.3)

**Prompt:**
> **Context.** Before any judging happens, the *result* of judging needs a type — and that
> type has one job beyond carrying a score: making scores **comparable across time**.
>
> This is the single most common failure of LLM-as-judge systems. A team charts quality over
> six months, the judge model silently updates or someone reworded the rubric, and the line
> moves for reasons that have nothing to do with the thing being measured. The chart then
> drives decisions. A score without provenance is not a measurement.
>
> **Task.** Implement `JudgeVerdict`, `Rubric`, and rubric hashing in `domain/judging/`.
>
> **Constraints.**
> - `JudgeVerdict` carries: `score`, `passed`, `reasoning`, `judge_model`, `judge_model_version`, `rubric_hash`, `threshold`.
> - **`judge_model_version` and `rubric_hash` are required fields, not optional.** A verdict that cannot state how it was produced must be unconstructable.
> - `rubric_hash` is a stable hash of the rubric text plus its threshold and any few-shot examples — reuse `domain/fingerprint.py`'s canonicalisation rather than writing a second hasher that can drift.
> - Rubric text is whitespace-significant. Reformatting a rubric changes the hash, and that is correct: it may change the judgement.
> - This module is pure and lives in `domain/`. Contract 3 must still pass.
> - The JSON artifact (v0.2 schema) gains judge fields — decide with SPIKE-006 Q5 whether that is a `schema_version` bump.
>
> **Files.** `domain/judging/verdict.py` · `domain/judging/rubric.py` · `tests/unit/domain/test_judge_model.py`.
>
> **Acceptance criteria.**
> - [ ] `JudgeVerdict` cannot be constructed without `judge_model_version` and `rubric_hash`.
> - [ ] Rubric hash is stable across dict key order and unstable across any text change including whitespace.
> - [ ] Two rubrics differing only in threshold hash differently.
> - [ ] Contract 3 passes.
> - [ ] Round-trips through the JSON artifact with no loss.
>
> **Out of scope.** Executing a judge, the assertion, prompt design.

---

### DF-302 — Judge evaluator behind a port
**Depends on:** DF-301, SPIKE-006

**Prompt:**
> **Context.** SPIKE-006 chose the execution model. Implement its verdict exactly — do not
> re-derive it. The judge call goes through the existing `ModelGateway`, which means it is
> automatically cassette-backed and retried by the decorators from EPIC-002. That reuse is
> the point; a parallel judging client would duplicate both.
>
> **Task.** Implement the judge evaluator in the application layer per SPIKE-006's model.
>
> **Constraints.**
> - Judge calls go through `ModelGateway`. **No separate HTTP client, no separate cache.**
> - `temperature=0` for judge calls, always. A judge is an instrument; it should not be creative.
> - The judge prompt asks for structured output (score + reasoning) and parses defensively — an unparseable judge response is a judge *error*, not a score of 0. Scoring 0 on a parse failure would silently fail cases for a bug in the judge.
> - Judge failures surface per SPIKE-006 Q3's answer.
> - Batching per SPIKE-006 Q4.
> - The evaluator is injected, never imported, so tests use a `FakeGateway` judge.
> - Bound judge concurrency separately from case concurrency — otherwise a 50-case run with 3 judged assertions each opens 150 connections.
>
> **Files.** `application/judging/evaluator.py` · `application/ports/` if SPIKE-006 requires a port · `tests/unit/application/test_judge_evaluator.py`.
>
> **Acceptance criteria.**
> - [ ] Judge calls route through `ModelGateway` — assert via `FakeGateway.requests`.
> - [ ] A judged assertion replays from a cassette with no live call.
> - [ ] `temperature=0` on every judge call.
> - [ ] An unparseable judge response is a judge error, distinguishable from a score of 0.
> - [ ] Judge concurrency is bounded independently — assert max in-flight.
> - [ ] Contract 3 passes; `domain/` gained no I/O.

---

### DF-303 — `llm_judge` assertion
**Depends on:** DF-302   **Spec:** §6.2

**Prompt:**
> **Context.** The user-facing assertion: `llm_judge: {rubric, model?, threshold?}`. Per
> SPIKE-006's model the assertion itself should remain **pure** — it reads a verdict that is
> already populated and applies a threshold.
>
> **Task.** Implement the assertion and its spec-level validation.
>
> **Constraints.**
> - Registered like any other assertion. Adding it must not break the two-file rule (SPEC §6.3); if SPIKE-006's model breaks it, say so in the PR rather than quietly accepting it.
> - `rubric` is required. `model` defaults to the case's model; `threshold` defaults to a documented value.
> - **The failure message must include the judge's reasoning and the rubric hash.** A judged failure with no reasoning is unactionable — the user cannot tell whether the agent was wrong or the rubric was.
> - The trajectory line still appears, as with every other assertion.
> - An empty or missing rubric is a **spec error at validate time**, with position.
> - Docs must state plainly that judged assertions cost money, vary between runs, and are not suitable for a merge gate without cassettes.
>
> **Files.** `domain/assertions/judge.py` · registry entry · `tests/unit/domain/test_llm_judge.py` · `docs/judging.md`.
>
> **Acceptance criteria.**
> - [ ] Pass and fail case against a scripted judge verdict.
> - [ ] Failure message contains score, threshold, judge reasoning, rubric hash, and the trajectory line.
> - [ ] Missing rubric is a positioned spec error, zero network calls.
> - [ ] A judge error produces a distinct result state, not a silent fail.
> - [ ] Assertion module remains pure; contract 3 passes.
> - [ ] Docs carry the cost/variance warning.

---

### DF-304 — Separate judge cost accounting
**Depends on:** DF-303   **Spec:** §9 (v0.3)

**Prompt:**
> **Context.** SPEC §9 requires that judge cost be reported separately and "never silently
> folded into the total." The reason is concrete: if judging inflates the case cost, then
> `cost_under` from EPIC-002 (DF-207) starts failing for reasons unrelated to the agent
> under test, and the user debugs the wrong thing.
>
> **Task.** Track and report judge cost and usage as a distinct channel.
>
> **Constraints.**
> - `Trace` (or the run result, per SPIKE-006 Q5) carries `judge_usage` and `judge_cost` separate from case usage and cost.
> - **`cost_under` and `latency_under_ms` from DF-207 must ignore judge cost entirely.** Regression test required — this is the whole reason for the ticket.
> - Terminal output shows judge cost on its own line in the summary, never merged into the case line.
> - The JSON artifact exposes both channels separately.
> - A run with no judged assertions shows no judge cost line at all — not `$0.0000`.
>
> **Files.** `domain/model/trace.py` · `adapters/driven/reporting/terminal.py` · `json_sink.py` · `tests/unit/test_judge_cost.py`.
>
> **Acceptance criteria.**
> - [ ] Judge cost never appears in case cost — assert numerically.
> - [ ] `cost_under` passes on a case whose judge cost would have breached the limit. This is the regression test.
> - [ ] Terminal summary shows both figures distinctly.
> - [ ] Structural-only run shows no judge line.
> - [ ] JSON artifact separates the channels.

---

### DF-305 — `repeat: N` execution and pass rates
**Depends on:** SPIKE-007   **Spec:** §9 (v0.3)

**Prompt:**
> **Context.** Agent behaviour is stochastic even at `temperature=0` — provider-side
> nondeterminism is real. A case that passes once may fail one time in five, and nothing in
> v0.1 or v0.2 can see that. `repeat: N` runs a case N times and reports `k/N`.
>
> **Task.** Implement repeated execution and pass-rate reporting.
>
> **Constraints.**
> - `repeat: N` at case level. Default 1, and `repeat: 1` must be **byte-identical in behaviour** to v0.2 — no new code path for the common case.
> - Repetitions run concurrently under the existing scheduler semaphore, not serially, and not as a nested pool.
> - The result is a **pass rate**, never a bare pass/fail. Whether the case *fails the build* at k<N is a policy: implement `require_pass_rate: <float>` defaulting to 1.0.
> - Each repetition produces a full `Trace`. The JSON artifact keeps all N; the terminal shows the rate and the first failing trace only.
> - **When repetitions disagree, that is the finding.** Surface it prominently — a case that passes 4/5 is more interesting than one that passes 5/5 or 0/5, and the reporter should not bury it.
> - Cassette keying per SPIKE-007's verdict.
> - If SPIKE-007 recommends a minimum N, warn below it rather than refusing.
>
> **Files.** `application/scheduler.py` · `domain/model/case.py` · `adapters/driven/reporting/terminal.py` · `tests/unit/test_repeat.py`.
>
> **Acceptance criteria.**
> - [ ] `repeat: 5` produces 5 traces and a `k/N` rate.
> - [ ] `repeat: 1` takes the identical code path as v0.2 — assert no behavioural difference.
> - [ ] Repetitions respect the global concurrency bound; max in-flight asserted.
> - [ ] `require_pass_rate: 0.8` passes at 4/5 and fails at 3/5.
> - [ ] A disagreeing case is visually distinct in terminal output from a uniformly passing or failing one.
> - [ ] All N traces present in the JSON artifact.
> - [ ] Below-minimum N produces a warning, not a refusal.

---

### DF-306 — Repetition-aware cassette keys
**Depends on:** DF-305, SPIKE-007

**Prompt:**
> **Context.** Implement SPIKE-007's keying verdict. The stakes are the same as SPIKE-002's:
> get this wrong and repeated cases either always miss the cache or silently replay the same
> response N times, which would make a pass rate of 5/5 completely meaningless while looking
> perfectly healthy.
>
> **Task.** Extend the fingerprint and cassette store for repetitions.
>
> **Constraints.**
> - Follow SPIKE-007's scheme exactly, including where the repetition index lives.
> - **All 19 SPIKE-002 tests must still pass**, unmodified.
> - `repeat: 1` produces the v0.2 key byte-for-byte; existing cassettes remain valid. Regression test with a v0.2-recorded cassette committed as a fixture.
> - Replaying a repeated case reproduces N distinct recorded responses, not one response N times. **This is the failure mode the ticket exists to prevent** — test it explicitly.
> - Partial cassettes (3 recorded, 5 requested) behave per SPIKE-007's documented policy in each mode.
> - `prune` (DF-205) understands repetition cassettes.
>
> **Files.** `domain/fingerprint.py` · `adapters/driven/cache/file_store.py` · `tests/unit/domain/test_fingerprint.py` · `tests/unit/adapters/test_cassette_store.py`.
>
> **Acceptance criteria.**
> - [ ] SPIKE-002's 19 tests pass unmodified.
> - [ ] A committed v0.2 cassette still replays under v0.3.
> - [ ] `repeat: 5` replay yields 5 distinct responses — asserted individually, not just by count.
> - [ ] Partial-cassette behaviour tested in all four modes.
> - [ ] `prune` handles repetition cassettes without orphaning valid ones.

---

### DF-307 — `compare` execution
**Depends on:** DF-305   **Spec:** §9 (v0.3)

**Prompt:**
> **Context.** `compare` runs one suite across N models or N prompt variants and produces a
> matrix. SPEC §9 calls it "the single most shareable artifact the tool produces" — it is
> the answer to *"should we switch to the cheaper model?"*, which is a question every team
> running agents in production is asking right now.
>
> **Task.** Implement the execution half. Rendering is DF-308.
>
> **Constraints.**
> - `dryfire compare --models a,b,c [suites...]` and `--prompts file1,file2`. Both axes; not both at once in v0.3 — refuse the combination with a clear message.
> - Reuses the existing scheduler. **This is orchestration over `run_suites`, not a second runner.** If it needs its own execution path, the scheduler abstraction is wrong.
> - Per cell: pass rate, total cost, mean latency, mean turn count.
> - A model that fails entirely (auth error, unknown model) is a **failed column**, not an aborted run. The other columns still complete and report.
> - Cost is estimated and displayed **before execution**, with a confirmation prompt above a configurable threshold. Comparing four models across fifty cases is expensive and nobody should discover that from a bill.
> - Interaction with `repeat` per SPIKE-007 Q5.
> - Emits the same event stream as `run`, so every existing sink works unchanged.
>
> **Files.** `application/usecases/compare.py` · `adapters/driving/cli/compare.py` · `tests/unit/application/test_compare.py`.
>
> **Acceptance criteria.**
> - [ ] 3 models × 5 cases produces 15 results in a stable matrix order.
> - [ ] A failing model yields a failed column; other columns complete.
> - [ ] Cost estimate shown before execution; threshold prompt works and is bypassable with `--yes`.
> - [ ] Uses the existing scheduler — `git diff` shows no new execution path.
> - [ ] Existing sinks consume compare runs without modification.
> - [ ] `--models` combined with `--prompts` is refused with a clear message.

---

### DF-308 — Compare matrix output
**Depends on:** DF-307

**Prompt:**
> **Context.** This output is the marketing asset. SPEC §9: *"design its output for a
> screenshot."* Someone will paste it into a Slack thread to justify a model decision, and
> it has to be readable with no accompanying explanation.
>
> **Task.** Render the compare matrix in the terminal.
>
> **Constraints.**
> - Models as columns, cases as rows, plus a summary row with pass rate, total cost, and mean latency per model.
> - **The interesting cell is the disagreement** — a case that passes on one model and fails on another. Make those visually obvious; a wall of uniform checkmarks teaches nothing.
> - Cost per model displayed prominently. The question being answered is usually "is the cheap model good enough."
> - Degrades on a non-TTY, same rule as AC-013. CI is a real consumer.
> - Wide matrices (6+ models) must stay legible — decide between horizontal scroll, transposition, or truncation with a note, and document the choice.
> - Unknown cost renders `—`, never `$0.0000`.
>
> **Files.** `adapters/driven/reporting/compare_terminal.py` · `tests/unit/adapters/test_compare_output.py` · `tests/fixtures/expected_output/compare_*.txt`.
>
> **Acceptance criteria.**
> - [ ] Golden-file test for a 3×5 matrix with two disagreements.
> - [ ] Disagreeing cells are visually distinct — assert on the rendered characters, not just colour.
> - [ ] Non-TTY output has zero ANSI escapes.
> - [ ] A 6-model matrix stays legible per the documented strategy.
> - [ ] Unknown cost renders `—`.
> - [ ] Summary row totals match the per-cell values.

---

### DF-309 — HTML report sink
**Depends on:** DF-308   **Spec:** §9 (v0.3)

**Prompt:**
> **Context.** The first visual output in the project, and it lands now for a specific
> reason: a single run is a list, which terminals render well, but a compare run is a matrix
> of models × cases, which terminals render badly. The data finally justifies the format.
>
> Because reporters are `EventSink`s (ARCHITECTURE §6), this is a new sink and a template —
> no changes to the loop, scheduler, or any existing reporter.
>
> **Task.** Implement `HtmlReportSink`.
>
> **Constraints.**
> - **One self-contained file.** No CDN, no external assets, no build step, no framework. It must open from disk with no network — an air-gapped CI artifact is a real use case.
> - No server, ever. This is a file, not `dryfire ui`. (ARCHITECTURE §11 tripwires.)
> - Renders both a normal run and a compare matrix.
> - The failure view is the priority: full trajectory, tool arguments, assertion messages, judge reasoning where present. This is where HTML genuinely beats the terminal — expandable turn-by-turn detail that would flood a console.
> - Generated from the v0.2 JSON artifact, so `dryfire report run.json` works offline on a previously-recorded run.
> - Under 500KB for a 50-case run.
> - Legible with CSS disabled — semantic HTML first, styling second.
>
> **Files.** `adapters/driven/reporting/html_sink.py` · `adapters/driven/reporting/templates/report.html` · `adapters/driving/cli/report.py` · `tests/unit/adapters/test_html_sink.py`.
>
> **Acceptance criteria.**
> - [ ] Single file, opens from `file://` with network disabled — verified.
> - [ ] Renders both a run and a compare matrix.
> - [ ] Turn-by-turn detail expandable per case.
> - [ ] `dryfire report run.json` regenerates from a JSON artifact with no re-execution.
> - [ ] Under 500KB for 50 cases.
> - [ ] No loop, scheduler, or existing-reporter changes — `git diff` proves it.
> - [ ] Structurally valid HTML; readable with CSS disabled.

---

### DF-310 — Docs and v0.3.0 release
**Depends on:** all above

**Prompt:**
> **Context.** Final ticket. v0.3 adds capabilities that can undermine the project's core
> claim if presented carelessly. The docs must be honest about the trade-offs rather than
> selling three features.
>
> **Task.** Document, changelog, release v0.3.0.
>
> **Constraints.**
> - `docs/judging.md` must state plainly: judged assertions cost money, vary between runs, and **should not gate a merge without cassettes**. Then explain judge drift — pinned model versions, rubric hashing, and why a score is not comparable to a score produced under a different rubric hash. This is the most valuable page in the docs and most tools do not have it.
> - `docs/flakiness.md` covering `repeat`, what a pass rate means, and the minimum-N guidance from SPIKE-007.
> - `docs/compare.md` with a real screenshot of the matrix.
> - **README structure must not change its centre of gravity.** The headline stays deterministic structural testing in CI. Judging and comparison are additive capabilities, presented below it. If the README now leads with LLM-as-judge, the project has drifted into the crowded part of the market it was designed to avoid.
> - `COMPARISON.md` re-verified against Promptfoo and DeepEval, with the check date recorded. Both are mature on judging and comparison; **say so.** v0.3 narrows a gap, it does not close one.
> - Benchmark published: structural-only suite runtime and cost, v0.2 vs v0.3, proving success criterion 2.
> - Semver v0.3.0. Spec format backward compatible with v0.1 and v0.2.
>
> **Files.** `docs/judging.md` · `docs/flakiness.md` · `docs/compare.md` · `README.md` · `COMPARISON.md` · `CHANGELOG.md`.
>
> **Acceptance criteria.**
> - [ ] v0.1 and v0.2 suite files run unchanged on v0.3 — CI backward-compatibility test.
> - [ ] `docs/judging.md` covers cost, variance, merge-gate guidance, and judge drift.
> - [ ] README still leads with deterministic structural testing.
> - [ ] Published benchmark shows no regression on structural-only suites.
> - [ ] Comparison tables re-verified, check date recorded, competitor strengths stated.
> - [ ] `uvx dryfire@0.3.0 init` works from a clean machine.

---

## 9. Notes for whoever runs this epic

- **SPIKE-006 is the architectural decision of the epic.** Everything from DF-301 to DF-304 assumes its verdict. Do not start them before it lands, and if its answer requires amending ARCHITECTURE §4.3, amend the document rather than making a silent exception in code.
- **DF-306 has a silent failure mode worth fearing.** If repeated cases replay one response N times, every pass rate becomes `N/N` and the entire `repeat` feature reports a comforting lie. That specific test is the most important one in the epic.
- **DF-304's regression test is the point of DF-304.** `cost_under` must not see judge cost. Without that test the ticket is decorative.
- **Watch the centre of gravity in DF-310.** Judging and comparison are where Promptfoo and DeepEval are strongest and most mature. If the README starts leading with them, you have repositioned the project into a fight it cannot win, and given up the one thing neither competitor has.

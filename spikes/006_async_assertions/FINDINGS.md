# SPIKE-006 — Async assertion execution model

**Type:** streamlined decision spike · **Depends on:** none · **Status:** complete
**Date:** 2026-08-02

## Verdict

**Model C — judge as a pre-assertion enrichment stage.** Pure assertions stay pure
and sync. A judged assertion reads a `JudgeVerdict` that an **async enrichment stage
in the application layer** has already attached to the trace, then applies a
threshold. The enrichment stage is the only place model I/O happens; it mirrors the
existing `price(trace, case)` seam in `composition._make_price` almost exactly,
differing only in that it is `await`ed and closes over a gateway plus a shared judge
concurrency semaphore.

The recommendation is not close. Models A and B both pay their cost across the *whole*
assertion surface — six pure assertions and their tests — to serve one judged
assertion. Model C localises the entire cost to a single new seam and leaves every
existing assertion, and `application/loop.py`, byte-for-byte unchanged.

Reference implementation: `seam.py` (+ `test_seam.py`, 8 passing). It exercises the
real `ModelGateway` port, the real frozen `Trace`, and the real `AssertionResult` —
not toys. Contract 3, contract 5, ruff, and all 5 import-linter contracts stay green
with the seam present.

## Why not A or B

| Model | What it is | What it costs |
|---|---|---|
| **A** — two-phase declare/execute | Domain assertions declare *requests*; the app executes them and feeds verdicts back into pure threshold assertions | A second protocol method (`declare()` alongside `evaluate()`), or a `JudgeRequest` domain type every assertion must know to ignore. Machinery imposed on all six pure assertions to serve one. |
| **B** — all assertions async | `evaluate()` becomes `async`; pure assertions simply never await | The async signature infects `safe_evaluate`, the registry `build`, `_evaluate`, and every assertion test — an `await` on six assertions that do no I/O. Async in the domain reads as a smell even though it does not *by itself* break contract 3. Largest blast radius. |
| **C** — enrichment stage ✅ | App layer runs judges after the loop, attaches `JudgeVerdict`s to the trace; assertions stay pure and read a populated field | One new async callback threaded through the scheduler + composition, plus a new pure `JudgeVerdict` type and a new optional `Trace` field. Zero change to existing assertions or the loop. |

Model C's cost is real but **bounded and precedented**: it is the same shape as
DF-207, which added the `price` seam so `cost_under` could read a cost the loop does
not compute. "Adding an assertion that needs data the loop doesn't produce" already
has a sanctioned pattern in this codebase, and Model C reuses it.

## Answers to the required questions

**Q1 — Which model, and what do the others cost?**
Model C. A and B both spread their cost across all six existing assertions (a second
protocol method / a mandatory async signature) to serve the one judged assertion. See
the table above.

**Q2 — Does it change the `Assertion` protocol? Does it break the two-file rule?**
The protocol is **unchanged**: `evaluate(trace) -> AssertionResult`, still pure, still
sync. The judged assertion reads `trace.judge_verdicts[...]`.

The two-file rule (SPEC §6.3: adding an assertion = one new file + one registry line)
holds *for the assertion mechanics* — `domain/assertions/judge.py` + one registry
import. But `llm_judge` is the first assertion that needs data the loop doesn't
produce, so the *feature* also lands the enrichment seam:
`domain/judging/{verdict,rubric}.py`, a `Trace.judge_verdicts` field, an
`application/judging/evaluator.py`, and the scheduler/composition wiring.

**This is a one-time sanctioned seam, decided here — not a PR-time confession**
(resolving the concern DF-303 left open). It is precisely analogous to DF-207: adding
`cost_under` was also "more than two files" because it first had to build the `price`
seam. Once the judging seam exists, a *second* judge-style assertion would again be
just two files. **Recommendation:** state this in the DF-303 PR as expected and
covered by this spike, and record the seam in ARCHITECTURE (amendment below) so it is
documented, not silent.

**Q3 — Where does a judge failure surface?**
As a **distinct state that maps to exit 3 (provider error)** — not a failed assertion
(exit 1) and not a score of 0. Rationale: a judge is provider I/O; when it errors
(timeout, 429, unparseable response), the agent under test did nothing wrong, so
reporting "assertion failed" would send the user to debug the wrong thing — the exact
failure mode DF-304 guards against for cost. An unparseable response is likewise a
judge *error*, never a 0 (scoring 0 on a judge bug silently fails good cases).

Mechanically: the enrichment stage records a `JudgeVerdict` with a populated `error`
field; the pure assertion surfaces it with a `JUDGE_ERROR:` marker in its message; the
exit-code computation treats a case carrying a judge error like a `provider_error`
termination. **No new exit code** — exit codes are contractual and 0/1/2/3 already has
the right bucket. (`test_judge_error_is_distinct_from_score_zero` pins this.)

**Q4 — Can judge calls be batched across cases? Implications for the scheduler?**
Yes, and they should be. Two levels of concurrency, one shared bound:
- **Within a case:** the enrichment stage `gather`s all of a case's judged
  assertions concurrently (flat gather, not a nested pool).
- **Across cases:** cases already run concurrently under the scheduler's worker pool,
  so their enrichment stages overlap naturally.
- **The bound:** a *single* `asyncio.Semaphore`, created once in the composition-level
  `_make_judge()` and closed over by the enricher, caps judge calls **globally** and
  **independently of case concurrency** (DF-302). A 50-case run with 3 judged
  assertions each never opens 150 connections; it opens `judge_concurrency` at most.
  (`test_judge_concurrency_is_bounded_globally_across_cases` pins this: 9 calls across
  3 cases, bound 2, max-in-flight exactly 2.)

Scheduler implication: **one** new optional parameter (`enrich: JudgeEnrich | None`)
and **one** new line in `_process_case` between `price(...)` and `_evaluate(...)`.
That is the whole change. The shared semaphore lives in the injected enricher, so the
scheduler gains no concurrency knowledge of its own.

**Q5 — Does `Trace` need a new field? Does it affect the v0.2 JSON schema version?**
Yes: `Trace` gains `judge_verdicts: dict[str, JudgeVerdict] = {}` (DF-301), plus
`judge_usage`/`judge_cost` as a separate channel (DF-304). All are **additive and
optional with empty/None defaults**, so:
- A structural-only trace serialises byte-identically to v0.2 (empty dict / no keys).
- A v0.2 consumer reading a v0.3 artifact ignores the new keys; a v0.3 consumer
  reading a v0.2 artifact sees the defaults.

`SCHEMA_VERSION` is currently `1`. The change is backward-compatible, so it is **not**
a breaking bump. Recommendation: **bump `SCHEMA_VERSION` to `2`** anyway, purely as a
*capability signal* so a reader (notably the DF-309 HTML report) can detect a
judge-aware artifact without probing for keys. Keep the reader tolerant of `1`. This
is a minor, additive bump — not a format break — and the v0.1/v0.2 backward-compat CI
test (DF-310) must continue to pass.

## Amendment to ARCHITECTURE (§4.4, new)

§5.1 deferred `llm_judge` with *"do not design it in now, but do not make it
impossible either."* This spike closes that deferral. **Landed as a new §4.4 "The
judging enrichment seam"** (the substance below; the committed wording is tightened):

> **The judging enrichment seam.** Structural assertions are pure: `Trace` in,
> `AssertionResult` out, no I/O (§4.3 unchanged). One class of assertion —
> `llm_judge` — needs a value the loop does not compute (a model-graded verdict). It
> obtains it the same way `cost_under` obtains cost (DF-207): the application layer
> attaches the value to the trace *before* assertions run, via an injected callback.
> For judging the callback is **async** and gateway-backed (`JudgeEnricher`), sitting
> in `_process_case` immediately after `price(...)` and before assertion evaluation.
> The assertion itself stays pure and merely reads `Trace.judge_verdicts`. `domain/`
> acquires no I/O; contract 3 is untouched. `application/loop.py` is not in this call
> graph and does not change — this is **not** a second exception like the DF-211
> passthrough seam, because the enrichment happens outside the loop entirely.

## Acceptance criteria (streamlined scope)

- [x] Model C prototyped against the real `Trace` and a real-`ModelGateway` fake judge.
- [x] Contract-3 compliance verified — `lint-imports` reports 5 kept / 0 broken with the seam present.
- [x] Structural-only path shown to touch **zero** gateway calls (`test_structural_only_case_touches_no_gateway`) — measured, not assumed.
- [x] Batching / independent judge-concurrency bound demonstrated across cases.
- [x] Cassette interaction argued: judge calls route through the same `ModelGateway`, so wrapping it in `CachingGateway` cassette-backs them for free; the fingerprint already includes the model, so a judge model ≠ case model is a distinct cassette entry. (Full replay test belongs to DF-302, which has the real gateway wiring.)
- [x] `evaluate()` protocol unchanged; two-file rule resolved up-front (Q2), not deferred to PR.

## Handoff to DF-301

Build order is unchanged from the epic. DF-301 lands the pure types this seam assumes:
`domain/judging/verdict.py` (`JudgeVerdict` with **required** `judge_model_version` +
`rubric_hash`), `domain/judging/rubric.py` (rubric hashing via
`domain/fingerprint.py`'s canonicaliser), and the `Trace.judge_verdicts` field +
`SCHEMA_VERSION` → 2. DF-302 then implements the real `JudgeEnricher` in
`application/judging/` and wires it in composition beside `_make_price`.

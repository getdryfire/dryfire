# EPIC-002 — dryfire v0.2: CI-grade

**Spec:** `SPEC.md` §9 (v0.2) · **Architecture:** `ARCHITECTURE.md`
**Depends on:** EPIC-001 shipped to PyPI
**Status:** Ready for spikes

> **Naming.** The project is now `dryfire`. EPIC-001 tickets keep their `AC-` prefix because
> they are in flight — renumbering running work costs more than the inconsistency. EPIC-002
> onward uses `DF-`. Every path in this document uses the hexagonal layout from
> ARCHITECTURE §2, not SPEC §8.

---

## 1. Epic goal

Make dryfire something a team can put in a merge gate: a second provider, deterministic
offline replay, retries, budget assertions, JUnit output, and a one-line GitHub Action.

v0.1 proved the idea works. v0.2 makes it survive contact with CI.

## 2. Success criteria

1. **`application/loop.py` is unchanged by this entire epic.** Not "barely changed" —
   unchanged. Cassettes and retries both land as decorators over `ModelGateway`. If the loop
   needs editing, the port boundary is in the wrong place and that is a stop-and-flag event.
2. The OpenAI gateway passes the **same** `ModelGateway` contract suite as Anthropic and
   `FakeGateway`, with no new methods on the port.
3. `dryfire run --cassette-mode replay` executes a full suite with **no network access and
   no API key**, in an airgapped container.
4. A cassette miss in `replay` mode exits 3 and names the missing fingerprint and case.
   Never a silent live call.
5. JUnit XML output renders correctly in GitHub Actions test reporting **and** one other CI
   system.
6. A user adds dryfire to their CI in one workflow step, copy-pasted from the README.
7. Full offline test suite still passes with no API key.

## 3. In scope

SPEC §9 (v0.2): OpenAI adapter · cassettes · retries · budget and extra assertions · JUnit
reporter · GitHub Action · passthrough mocks.

## 4. Out of scope

`llm_judge`, `compare`, HTML report, `repeat`/flakiness (all v0.3) · code export (v0.4) ·
streaming · web UI · any server, database, or hosted anything · more than two providers.

Two providers is the design budget for v0.2. A third is a v0.3 conversation, and each new
one must pass the contract suite unchanged.

## 5. Sequencing

```
  SPIKE-004 (passthrough) ─────────────┐
  SPIKE-005 (junit mapping) ───────┐   │
                                   │   │
  DF-201 (openai gateway) ─────┐   │   │
  DF-202 (fingerprint) ────┐   │   │   │
                           ↓   │   │   │
  DF-203 (cassette store) ─┤   │   │   │
                           ↓   │   │   │
  DF-206 (retry decorator) │   │   │   │
                           ↓   │   │   │
  DF-204 (caching gateway) ┴───┤   │   │
                               ↓   │   │
  DF-205 (prune) ──────────────┤   │   │
  DF-207 (budget asserts) ─────┤   │   │
  DF-208 (extra asserts) ──────┤   │   │
  DF-209 (junit sink) ─────────┴───┘   │
  DF-211 (passthrough mocks) ──────────┘
                               ↓
  DF-210 (github action) → DF-212 (docs + release)
```

DF-202 and DF-201 are independent and can run in parallel. Everything converges on DF-210.

---

## 6. The one architectural idea in this epic

**Both new behaviours are decorators over `ModelGateway`.** Nothing else in the system
learns that caching or retrying exists.

```python
gateway = AnthropicGateway(...)          # or OpenAIGateway
gateway = RetryingGateway(gateway, max_retries=3)
gateway = CachingGateway(gateway, store, mode)
```

**Order is load-bearing and is not a preference.** Caching must be *outermost*: a cache hit
must return without ever reaching the retry layer, and retries must apply only to live
calls. Inverting this makes cached runs retry against a cache, which is meaningless, and
makes a recorded response include retry state, which is wrong.

Wiring lives in `composition.py` and nowhere else. If a `if cassettes_enabled` appears in
the loop, the scheduler, or a use case, that is the failure mode this epic exists to avoid.

---

## 7. Spike tickets

### SPIKE-004 — Passthrough mock execution model
**Type:** spike   **Time-box:** half day   **Depends on:** none

**Prompt:**
> **Context.** `dryfire` runs agent test suites with declaratively mocked tools. v0.2 adds
> `passthrough` mocks: instead of a canned return, a mock names a real Python callable as
> `impl: package.module:function`, which dryfire imports and calls with the tool arguments
> (`SPEC.md` §4.4). This means executing arbitrary user code found in a YAML file, inside a
> concurrent async runner, and it has open questions in three directions — import
> resolution, execution model, and security posture — that will be expensive to change once
> users depend on the behaviour.
>
> **Task.** Determine the execution model and write a working prototype resolver + invoker.
>
> **Constraints.** No sandboxing — this is the user's own code in the user's own repo and
> pretending otherwise gives false assurance. Must work when the callable is sync **or**
> async. Must not deadlock the async scheduler. Assume cases run concurrently at default
> concurrency 4.
>
> **Files.** `spikes/004_passthrough/` with `resolver.py`, `invoke.py`, `sample_impls.py`, `FINDINGS.md`.
>
> **Acceptance criteria.**
> - [ ] Resolves `pkg.mod:func` where `pkg` is on `sys.path`, in the CWD, and in an editable-installed local package.
> - [ ] Invokes a sync callable without blocking the event loop (prove it: run 4 concurrently, each sleeping 200ms, assert wall-clock under 400ms).
> - [ ] Invokes an async callable natively.
> - [ ] A callable that raises becomes a `ToolResult(is_error=True)` carrying the exception message; the run continues.
> - [ ] A callable that hangs is bounded by a timeout and produces an error result.
> - [ ] Import failure is reported as a **spec error at validate time**, not a runtime crash mid-run.
>
> **Questions FINDINGS.md must answer.**
> 1. Sync callables: thread executor, or require the user to make them async? State the trade-off and pick.
> 2. Can import resolution happen at `validate` time so `dryfire validate` catches a bad `impl:` before any API spend? Any case where it cannot?
> 3. What is the timeout default, and is it per-call or per-case?
> 4. Is a passthrough result cacheable? **Argue no** — a real callable can have side effects and non-deterministic output, so recording it into a cassette makes replay a lie. Confirm or refute with a concrete example.
> 5. What must the docs say about the security posture, in one paragraph a user will actually read?
>
> **Out of scope.** Sandboxing, subprocess isolation, permission models.
>
> **Deliverable.** `FINDINGS.md` with a **Verdict** giving the execution model and a reference `invoke()` that DF-211 adapts.

---

### SPIKE-005 — JUnit XML mapping across CI consumers
**Type:** spike   **Time-box:** half day   **Depends on:** none

**Prompt:**
> **Context.** v0.2 emits JUnit XML so CI systems render results natively. JUnit XML is a
> de-facto format with no real standard, and consumers disagree on how they interpret it. A
> mismapping produces output that is technically valid and practically useless — which is
> worse than no reporter at all, because users will trust it.
>
> dryfire's domain has three levels (suite → case → assertion) and JUnit has two
> (testsuite → testcase). That mismatch is the whole question.
>
> **Task.** Determine the mapping empirically by feeding candidate XML to real consumers.
>
> **Constraints.** Test against at least **three**: GitHub Actions test reporting (via a
> published action such as `dorny/test-reporter`), GitLab CI, and `pytest`'s own JUnit
> consumer or Jenkins. Judge on rendered output, not schema validity.
>
> **Files.** `spikes/005_junit/` with `candidates/` (3+ XML files), `render_notes.md` (screenshots or transcribed output per consumer), `FINDINGS.md`.
>
> **Acceptance criteria.**
> - [ ] Three candidate mappings produced: (A) case = testcase, assertions concatenated into one failure body; (B) assertion = testcase, case = testsuite; (C) case = testcase with one `<failure>` per failed assertion.
> - [ ] Each fed to three consumers, with the rendered result recorded.
> - [ ] A verdict on which mapping makes a failing `not_calls_tool` **most legible in a PR check**, since that is the moment that matters.
> - [ ] Confirmed behaviour for: the trajectory line's arrows and newlines surviving XML escaping; a case that errored rather than failed; a zero-case run.
>
> **Questions FINDINGS.md must answer.**
> 1. Which mapping, and what specifically did the other two lose?
> 2. Does any consumer truncate the failure body? At what length? Does the trajectory line survive?
> 3. `<error>` vs `<failure>`: which for `provider_error` and `unmocked_tool` terminations?
> 4. Are `time`, `classname`, or `file` attributes needed for grouping to work anywhere?
> 5. Does any consumer choke on the `→` character or require ASCII?
>
> **Out of scope.** Implementing the sink (DF-209).
>
> **Deliverable.** `FINDINGS.md` with a **Verdict** naming the mapping plus a reference XML document DF-209 matches against.

---

## 8. Feature tickets

### DF-201 — OpenAI gateway adapter
**Depends on:** EPIC-001 (AC-007)   **Spec:** §3.1, §3.3

**Prompt:**
> **Context.** SPIKE-001 built and structurally verified an OpenAI adapter —
> `spikes/001_provider_normalization/adapters.py::OpenAIAdapter` is your reference, and its
> `FINDINGS.md` is required reading. This ticket is the real test of the whole hexagonal
> bet: **if the `ModelGateway` port is correct, adding a second provider changes nothing
> above the port.**
>
> **Task.** Implement `OpenAIGateway` in `adapters/driven/providers/openai.py`.
>
> **Constraints.**
> - **`application/loop.py` must not change.** Not one line. If it needs to, stop and flag it — that is SPIKE-001 having failed, and the fix is the port, not the loop.
> - No new methods on `ModelGateway`. No `isinstance` checks anywhere.
> - Tool results are **separate messages** with `role: "tool"` — N parallel results become N messages, unlike Anthropic's one message with N blocks.
> - `function.arguments` is a **JSON string** and can be truncated. Parse defensively: on failure set `arguments={}` and populate `malformed_arguments`. Never raise.
> - `is_error` has **no OpenAI equivalent**. Encode it into result content via a named constant `OPENAI_ERROR_PREFIX` (ARCHITECTURE / SPEC §3.1 obligation 5). Do not invent a field.
> - Stop reasons per SPEC §3.3. `content_filter` → `refusal`, documented as non-equivalent.
> - Register any new tool-call id key name in `_CALL_ID_KEYS` (SPEC §3.1 obligation 2). OpenAI uses `tool_call_id`; verify nothing else appears.
> - `openai` stays an optional extra. Missing SDK → actionable message naming the install command.
>
> **Files.** `adapters/driven/providers/openai.py` · `tests/unit/adapters/test_openai_gateway.py` · `tests/fixtures/openai/*.json` · `tests/integration/test_openai_live.py` (`@pytest.mark.live`).
>
> **Acceptance criteria.**
> - [ ] Passes the existing `ModelGateway` contract suite **unmodified**.
> - [ ] `git diff` on `application/` is empty for this ticket. State this explicitly in the PR.
> - [ ] Recorded-payload tests: single call · two parallel calls · text only · `length` truncation · error result · **malformed arguments**.
> - [ ] Malformed arguments yield `arguments={}` + `malformed_arguments` set, no exception.
> - [ ] N parallel results produce N `role: "tool"` messages in call order.
> - [ ] Unknown `finish_reason` → `"error"`, no raise.
> - [ ] `@pytest.mark.live` two-turn tool-calling exchange, skipped without `OPENAI_API_KEY`.
> - [ ] `provider: openai` in a suite runs end to end against recorded fixtures.
>
> **Out of scope.** Cassettes, retries, more providers.

---

### DF-202 — Request fingerprinting
**Depends on:** SPIKE-002 (done)   **Spec:** §9 (v0.2)

**Prompt:**
> **Context.** SPIKE-002 produced a verified implementation with 19 passing tests. **Lift
> `spikes/002_cassette_fingerprint/fingerprint.py` essentially verbatim** and port
> `test_stability.py` unchanged. Read that spike's `FINDINGS.md` first — the tool-call id
> normalisation is not an optimisation, it is the difference between cassettes working and
> silently missing on every turn after the first.
>
> **Task.** Port the fingerprint module into the package.
>
> **Constraints.**
> - Canonical JSON: sorted keys, no whitespace, NFC-normalised strings, `allow_nan=False`, int and float **not** unified.
> - Hash tool `name` + `description` + `input_schema`, **in list order**. Description is prompt text; excluding it is the false-stable failure mode.
> - Normalise tool-call ids to positional placeholders — **hash path only**. The wire path keeps ids verbatim.
> - `_CALL_ID_KEYS` is vendor-coupled. Comment it as such and reference the adapter obligation.
> - `SCHEMA_VERSION` is inside the hash input, so bumping it invalidates everything by construction. No migration code, ever.
> - This module is **pure** and belongs under `domain/` — no I/O, no filesystem.
>
> **Files.** `domain/fingerprint.py` · `tests/unit/domain/test_fingerprint.py`.
>
> **Acceptance criteria.**
> - [ ] All 19 spike tests ported and passing.
> - [ ] Deterministic across processes under `PYTHONHASHSEED=random` — assert in a subprocess.
> - [ ] Import-linter contract 3 still passes (domain imports only pydantic + stdlib).
> - [ ] Fingerprint of a real 3-turn Anthropic conversation is stable across two constructions with different call ids.
>
> **Out of scope.** Storage, the caching decorator.

---

### DF-203 — File cassette store
**Depends on:** DF-202   **Spec:** §9 (v0.2)

**Prompt:**
> **Context.** `ResponseCache` is a driven port already declared in `application/ports/`.
> This ticket is its file-backed implementation. SPIKE-002's `FINDINGS.md` §3 specifies the
> on-disk layout and body format — follow it exactly; the layout was chosen so a reviewer
> reading a git diff can tell which case and turn a cassette belongs to.
>
> **Task.** Implement `FileCassetteStore`.
>
> **Constraints.**
> - Layout: `.dryfire/cassettes/<suite>/<case>/<NN>-<fingerprint>.json`, `NN` = turn index.
> - Body per SPIKE-002: `schema_version`, `fingerprint`, suite, case, turn, provider, model, `recorded_at`, a pretty-printed `request_digest`, and the raw `response`. The digest and timestamp are for humans and are **not** hashed.
> - **Atomic writes** (temp file + rename). A killed run must never leave a truncated cassette — these get committed to git.
> - Concurrent cases may write simultaneously. Last-write-wins is acceptable; a partial file is not.
> - Suite and case names must be **path-sanitised** (slashes, colons, spaces, unicode) without collapsing two distinct names to one path.
> - Reads are keyed by fingerprint alone. The directory structure is for humans; correctness never depends on it.
> - A cassette whose `schema_version` differs from current is treated as a **miss**, not an error.
>
> **Files.** `adapters/driven/cache/file_store.py` · `tests/unit/adapters/test_cassette_store.py` · `tests/contracts/test_response_cache_contract.py`.
>
> **Acceptance criteria.**
> - [ ] Contract test suite for `ResponseCache`, run against `FileCassetteStore` and an `InMemoryCache` fake.
> - [ ] Round-trip: put then get returns an equal `ModelResponse`.
> - [ ] Interrupting a write leaves either no file or a complete one — test by patching rename to fail.
> - [ ] Two distinct case names that sanitise similarly do not collide.
> - [ ] Mismatched `schema_version` reads as a miss.
> - [ ] Committed cassettes are readable, stable-key JSON — a golden file proves the diff stays small when only the response changes.
>
> **Out of scope.** Mode logic, the decorator, `prune`.

---

### DF-204 — CachingGateway decorator
**Depends on:** DF-203, DF-206   **Spec:** §9 (v0.2)

**Prompt:**
> **Context.** This is the ticket that proves the architecture. Cassettes must land as a
> **decorator over `ModelGateway`** with zero changes to `application/loop.py`. Read
> `ARCHITECTURE.md` §6 and §8.
>
> **Task.** Implement `CachingGateway` and wire the four modes in `composition.py`.
>
> **Constraints.**
> - Implements `ModelGateway`, wraps another `ModelGateway`. That is the entire integration surface.
> - **Composition order is fixed:** `Caching(Retrying(Real))`. A cache hit must never reach the retry layer, and retries apply only to live calls. Do not make this configurable.
> - Modes: `auto` (miss → live + record) · `record` (always live, overwrite) · `replay` (**miss → exit code 3**, naming the missing fingerprint and case; never a live call) · `off` (bypass entirely).
> - Emits `ModelResponded` with `cache_hit` set so reporters can show it. This is the event model earning its place.
> - `replay` mode must be provable airgapped: no socket is opened, verified by a patched transport that raises on any connection attempt.
> - Cache key is the fingerprint alone. The decorator never inspects request semantics.
>
> **Files.** `adapters/driven/providers/caching.py` · `composition.py` · `tests/unit/adapters/test_caching_gateway.py` · `tests/acceptance/test_replay_offline.py`.
>
> **Acceptance criteria.**
> - [ ] **`git diff application/loop.py` is empty for this ticket.** State it in the PR.
> - [ ] Passes the `ModelGateway` contract suite while wrapping `FakeGateway`.
> - [ ] One test per mode.
> - [ ] `replay` with a missing cassette exits 3 with a message naming fingerprint **and** case.
> - [ ] Acceptance test: record a full suite, then replay it with a transport patched to raise on connect — passes.
> - [ ] A multi-turn case replays correctly on turns 2+ (the SPIKE-002 failure mode; regression test).
> - [ ] Cache hits are visible in terminal output.
>
> **Out of scope.** `prune`, retry logic.

---

### DF-205 — `prune` command
**Depends on:** DF-204

**Prompt:**
> **Context.** Cassette paths embed suite and case names, so renaming either orphans its
> cassettes (SPIKE-002 §3, an accepted trade-off). `prune` is the mitigation.
>
> **Task.** Implement `dryfire prune`.
>
> **Constraints.** Dry-run by default; `--yes` to delete. Prints what it would remove and why (orphaned suite / orphaned case / stale `schema_version`). Never deletes a cassette whose suite failed to load — a broken spec must not cause data loss. Exits 0 whether or not anything was pruned.
>
> **Files.** `adapters/driving/cli/prune.py` · `tests/integration/test_prune.py`.
>
> **Acceptance criteria.**
> - [ ] Default run deletes nothing and lists candidates with reasons.
> - [ ] `--yes` deletes only listed candidates.
> - [ ] A cassette belonging to a suite that fails to parse is **never** pruned.
> - [ ] Stale `schema_version` cassettes are identified.
> - [ ] Empty directories are cleaned up after pruning.

---

### DF-206 — RetryingGateway decorator
**Depends on:** DF-201   **Spec:** §9 (v0.2)

**Prompt:**
> **Context.** Transient 429s and 5xx currently fail a case outright. Retries belong in a
> decorator, for the same reason caching does: the loop must not learn about them.
>
> **Task.** Implement `RetryingGateway`.
>
> **Constraints.**
> - **Retries are not turns.** `Trace.turns` must be unaffected by retry count — this is a SPEC §5 invariant and needs an explicit test.
> - Exponential backoff with jitter. `--max-retries`, default 3.
> - Retry only on: 429, 5xx, connection errors, timeouts. **Never** on 4xx-other, auth failures, or malformed-request errors — retrying those burns time and hides a real bug.
> - Honour `Retry-After` when the provider sends it.
> - Retry classification is per-provider and lives in the **gateway adapter**, not the decorator. The decorator asks `is_retryable(exc)`; the adapter answers. Otherwise the decorator grows vendor knowledge.
> - Exhausted retries → the original exception propagates, and the loop records `provider_error` as it already does.
> - Sleeps go through the `Clock` port so tests do not actually wait.
>
> **Files.** `adapters/driven/providers/retrying.py` · `application/ports/model_gateway.py` (add `is_retryable`) · `tests/unit/adapters/test_retrying_gateway.py`.
>
> **Acceptance criteria.**
> - [ ] A 429 then success → one turn in the trace, not two.
> - [ ] A 401 is not retried.
> - [ ] Backoff delays follow the expected sequence under `FrozenClock`; the test runs in milliseconds.
> - [ ] `Retry-After` is honoured when present.
> - [ ] Exhausted retries → `provider_error` termination, run continues to the next case.
> - [ ] Passes the `ModelGateway` contract suite wrapping `FakeGateway`.
> - [ ] `git diff application/loop.py` empty.

---

### DF-207 — Budget assertions
**Depends on:** EPIC-001 (AC-010, AC-017)   **Spec:** §6.2

**Prompt:**
> **Context.** `cost_under` and `latency_under_ms` let a suite fail when a prompt change
> makes an agent chattier or more expensive. AC-017 already computes cost and returns `None`
> for unknown models — that `None` is the interesting case here.
>
> **Task.** Implement both assertions in `domain/assertions/budget.py`.
>
> **Constraints.**
> - **`cost_under` against an unknown model (`cost is None`) must not silently pass.** A green check that proves nothing is worse than a red one. Fail with a message stating that pricing is unavailable for the model, and name it.
> - Cost is advisory (SPEC §3.2) — say so in the failure message so nobody debugs the wrong thing.
> - `latency_under_ms` measures model latency summed across turns, **excluding** mock resolution and retry backoff. Naming this precisely in the message matters; users will otherwise assume wall-clock.
> - Adding these must touch exactly two files (SPEC §6.3). Zero changes to the loop or reporters.
> - Under cassette replay, latency is the **recorded** latency, not replay time. Document this — a replayed run is not a latency measurement.
>
> **Files.** `domain/assertions/budget.py` · registry entry · `tests/unit/domain/test_budget_assertions.py`.
>
> **Acceptance criteria.**
> - [ ] Pass and fail case for each.
> - [ ] Unknown-model cost **fails** with an explicit pricing-unavailable message.
> - [ ] Failure messages show actual vs limit and include the trajectory line.
> - [ ] Latency excludes retry backoff — test with a scripted retry.
> - [ ] Two-file rule verified.

---

### DF-208 — Extended structural assertions
**Depends on:** EPIC-001 (AC-011)   **Spec:** §6.2

**Prompt:**
> **Context.** Three more assertions from SPEC §6.2: `min_tool_calls`, `final_matches`
> (regex), `final_json_schema`. AC-011's shared trajectory renderer and failure format apply
> unchanged — reuse, do not reimplement.
>
> **Task.** Implement all three.
>
> **Constraints.**
> - `min_tool_calls: {tool, count}` — at least N calls. This is the retry-recovery assertion from SPEC §4.3's worked example, so it must work against a `sequence` mock.
> - `final_matches` compiles the regex **at spec-validation time**; an invalid pattern is a spec error with a position, not a runtime failure.
> - `final_json_schema` validates `final_text` parsed as JSON against a supplied schema. Unparseable JSON and schema-violating JSON are **different failure messages** — the user needs to know which.
> - Regex matching must be bounded against catastrophic backtracking. Cap execution and fail with a clear message rather than hanging CI.
> - Every failure message includes the trajectory line.
>
> **Files.** `domain/assertions/structural.py` (extend) · `tests/unit/domain/test_extended_assertions.py`.
>
> **Acceptance criteria.**
> - [ ] Pass and fail case for each.
> - [ ] `min_tool_calls` passes against SPEC §4.3's `recovers_from_tool_error` case end to end.
> - [ ] An invalid regex is a **spec error at validate time** with line/col.
> - [ ] Unparseable JSON and invalid-per-schema JSON produce distinguishable messages.
> - [ ] A catastrophic-backtracking pattern fails within a bounded time instead of hanging.

---

### DF-209 — JUnit XML sink
**Depends on:** SPIKE-005   **Spec:** §9 (v0.2)

**Prompt:**
> **Context.** SPIKE-005 determined the mapping empirically against three CI consumers. Its
> `FINDINGS.md` verdict and reference XML are authoritative — implement that, not your own
> reading of the format. Reporters are `EventSink`s (ARCHITECTURE §6), so this is a new sink,
> not a change to anything existing.
>
> **Task.** Implement `JUnitSink`.
>
> **Constraints.**
> - Match SPIKE-005's reference XML exactly, including the `<error>` vs `<failure>` decision for `provider_error` and `unmocked_tool`.
> - The trajectory line must survive XML escaping and render legibly in a PR check. If SPIKE-005 found a consumer that mangles `→`, use its recommended fallback.
> - Atomic write, same as DF-203.
> - Registered as a sink; **no changes to the loop, scheduler, or terminal reporter**.
> - Emitting JUnit must compose with `--json-out` and terminal output in one run.
>
> **Files.** `adapters/driven/reporting/junit_sink.py` · `tests/unit/adapters/test_junit_sink.py` · `tests/fixtures/expected_junit/*.xml`.
>
> **Acceptance criteria.**
> - [ ] Output matches SPIKE-005's reference XML byte-for-byte for the same input.
> - [ ] Validates against a JUnit XSD.
> - [ ] Golden-file tests for: all-pass · one failure with three assertions · a `provider_error` case · a zero-case run.
> - [ ] Trajectory line survives escaping — assert on the parsed text content.
> - [ ] `--reporter junit --json-out x.json` produces both.
> - [ ] Manually verified rendering in a real GitHub Actions run; screenshot in the PR.

---

### DF-210 — GitHub Action
**Depends on:** DF-204, DF-209

**Prompt:**
> **Context.** Adoption depends on the CI step being one copy-pasteable block. This is the
> distribution ticket.
>
> **Task.** Ship a composite GitHub Action plus a documented workflow.
>
> **Constraints.**
> - **Composite action**, not Docker — Docker actions are slow to start and this must feel instant.
> - Inputs: `suites`, `cassette-mode` (default `replay`), `reporter`, `fail-fast`, `version`.
> - **Default to `replay`.** The headline value is a CI run that is free, offline, and deterministic. A default that spends money on every push would be a bad default.
> - Uploads the JUnit XML as an artifact and surfaces it as a check.
> - Fails the job on dryfire exit 1, 2, or 3, with the exit code visible in the log.
> - The README snippet must be under 10 lines and work unmodified in a fresh repo.
>
> **Files.** `action.yml` · `.github/workflows/example-usage.yml` · `docs/ci.md`.
>
> **Acceptance criteria.**
> - [ ] Verified in a **separate throwaway repository**, not this one.
> - [ ] Cold-start step time under 20s, measured and recorded.
> - [ ] Failing cases fail the job; JUnit renders in the PR check.
> - [ ] Works with no API key configured (replay mode) — this is the headline demo.
> - [ ] README snippet is under 10 lines and pasted verbatim from the tested workflow.

---

### DF-211 — Passthrough mocks
**Depends on:** SPIKE-004   **Spec:** §4.4

**Prompt:**
> **Context.** SPIKE-004 settled the execution model. Implement its verdict, including its
> conclusion on cacheability — do not re-derive it.
>
> **Task.** Implement `impl: pkg.mod:func` passthrough mocks.
>
> **Constraints.**
> - Follow SPIKE-004's verdict on sync-vs-async handling and timeouts exactly.
> - Import resolution happens at **validate time** — a bad `impl:` is a positioned spec error before any API spend.
> - A raising callable → `ToolResult(is_error=True)`; the run continues.
> - **Passthrough results are not cached** (SPIKE-004 Q4). A case using passthrough mocks must be excluded from cassette recording, with a visible note — a cassette containing side-effecting output makes replay a lie.
> - Resolution stays in the domain `MockResolver` only if it remains pure; if invocation needs I/O, the invoker is an adapter behind a port. Follow the layering, and if this forces a new port, say so rather than smuggling I/O into `domain/`.
> - Docs must carry SPIKE-004's security paragraph.
>
> **Files.** `domain/mocking/` and/or `adapters/driven/` per the layering decision · `application/ports/` if a port is added · `tests/unit/test_passthrough_mocks.py` · `docs/mocks.md`.
>
> **Acceptance criteria.**
> - [ ] Sync and async callables both work.
> - [ ] A bad `impl:` is caught by `dryfire validate` with line/col, zero network calls.
> - [ ] A raising callable produces an error result; the run continues.
> - [ ] Timeout produces an error result within the bound.
> - [ ] A passthrough case is excluded from cassette recording, with a visible note in output.
> - [ ] Four concurrent sync callables do not serialise — wall-clock assertion.
> - [ ] Security posture documented.

---

### DF-212 — Docs and v0.2.0 release
**Depends on:** all above

**Prompt:**
> **Context.** Final ticket. v0.2's story is "put this in your merge gate" — the docs must
> lead with that, not with a feature list.
>
> **Task.** Update docs, changelog, and release v0.2.0.
>
> **Constraints.**
> - README gains a CI section with the under-10-line workflow snippet, above the full feature list.
> - New page `docs/cassettes.md` explaining record/replay, what invalidates a cassette, and **why tool descriptions are part of the key** — that behaviour surprises people and an unexplained re-record erodes trust.
> - `docs/ci.md` covering exit codes, JUnit, and the Action.
> - `COMPARISON.md` re-verified against Promptfoo and DeepEval before publishing. Both move fast and both are ahead on breadth; **any row that has become false must be corrected, not quietly dropped.**
> - Changelog notes that OpenAI support landed with zero changes to the loop — it is the strongest available evidence the architecture is sound, and it is worth saying out loud.
> - Semver: v0.2.0. No breaking changes to the v0.1 spec format; if one was needed, it belongs in v1.0 and this epic is wrong.
>
> **Files.** `README.md` · `docs/cassettes.md` · `docs/ci.md` · `COMPARISON.md` · `CHANGELOG.md`.
>
> **Acceptance criteria.**
> - [ ] A v0.1 suite file runs unchanged on v0.2 — backward-compatibility test in CI.
> - [ ] CI snippet in the README is copied verbatim from the tested workflow.
> - [ ] `docs/cassettes.md` explains key composition and invalidation causes.
> - [ ] Comparison tables re-verified against both competitors' current docs, with the check date recorded.
> - [ ] `uvx dryfire@0.2.0 init` works from PyPI on a clean machine.
> - [ ] Changelog complete.

---

## 9. Notes for whoever runs this epic

- **DF-201 and DF-204 are the load-bearing tickets.** Both carry "`git diff application/loop.py` is empty" as an acceptance criterion. If either fails that, stop the epic and fix the port. Everything downstream compounds the mistake.
- **DF-207's unknown-model behaviour is a real decision, not a detail.** Failing when pricing is unavailable will annoy someone. Pass silently instead and their cost gate proves nothing while looking green. Fail loudly.
- **DF-210 must be tested in a throwaway repo.** An action that works in its own repository and nowhere else is the classic failure here.
- Both spikes are half-day and both answer questions that are expensive to change after users depend on the behaviour. Run them first.

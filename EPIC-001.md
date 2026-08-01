# EPIC-001 — dryfire v0.1: Local-first agent trajectory eval runner

**Spec:** `SPEC.md` §3–§8, §9 (v0.1)
**Status:** Spikes complete — see `SPIKE-REPORT.md`. Ready for AC-001.
**Target:** shippable to PyPI

---

## 1. Epic goal

Ship a CLI that runs YAML-defined agent test suites against Anthropic, executes the full
tool-calling loop with deterministic mocked tools, and asserts on the resulting trajectory —
with output good enough that a failure message alone tells you what the agent did wrong.

## 2. Success criteria

The epic is done when **all** of these are true:

1. `uvx dryfire init && cd . && dryfire run` produces a green run in under 60 seconds
   on a clean machine **with no API key set**.
2. The full test suite passes offline, with no network access and no API key.
3. All six v0.1 assertion kinds are implemented, registered, and individually tested.
4. A failing `not_calls_tool` prints the actual ordered tool-call sequence and the offending
   call's arguments (SPEC §6, required output format).
5. Exit codes 0/1/2/3 behave exactly as specified in SPEC §7.1, with a test per code.
6. `dryfire validate` catches every spec error class without making a network call.
7. Adding a hypothetical seventh assertion requires touching exactly two files.
8. Package published to PyPI; README shows a runnable example above the fold.

## 3. In scope

Anthropic provider only. Sections 3–8 of SPEC.md as marked v0.1.

## 4. Out of scope (explicitly deferred — do not build)

OpenAI adapter, cassettes, JUnit reporter, GitHub Action, retries/backoff, `llm_judge`,
`compare`, HTML report, `repeat`, code export, `passthrough` mocks, web UI, any server,
any database, streaming responses.

If a ticket seems to need one of these, it is wrong — stop and flag it rather than
building forward.

## 5. Sequencing

```
  SPIKE-001 ─┐
  SPIKE-002 ─┼─→ AC-001 → AC-002 → AC-003 → AC-004 → AC-005
  SPIKE-003 ─┘                 │        │
                               ↓        ↓
                            AC-006 (FakeProvider)
                               │
              ┌────────────────┼────────────────┐
              ↓                ↓                ↓
           AC-007          AC-008           AC-010
        (anthropic)        (mocks)      (assert framework)
              │                │                │
              └────────→ AC-009 (loop) ←────────┘
                               │                │
                               ↓                ↓
                            AC-012           AC-011
                         (scheduler)     (structural asserts)
                               │                │
                               └──→ AC-017 ─────┤
                                  (cost)        │
                                                ↓
                                    AC-013 → AC-014 → AC-015
                                  (terminal)  (json)   (CLI)
                                                        │
                                              AC-016 → AC-018 → AC-019
                                              (init)  (dogfood) (release)
```

**All three spikes must complete before AC-002.** They exist to retire architectural risk
that would otherwise force a rewrite.

---

## 6. Ticket-as-prompt format

Every ticket in this epic — and every future epic — uses this exact structure so it can be
pasted into Claude Code as a self-contained unit of work.

```markdown
### <ID> — <Title>
**Type:** spike | feature | chore   **Milestone:** v0.x
**Depends on:** <IDs or none>       **Time-box:** <spikes only>

**Prompt:**
> **Context.** <what exists already, what spec section governs this>
> **Task.** <the single thing to build>
> **Constraints.** <non-negotiables: no network, no new deps, protocol boundaries>
> **Files.** <exact paths to create or modify>
> **Acceptance criteria.** <checkbox list, each independently verifiable>
> **Out of scope.** <what NOT to touch>
> **Deliverable.** <artifact + how it's verified>
```

Rules for writing these prompts:

- Name **exact file paths**. Claude Code inventing a layout is the main failure mode.
- Every acceptance criterion must be checkable by running a command.
- Always include "Out of scope" — it is what prevents scope drift across a 19-ticket epic.
- Never say "and also add tests." State which tests, in which file, asserting what.

---

## 7. Spike tickets

> **All three executed.** Verdicts in `spikes/*/FINDINGS.md`, consolidated in
> `SPIKE-REPORT.md`. Six amendments applied to SPEC.md. One outstanding item: SPIKE-001's
> live probe run (needs API keys) must complete before AC-002 closes.


### SPIKE-001 — Provider normalization contract
**Type:** spike   **Milestone:** v0.1
**Depends on:** none   **Time-box:** 1 working day

**Prompt:**
> **Context.** We are building `dryfire`, a CLI that runs LLM agent tool-calling loops
> and asserts on the trajectory. `SPEC.md` §3 proposes provider-neutral types (`ToolDef`,
> `ToolCall`, `ToolResult`, `Message`, `ModelResponse`, `StopReason`) and a `Provider`
> protocol with a single `complete()` method. The entire architecture rests on this
> abstraction holding for both Anthropic and OpenAI. If it leaks, v0.2 forces a rewrite of
> the loop. Nothing has been implemented yet — this is a throwaway investigation in a
> `spikes/` directory.
>
> **Task.** Empirically validate or break the proposed normalization. Write two minimal
> adapters (Anthropic and OpenAI) that convert the proposed neutral types to and from each
> vendor's wire format, and exercise them against three scenarios: (a) a single tool call,
> (b) **two parallel tool calls in one assistant response**, (c) a tool result flagged as
> an error, followed by a model retry.
>
> **Constraints.** Throwaway code, quality bar is "readable enough to draw conclusions."
> Use the official `anthropic` and `openai` SDKs. Live calls are expected; keep them
> minimal and use the cheapest capable model from each vendor. Do not build a CLI, a spec
> loader, or a loop abstraction.
>
> **Files.** Create `spikes/001_provider_normalization/` containing `neutral.py`,
> `adapter_anthropic.py`, `adapter_openai.py`, `probe.py`, and `FINDINGS.md`.
>
> **Acceptance criteria.**
> - [ ] `python spikes/001_provider_normalization/probe.py --provider anthropic` runs all
>       three scenarios and prints the neutral `ModelResponse` for each.
> - [ ] Same for `--provider openai`.
> - [ ] Parallel tool calls round-trip correctly for both vendors: two `ToolCall` entries
>       in one `ModelResponse`, and two tool results sent back in call order.
> - [ ] Error tool results round-trip for both vendors.
> - [ ] `FINDINGS.md` answers each question below with a concrete yes/no plus evidence.
>
> **Questions FINDINGS.md must answer.**
> 1. Does one `stop_reason` enum cover both vendors without loss? List the exact mapping
>    table, including anything that has no clean neutral equivalent.
> 2. Are tool-call arguments always parseable to `dict` at adapter level, or can a vendor
>    emit malformed/partial JSON that must surface upward? What is the failure policy?
> 3. Can tool **results** be represented as one neutral shape, given the vendors differ on
>    whether results are separate messages or blocks within one message?
> 4. Does either vendor require the assistant's tool-call message to be echoed back
>    verbatim (including ids/fields we would otherwise drop)? If yes, `Message` needs a
>    provider-opaque passthrough field — say so explicitly.
> 5. Are tool-call ids stable and always present?
> 6. What must be excluded from a request fingerprint to be vendor-neutral? (Feeds
>    SPIKE-002.)
>
> **Out of scope.** Streaming, retries, cost calculation, caching, any non-tool feature.
>
> **Deliverable.** `FINDINGS.md` ending with a section titled **"Verdict"** that states
> either "the proposed types in SPEC §3 hold as written" or a concrete list of required
> amendments with the exact revised type definitions. This verdict is a blocking input to
> AC-002.

---

### SPIKE-002 — Cassette fingerprint stability
**Type:** spike   **Milestone:** v0.1 (informs v0.2 build)
**Depends on:** SPIKE-001   **Time-box:** half day

**Prompt:**
> **Context.** v0.2 will record provider responses to disk ("cassettes") and replay them so
> CI runs offline, deterministically, at zero API cost (`SPEC.md` §9 v0.2). The fingerprint
> that keys a cassette must be stable across irrelevant changes and must change when the
> request meaningfully changes. Getting this wrong makes cassettes either constantly
> invalidated (useless) or silently stale (dangerous). The decision constrains how requests
> are represented in v0.1, so it must be settled now even though cassettes ship in v0.2.
> `spikes/001_provider_normalization/` exists and its `FINDINGS.md` is authoritative on the
> neutral request shape.
>
> **Task.** Design and empirically test a request-fingerprinting scheme. Determine exactly
> which fields belong in the hash, and prove the resulting key is stable under
> irrelevant variation and sensitive to relevant variation.
>
> **Constraints.** Hash input must be canonical JSON: sorted keys, no whitespace variance,
> stable float formatting, explicit unicode normalization. Algorithm SHA-256, truncated to
> 16 hex chars for filenames. No network calls needed — operate on captured request
> payloads.
>
> **Files.** Create `spikes/002_cassette_fingerprint/` with `fingerprint.py`,
> `test_stability.py`, and `FINDINGS.md`.
>
> **Acceptance criteria.**
> - [ ] Fingerprint is IDENTICAL across: dict key insertion order; different API keys;
>       different timestamps or request ids; adapter version bumps; Unicode normalisation
>       form; **provider-generated tool-call ids**.
> - [ ] Fingerprint DIFFERS when a tool `description` changes. (CORRECTED 2026-07-30: the
>       original brief called for stability here. That was wrong — a description is prompt
>       text and the primary lever for steering tool selection. Rule: when stability and
>       sensitivity conflict, sensitivity wins.)
> - [ ] Fingerprint DIFFERS for any change to: model, system prompt (including whitespace),
>       message content, tool `name` or `input_schema`, temperature, top_p, max_tokens.
> - [ ] `pytest spikes/002_cassette_fingerprint/test_stability.py` passes with one test per
>       bullet above.
> - [ ] A documented decision on whether tool ORDER is semantically meaningful (it can
>       affect model behavior) — and therefore whether it belongs in the hash.
>
> **Questions FINDINGS.md must answer.**
> 1. Final field list: included vs excluded, with a one-line rationale each.
> 2. Is tool order in the hash? Justify against the risk of spurious invalidation.
> 3. How are cassettes stored and named so a human reviewing a git diff can tell which case
>    a cassette belongs to? Propose the on-disk layout.
> 4. What happens when a cassette exists but its recorded response shape predates a schema
>    change? Propose a version field and a migration/invalidation policy.
> 5. Does anything here require a field on the v0.1 request types that SPEC §3 lacks?
>
> **Out of scope.** Implementing the cassette store, replay logic, or CLI flags. This is
> design + proof only.
>
> **Deliverable.** `FINDINGS.md` with a **"Verdict"** section giving the final canonical
> fingerprint algorithm as pseudocode plus the on-disk layout, and an explicit statement of
> any amendment required to SPEC §3 or §9.

---

### SPIKE-003 — YAML spec validation error UX
**Type:** spike   **Milestone:** v0.1
**Depends on:** none   **Time-box:** half day

**Prompt:**
> **Context.** `dryfire`'s adoption target is a green test within 60 seconds of `init`
> (`SPEC.md` §1.6). The most likely thing to blow that budget is an unreadable validation
> error when a user hand-edits a suite YAML. Specs are loaded into pydantic v2 models
> (`SPEC.md` §4). Pydantic reports errors by field path (`cases.0.expect.2.tool_args`), not
> by file position, which is useless in a 200-line YAML.
>
> **Task.** Determine whether pydantic v2 `ValidationError` field paths can be reliably
> mapped back to line and column in the source YAML, and prototype the best achievable
> error rendering.
>
> **Constraints.** Try `ruamel.yaml` round-trip mode, which preserves `.lc` position data on
> loaded nodes. Compare against alternatives (custom loader, `yaml.compose()` node tree).
> Do not adopt a dependency heavier than `ruamel.yaml`. Must work for errors nested at
> least three levels deep (`cases[].expect[].<assertion>`).
>
> **Files.** Create `spikes/003_spec_errors/` with `locate.py`, `sample_broken.eval.yaml`
> (containing at least five distinct error classes), `render.py`, and `FINDINGS.md`.
>
> **Acceptance criteria.**
> - [ ] `python spikes/003_spec_errors/render.py sample_broken.eval.yaml` prints, for each
>       error: file path, line and column, the offending source line, a caret marker, and a
>       plain-language message.
> - [ ] Works for all five error classes: unknown assertion kind; wrong type for a field;
>       missing required field; unknown top-level key; a `$ref` pointing at a missing file.
> - [ ] Unknown-assertion-kind errors suggest the closest valid kind by edit distance.
> - [ ] Errors are reported for the WHOLE file in one pass, not one-at-a-time.
>
> **Questions FINDINGS.md must answer.**
> 1. Can every pydantic error path be resolved to a position? Which cases cannot, and what
>    is the fallback rendering?
> 2. What is the performance cost of round-trip loading on a 500-line suite?
> 3. Does this force a specific loader choice that SPEC §8.1 must record as a hard
>    dependency?
> 4. Recommended module boundary: where does position-mapping live so that `spec/loader.py`
>    and `spec/errors.py` stay separable?
>
> **Out of scope.** Implementing the real loader or the real models. Prototype only.
>
> **Deliverable.** `FINDINGS.md` with a **"Verdict"** section recommending the approach, plus
> a copy-pasteable reference implementation of the position-mapping function that AC-004
> will adapt.

---

## 8. Feature ticket backlog

To be expanded into full prompts in the next pass. IDs are stable; do not renumber.

| ID | Title | Depends on | Spec ref |
|---|---|---|---|
| AC-001 | Project scaffold: `uv`, `pyproject.toml`, ruff, mypy, pytest, CI workflow | spikes | §8.1 |
| AC-002 | Domain types: `providers/base.py`, `runner/trace.py` | AC-001, SPIKE-001 | §3 |
| AC-003 | Spec pydantic models: project config, suite, case, mock rules, assertion refs | AC-002 | §4 |
| AC-004 | Spec loader: YAML → models, `$ref` resolution, env interpolation, positioned errors | AC-003, SPIKE-003 | §4.4 |
| AC-005 | Config resolution: project defaults → suite → case override chain | AC-004 | §4.2 |
| AC-006 | `FakeProvider` + offline test harness | AC-002 | §8.2 |
| AC-007 | Anthropic provider adapter | AC-002, SPIKE-001 | §3.1 |
| AC-008 | Mock resolver: ordered rules, subset `when` matching, `sequence`, `on_unmocked` | AC-003 | §4.4 |
| AC-009 | Agent loop `run_case` incl. parallel tool calls and all termination reasons | AC-006, AC-007, AC-008 | §5 |
| AC-010 | Assertion framework: protocol, `AssertionResult`, registry, spec-time validation | AC-002 | §6, §6.3 |
| AC-011 | Six structural assertions with required failure-message format | AC-009, AC-010 | §6.1 |
| AC-012 | Scheduler: asyncio, semaphore, `--concurrency`, spec-order results | AC-009 | §5 |
| AC-013 | Terminal reporter with `rich`, TTY-degradation | AC-011, AC-017 | §7.2 |
| AC-014 | JSON reporter and `--json-out` trace serialization | AC-013 | §7 |
| AC-015 | CLI: `run`, `validate`, `trace`, all flags, contractual exit codes | AC-014 | §7, §7.1 |
| AC-016 | `init` scaffold + bundled keyless example meeting the 60-second target | AC-015 | §1.6, §9 |
| AC-017 | Pricing data file + cost computation, `None` on unknown model | AC-002 | §3.2 |
| AC-018 | Dogfood: dryfire's own eval suite running against `FakeProvider` in CI | AC-016 | §8.2 |
| AC-019 | README with above-the-fold example, asciinema GIF, PyPI release | AC-018 | §9 |

---

## 9. Notes for the next pass

When expanding AC-001…AC-019 into prompts:

- AC-009 (the loop) and AC-011 (assertion failure messages) are the two tickets where
  quality actually matters. Budget the most prompt detail there; both deserve explicit
  test tables enumerating input trace → expected result.
- AC-002 must not be written until all three spike verdicts are in hand — the verdicts may
  amend SPEC §3.
- AC-016's acceptance criterion is a stopwatch measurement on a clean container, not a
  subjective judgment. Write it that way.

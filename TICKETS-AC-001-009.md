# EPIC-001 — Tickets AC-001 … AC-009

Each ticket is self-contained: paste the **Prompt** block into Claude Code as one unit of
work. Read `SPEC.md` first; it is authoritative and already carries the six post-spike
amendments. Reference implementations live in `spikes/`.

**Global constraints for every ticket in this epic:**

- Python 3.12+, managed with `uv`. Never `pip install` into a global environment.
- No new runtime dependency without adding it to `pyproject.toml` and justifying it.
- Every test must pass **offline with no API key**. Anything needing network gets
  `@pytest.mark.live` and is skipped by default.
- `ruff` and `mypy --strict` must pass on every ticket before it is considered done.
- Do not build anything listed in EPIC-001 §4 (Out of scope). If a ticket appears to
  require it, stop and flag rather than building forward.

---

### AC-001 — Project scaffold and toolchain
**Type:** chore   **Milestone:** v0.1
**Depends on:** spikes complete   **Spec:** §8, §8.1

**Prompt:**
> **Context.** Greenfield repository for `agentcheck`, a CLI that runs LLM agent
> tool-calling test suites and asserts on the trajectory. `SPEC.md` §8 defines the target
> package layout; §8.1 defines dependencies. Nothing exists yet.
>
> **Task.** Create the repository skeleton, toolchain configuration, and CI so that every
> subsequent ticket has a working `uv run pytest` / `uv run ruff` / `uv run mypy` loop.
>
> **Constraints.**
> - `ruamel.yaml` is a **required core** dependency. Do not add `pyyaml` — it is banned
>   from the spec-loading path (SPEC §8.1).
> - Provider SDKs (`anthropic`, `openai`) are **optional extras**. `import agentcheck` must
>   succeed with neither installed.
> - The app name must be read from a single constant, not hardcoded in user-facing strings.
> - `mypy --strict` on `agentcheck/`. Tests may be looser.
>
> **Files.**
> - `pyproject.toml` — `[project]` with core deps; `[project.optional-dependencies]` for
>   `anthropic`, `openai`, `all`, `dev`; `[project.scripts] agentcheck = "agentcheck.cli:app"`;
>   `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]` with `markers = ["live: requires API key"]`.
> - `agentcheck/__init__.py`, `agentcheck/__about__.py` (`APP_NAME`, `__version__`, `CONFIG_DIR = ".agentcheck"`).
> - Empty packages with `__init__.py`: `spec/`, `providers/`, `runner/`, `assertions/`, `reporters/`, `scaffold/`, `data/`.
> - `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `tests/conftest.py`.
> - `.github/workflows/ci.yml` — matrix on 3.12/3.13; runs ruff, mypy, pytest; **no secrets configured**, proving the suite is offline.
> - `.gitignore` (include `.agentcheck/runs/`, exclude `.agentcheck/cassettes/`), `LICENSE` (MIT), `README.md` stub.
>
> **Acceptance criteria.**
> - [ ] `uv sync --all-extras` succeeds from a clean checkout.
> - [ ] `uv run pytest` passes (zero tests is acceptable at this stage).
> - [ ] `uv run ruff check .` and `uv run mypy agentcheck` both clean.
> - [ ] `uv run agentcheck --help` prints usage and exits 0.
> - [ ] `uv run --no-extra all python -c "import agentcheck"` succeeds with no provider SDK installed.
> - [ ] CI workflow runs green on push with no secrets set.
>
> **Out of scope.** Any command implementation beyond `--help`. Any domain logic.
>
> **Deliverable.** A repository where `uv run pytest && uv run ruff check . && uv run mypy agentcheck` is a single green gate.

---

### AC-002 — Provider-neutral domain types
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-001, SPIKE-001   **Spec:** §3, §3.1, §3.3

**Prompt:**
> **Context.** SPIKE-001 validated the provider-neutral model against both Anthropic and
> OpenAI wire formats and produced four amendments, now folded into `SPEC.md` §3. The
> reference implementation is `spikes/001_provider_normalization/neutral.py`. These types
> are the contract every other subsystem depends on; get them wrong and the loop,
> assertions, reporters, and v0.2 cassettes all inherit the mistake.
>
> **Task.** Implement the domain types and the `Provider` protocol exactly as specified in
> SPEC §3, plus the stop-reason mapping helper from §3.3.
>
> **Constraints.**
> - Pydantic v2 `BaseModel` throughout (the spike used dataclasses — convert).
> - `ToolCall.malformed_arguments` and `Message.raw` are **required fields of the model**,
>   not optional extras. Both exist for reasons documented in SPIKE-001; do not remove them
>   as unused — nothing consumes them until AC-007.
> - `Turn.request_messages` is load-bearing for v0.2 cassettes. Keep it.
> - This module imports **no** provider SDK and contains **no** vendor names in logic (a
>   mapping table keyed by provider name is fine).
> - `Trace.tool_calls()` and `Trace.tool_names()` must flatten in true call order across all
>   turns — this is the primary surface every structural assertion reads.
>
> **Files.**
> - `agentcheck/providers/base.py` — `Usage`, `ToolDef`, `ToolCall`, `ToolResult`, `Message`, `ModelResponse`, `StopReason`, `ModelParams`, `Provider` protocol.
> - `agentcheck/runner/trace.py` — `Turn`, `TerminationReason`, `Trace` with `tool_calls()` / `tool_names()`.
> - `tests/unit/test_domain_types.py`.
>
> **Acceptance criteria.**
> - [ ] All types in SPEC §3 exist with the exact field names and defaults shown there.
> - [ ] `Trace.tool_names()` on a 3-turn trace with 2 parallel calls in turn 1 returns all
>       calls in order across turns — test with an explicit expected list.
> - [ ] `Trace` round-trips through `model_dump_json()` / `model_validate_json()` with no
>       loss, including `Message.raw` and `malformed_arguments`.
> - [ ] Serialised `Trace` contains no non-finite floats (`allow_nan=False` compatible) —
>       required by v0.2 fingerprinting.
> - [ ] A `Provider` stub implementing only `complete()` and `cost()` satisfies the protocol
>       under `mypy --strict`.
> - [ ] `map_stop_reason(provider, raw_value)` implements the SPEC §3.3 table and returns
>       `"error"` for unknown values **without raising** — test with a synthetic value.
>
> **Out of scope.** Any concrete provider. The loop. Assertions. Cost calculation (AC-017).
>
> **Deliverable.** Two modules plus tests. No behaviour, only the contract.
>
> **Note.** SPIKE-001's live probe run is still outstanding. If it contradicts anything
> here, this ticket is reopened rather than patched downstream.

---

### AC-003 — Spec models
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-002   **Spec:** §4.2, §4.3, §4.4

**Prompt:**
> **Context.** Users write suites as YAML (`SPEC.md` §4.3 has a complete worked example).
> This ticket implements the pydantic models those files validate against. Loading,
> `$ref` resolution, and error rendering are AC-004 — this ticket is the schema only.
>
> **Task.** Implement pydantic models for the project config and suite files per SPEC §4.
>
> **Constraints.**
> - `extra="forbid"` on every model. Unknown keys are user errors and must surface as such.
> - `return` is a Python keyword: the `MockRule` field is `returns` with `alias="return"`
>   and `populate_by_name=True`.
> - `MockRule` must validate that **exactly one** of `returns` / `error` / `sequence` is set
>   — a model validator, with a message naming which were found.
> - `expect` entries stay as `list[dict]` at this layer. Assertion kinds are registry-driven
>   (§6.3) and cannot be checked by pydantic; that check belongs in AC-004's pre-pass.
> - Do **not** resolve `$ref` here. A `$ref` key reaching these models is a bug in the
>   caller.
> - Every field that SPEC §4.2 says has a project-level default must be `| None` here, with
>   resolution deferred to AC-005. Do not bake defaults into the models.
>
> **Files.**
> - `agentcheck/spec/models.py` — `ProjectConfig`, `Defaults`, `CassetteConfig`, `Suite`, `Case`, `MockRule`, `ToolSpec`.
> - `tests/unit/test_spec_models.py`.
>
> **Acceptance criteria.**
> - [ ] The complete SPEC §4.3 example validates cleanly.
> - [ ] The SPEC §4.2 project config example validates cleanly.
> - [ ] `MockRule` with zero of `return`/`error`/`sequence` fails; with two set, fails; with
>       exactly one, passes. Three tests.
> - [ ] `MockRule` accepts `return:` from YAML and exposes it as `.returns`.
> - [ ] An unknown key at suite, case, and tool level each raise `extra_forbidden`.
> - [ ] `Case.input` accepts both a bare string and a list of role/content dicts.
> - [ ] Case-level `mocks` and suite-level `mocks` use the identical `MockRule` model.
>
> **Out of scope.** YAML loading, `$ref`, env interpolation, positioned errors, assertion
> kind validation, default resolution.
>
> **Deliverable.** `models.py` plus tests, validating the spec's own worked examples.

---

### AC-004 — Spec loader with positioned errors
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-003, SPIKE-003   **Spec:** §4.1 (load pipeline), §4.4

**Prompt:**
> **Context.** SPIKE-003 proved that pydantic v2 error paths can be mapped back to YAML
> line/col via `ruamel.yaml` round-trip mode, and produced a working reference
> implementation. **Lift `spikes/003_spec_errors/locate.py` — the `Position` class and the
> `locate()` walker — essentially verbatim.** `render()` in that spike defines the required
> output format. The adoption target (SPEC §1.6) makes this the highest-leverage UX in the
> product: a user hand-edits YAML, gets it wrong, and what happens next determines whether
> they stay.
>
> **Task.** Implement the three-stage load pipeline from SPEC §4.1: positioned YAML load →
> `$ref` + env pre-pass → assertion-registry pre-pass → pydantic → collected, rendered
> errors.
>
> **Constraints.**
> - Stage order is **normative**. Pre-passes run before pydantic, because `extra="forbid"`
>   would otherwise reject a raw `$ref` key and mask the real error.
> - **All** errors from **all** stages are collected in one pass and sorted by source
>   position. Never fail on the first error.
> - `missing`-class errors have no source token by definition. Resolve to the deepest
>   enclosing node, flag `exact=False`, and render `(nearest enclosing node)`.
> - **Cascade suppression is mandatory:** a node substituted because its `$ref` failed must
>   suppress every pydantic error beneath that loc prefix. During the spike this reduced a
>   sample from 7 errors to 5 for the same 5 mistakes.
> - `${VAR}` interpolation: a missing environment variable is a spec error, **never** an
>   empty string.
> - `$ref` paths resolve relative to the containing suite file, not the CWD.
> - Round-trip loading is unconditional. Measured cost is ~40 ms on a 488-line suite. Do not
>   build a fast path.
>
> **Files.**
> - `agentcheck/spec/positions.py` — `Position`, `load_positioned`, `locate`. Schema-agnostic.
> - `agentcheck/spec/errors.py` — `SpecError`, the pydantic-code → plain-language message table, `render()`.
> - `agentcheck/spec/loader.py` — pipeline orchestration, `$ref`, env interpolation.
> - `tests/unit/test_spec_loader.py`, `tests/fixtures/broken/*.eval.yaml`.
>
> **Acceptance criteria.**
> - [ ] All five error classes report with file, line, col, source line, and caret: unknown
>       assertion kind; wrong field type; missing required field; unknown top-level key;
>       `$ref` to a missing file.
> - [ ] All errors in a file are reported in one pass, sorted by source position.
> - [ ] A failed `$ref` produces **exactly one** error — regression test asserting the count.
> - [ ] Unknown assertion kinds produce a did-you-mean suggestion by edit distance
>       (`calls_tolo` → `calls_tool`).
> - [ ] `missing` errors resolve to the nearest enclosing node and render the approximation
>       marker.
> - [ ] `${MISSING_VAR}` produces a positioned spec error, not an empty string.
> - [ ] A `$ref` resolves correctly when the suite is loaded from a different CWD.
> - [ ] Loading a valid suite makes **zero** network calls (assert with a patched transport).
> - [ ] Golden-file test pinning the exact rendered output of `tests/fixtures/broken/all_five.eval.yaml`.
>
> **Out of scope.** Default resolution (AC-005). Executing anything. The `validate` CLI
> command (AC-015) — expose a callable, not a command.
>
> **Deliverable.** A loader returning `(list[Suite], list[SpecError])`, plus a renderer whose
> output matches the spike's format.

---

### AC-005 — Configuration resolution
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-004   **Spec:** §4.2

**Prompt:**
> **Context.** Settings arrive from four places with a precedence order: built-in defaults →
> `agentcheck.yaml` `defaults:` → suite-level fields → case-level fields, with CLI flags
> overriding everything. AC-003 deliberately left these fields `| None` so this ticket owns
> resolution in one place.
>
> **Task.** Implement discovery of `agentcheck.yaml`, suite-file globbing, and the
> precedence chain producing a fully-resolved `ResolvedCase` for the runner.
>
> **Constraints.**
> - Precedence is exactly: CLI flag > case > suite > project `defaults:` > built-in.
> - Built-in defaults per SPEC §4.2: `max_turns=10`, `temperature=0`, `on_unmocked="error"`,
>   `concurrency=4`.
> - Project config discovery walks upward from CWD to the filesystem root. If none is found,
>   built-in defaults apply and this is **not** an error — a bare suite file must be runnable.
> - Resolution is pure: inputs in, `ResolvedCase` out. No I/O beyond config discovery, no
>   global state.
> - `ResolvedCase` must carry the source suite path and case name; reporters and cassette
>   paths both need them.
>
> **Files.**
> - `agentcheck/config.py` — discovery, `ResolvedCase`, `resolve()`.
> - `tests/unit/test_config_resolution.py`.
>
> **Acceptance criteria.**
> - [ ] One test per precedence level proving each overrides the one below it.
> - [ ] Running from a subdirectory finds the project config in an ancestor.
> - [ ] No project config anywhere → built-in defaults, no error raised.
> - [ ] Suite glob patterns from `suites:` resolve relative to the config file's directory.
> - [ ] A case inheriting nothing gets every built-in default, asserted field by field.
> - [ ] `resolve()` is pure — calling it twice with the same inputs gives equal results.
>
> **Out of scope.** CLI flag parsing (AC-015) — accept an overrides dict.
>
> **Deliverable.** `resolve()` returning fully-populated `ResolvedCase` objects with no
> `None` fields remaining.

---

### AC-006 — FakeProvider and offline test harness
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-002   **Spec:** §8.2

**Prompt:**
> **Context.** SPEC §8.2 requires the entire test suite to run offline with no API key. That
> is only achievable if every loop, mock, and assertion test drives a scripted provider.
> This ticket builds it, and it is used by AC-009, AC-011, AC-012, AC-013, and AC-018 — so
> its ergonomics determine how pleasant the rest of the epic is to write.
>
> **Task.** Implement `FakeProvider`, satisfying the `Provider` protocol, which returns a
> pre-scripted sequence of `ModelResponse` objects.
>
> **Constraints.**
> - Lives in `agentcheck/providers/fake.py`, **shipped in the package**, not in `tests/` —
>   AC-016's keyless scaffold example depends on it at runtime.
> - Must support a terse construction form. Aim for:
>   `FakeProvider.script([tool_call("lookup_order", {"order_id": "A-991"}), text("Done.")])`
> - Records every request it receives so tests can assert on what the loop actually sent —
>   this is how AC-009 verifies message construction.
> - Raises a clear error when the script is exhausted but another call arrives, naming how
>   many calls were made. A silent repeat would mask infinite-loop bugs.
> - Supports scripting a provider **failure** (raising) to exercise the `provider_error`
>   termination path.
> - Generates deterministic, unique tool-call ids (`fake_call_0`, `fake_call_1`, …).
>
> **Files.**
> - `agentcheck/providers/fake.py` — `FakeProvider`, helpers `text()`, `tool_call()`, `parallel()`, `fails()`.
> - `tests/conftest.py` — fixtures.
> - `tests/unit/test_fake_provider.py`.
>
> **Acceptance criteria.**
> - [ ] Satisfies the `Provider` protocol under `mypy --strict`.
> - [ ] Returns scripted responses in order; `.requests` exposes what it received.
> - [ ] `parallel()` produces one `ModelResponse` carrying two `ToolCall`s.
> - [ ] Script exhaustion raises an error naming the call count.
> - [ ] `fails()` causes `complete()` to raise a provider-style exception.
> - [ ] Tool-call ids are unique within a run and stable across runs.
> - [ ] Importable with no provider SDK installed.
>
> **Out of scope.** The loop. Cassettes. Any real provider.
>
> **Deliverable.** A scripted provider that makes every downstream ticket testable offline.

---

### AC-007 — Anthropic provider adapter
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-002, AC-006, SPIKE-001   **Spec:** §3.1, §3.3

**Prompt:**
> **Context.** SPIKE-001 built and structurally verified an Anthropic adapter —
> `spikes/001_provider_normalization/adapters.py::AnthropicAdapter` is your reference.
> **Read `spikes/001_provider_normalization/FINDINGS.md` and
> `spikes/002_cassette_fingerprint/FINDINGS.md` before starting.** Their verdicts are in
> tension and you must hold both: tool-call ids are preserved **verbatim on the wire** and
> normalised **only on the fingerprint path** (v0.2). Getting this wrong breaks multi-turn
> replay later in a way that is very hard to trace back here.
>
> **Task.** Implement the production Anthropic adapter satisfying the `Provider` protocol.
>
> **Constraints.**
> - Two responsibilities only: `to_wire` and `from_wire`. **No loop logic, no retry logic,
>   no assertion logic.** If the adapter needs anything else, the protocol is wrong — stop
>   and flag it.
> - Anthropic validates that `tool_use` ids in a replayed assistant turn match what it
>   issued and rejects reconstructions. When `Message.raw` is present, **echo it verbatim**;
>   reconstruct from neutral fields only as a fallback.
> - Tool results are `tool_result` blocks inside a **user** message. N parallel results →
>   **one** message with N blocks, in call order.
> - `from_wire` must populate `Message.raw` so the next turn can echo it.
> - Stop reasons via the SPEC §3.3 table. Unknown values → `"error"`, never raise.
> - Tool-call ids are opaque: never parse, never assume a prefix, never regenerate.
> - `anthropic` is an optional extra. A missing SDK produces an actionable error naming the
>   exact install command — not an `ImportError` traceback.
>
> **Files.**
> - `agentcheck/providers/anthropic.py`.
> - `tests/unit/test_anthropic_adapter.py`, `tests/fixtures/anthropic/*.json`.
> - `tests/integration/test_anthropic_live.py` (`@pytest.mark.live`).
>
> **Acceptance criteria.**
> - [ ] Recorded-payload tests (no network) for: single tool call; two parallel tool calls;
>       text-only response; `max_tokens` truncation; an error tool result.
> - [ ] Parallel calls round-trip with order preserved, verified both directions.
> - [ ] An assistant turn with `raw` set is echoed byte-identically by `to_wire`.
> - [ ] `is_error=True` produces `"is_error": true` on the wire.
> - [ ] An unknown `stop_reason` maps to `"error"` without raising.
> - [ ] Importing `agentcheck` without the `anthropic` extra succeeds; **constructing** the
>       adapter raises a message containing the install command.
> - [ ] `@pytest.mark.live` test performing one real two-turn tool-calling exchange, skipped
>       without `ANTHROPIC_API_KEY`.
> - [ ] **Blocking:** `spikes/001/probe.py --provider anthropic` has been run live and its
>       canned payloads replaced with real responses. Fixtures in this ticket derive from
>       those real responses, not from the spike's hand-written approximations.
>
> **Out of scope.** OpenAI (v0.2). Streaming. Retries (v0.2). Cost (AC-017). Cassettes (v0.2).
>
> **Deliverable.** A production adapter whose unit tests run entirely offline against
> real recorded payloads.

---

### AC-008 — Mock resolver
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-003   **Spec:** §4.4

**Prompt:**
> **Context.** Mocked tools are what make eval runs deterministic and fast — real tools have
> side effects and non-deterministic outputs. SPEC §4.4 defines the rule semantics. The
> `sequence` form (first call errors, second succeeds) is what makes error-recovery testing
> possible and is a **first-class feature, not an edge case** — it is one of the things this
> tool has that competitors do not.
>
> **Task.** Implement `MockResolver`: given a `ToolCall`, return a `ToolResult` or signal
> UNMOCKED.
>
> **Constraints.**
> - Rules are evaluated **in order, first match wins**.
> - `when` is a **deep subset** match against parsed arguments: every key/value in `when`
>   must be present and equal in the call arguments; extra argument keys do not prevent a
>   match. Nested dicts recurse. Lists compare by equality, not subset.
> - A rule with no `when` is a catch-all and matches anything.
> - `sequence` is consumed one entry per matching call; **the last entry repeats** once
>   exhausted. State is per-case, never shared across cases — a resolver is constructed
>   fresh per case, and concurrent cases must not interfere (AC-012 runs them in parallel).
> - `error` produces `ToolResult(is_error=True)`.
> - Case-level mocks **replace** the whole rule list for that tool name; they do not append
>   to suite-level rules.
> - Unmatched call → return a sentinel, do not raise. The loop owns the `on_unmocked` policy.
> - A call whose `malformed_arguments` is set can never match a `when` rule; it may match a
>   catch-all. Document this explicitly.
>
> **Files.**
> - `agentcheck/runner/mocks.py` — `MockResolver`, `UNMOCKED` sentinel.
> - `tests/unit/test_mock_resolver.py`.
>
> **Acceptance criteria.**
> - [ ] First-match-wins verified with two rules that both match.
> - [ ] Deep subset: `when: {a: 1}` matches `{a: 1, b: 2}` and does not match `{a: 2}`.
> - [ ] Nested subset: `when: {x: {y: 1}}` matches `{x: {y: 1, z: 2}}`.
> - [ ] Catch-all matches when no `when` rule does.
> - [ ] `sequence` of 2 across 4 calls yields entries 1, 2, 2, 2.
> - [ ] Case-level mocks fully replace suite-level rules for that tool.
> - [ ] Two resolvers built from the same spec have independent `sequence` state.
> - [ ] Unmatched call returns `UNMOCKED`, does not raise.
> - [ ] A `malformed_arguments` call falls through `when` rules to the catch-all.
>
> **Out of scope.** `passthrough` mocks (v0.2). The loop's `on_unmocked` handling (AC-009).
>
> **Deliverable.** A pure, per-case resolver with no I/O and no shared state.

---

### AC-009 — The agent loop
**Type:** feature   **Milestone:** v0.1
**Depends on:** AC-006, AC-007, AC-008   **Spec:** §5

**Prompt:**
> **Context.** This is the core of the product. `SPEC.md` §5 gives numbered pseudocode and a
> list of invariants. Everything else — assertions, reporters, cassettes, compare — reads
> the `Trace` this function produces. It must be readable, directly testable without
> network, and correct on the edges that matter: parallel tool calls, turn limits, provider
> failure, and unmocked calls.
>
> **Task.** Implement `run_case(resolved_case, provider, resolver) -> Trace` exactly per
> SPEC §5.
>
> **Constraints.**
> - Follow the SPEC §5 pseudocode step for step. Deviating means the spec is wrong — fix the
>   spec in the same PR rather than diverging silently.
> - **Never raise for a normal outcome.** `max_turns_exceeded`, `provider_error`, and
>   `unmocked_tool` are all recorded terminations. A failing case must not abort the run.
> - Parallel tool calls: iterate `response.tool_calls` in order, resolve each, append results
>   **in call order**. The adapter decides message shaping; the loop only guarantees order.
> - Retries are **not** turns (v0.2 concern, but do not design them out).
> - `Turn.request_messages` must hold a **copy** of what was sent that turn, taken before
>   mutation. This is load-bearing for v0.2 cassettes.
> - The loop must **never mutate the case spec**. Take defensive copies.
> - The loop is pure with respect to the resolver: given `FakeProvider` and a resolver, the
>   returned `Trace` is deterministic and no network call occurs.
> - `async def`. No `asyncio.run` inside — AC-012 owns scheduling.
>
> **Files.**
> - `agentcheck/runner/loop.py` — `run_case`.
> - `tests/unit/test_loop.py`.
>
> **Acceptance criteria — one test per row, all against `FakeProvider`:**
>
> | # | Script | Expected |
> |---|---|---|
> | 1 | text only | 1 turn, `termination="end_turn"`, `final_text` set, no tool calls |
> | 2 | tool_call → text | 2 turns, 1 tool call, tool result appended, `end_turn` |
> | 3 | parallel(2 calls) → text | 2 turns, `tool_names()` in call order, 2 results in call order |
> | 4 | tool_call × 12, `max_turns=3` | exactly 3 turns, `termination="max_turns_exceeded"`, no exception |
> | 5 | provider raises on turn 2 | `termination="provider_error"`, `Trace.error` populated, turn 1 retained |
> | 6 | call to unmocked tool, `on_unmocked="error"` | `termination="unmocked_tool"`, message names tool **and** its arguments |
> | 7 | same, `on_unmocked="null"` | loop continues, result content empty |
> | 8 | tool errors then succeeds (`sequence`) | 3 turns, first result `is_error=True`, second not |
> | 9 | `stop_reason="max_tokens"` | `termination="max_tokens"`, loop stops |
> | 10 | any multi-turn script | `Turn.request_messages` grows per turn and turn N's copy is unaffected by turn N+1 |
> | 11 | any script | the input `ResolvedCase` is unchanged after the call (deep-equality assert) |
> | 12 | 2-turn script | `total_usage` is the sum of per-turn usage |
>
> Plus:
> - [ ] Every test runs with no network and no API key.
> - [ ] `run_case` never raises for any row above.
> - [ ] Test asserting the loop makes exactly N provider calls for an N-turn script, via
>       `FakeProvider.requests`.
>
> **Out of scope.** Concurrency (AC-012). Assertions (AC-010/011). Cost (AC-017).
> Reporting (AC-013). Cassettes (v0.2).
>
> **Deliverable.** `run_case` plus a test module where all twelve rows are individually
> named tests. If any row is awkward to express, that is a signal the `Trace` model is
> wrong — flag it rather than working around it in the test.

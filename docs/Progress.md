# Progress

**Last Updated:** 2026-08-01

---

## How This Works

Global tracker for agentcheck. Answers three questions without digging through the codebase:
1. What's actively being built?
2. What's shipped and working?
3. What's next?

**Epic reference:** `EPIC-001.md` has the v0.1 goal and ticket sequencing; the tickets live
in `TICKETS-AC-001-009.md` and `TICKETS-AC-010-019.md`.

Update this file when work ships, phases change, or priorities shift.

---

## In Development

> Actively building. Code is being written.

### AC-018 — Dogfood suite in CI (implemented, PR open)
agentcheck runs its own eval suite against the fake provider — proving the tool works by using it,
offline, as a separate CI job (SPEC §8.2). TDD-for-a-harness: mutation-checked (break a pass-case →
red; flip a fail-case to pass → red). Runtime ~2s (<30s target). `make check` green (312 tests + 1
live-skipped).
- `evals/self/pass.eval.yaml` — every one of the six assertions in a **passing** case, plus the
  `end_turn` and `max_turns_exceeded` terminations and a `sequence` error-then-success recovery. Whole
  suite exits 0.
- `evals/self/fail.eval.yaml` — the same six assertions in a **deliberately-failing** case, plus an
  `unmocked_tool` termination case. Whole suite exits 1 (the green outcome for CI).
- `evals/self/provider_error.eval.yaml` — a `fails:` script → `provider_error` termination → exit 3
  (own file: exit 3 outranks the assertion-failure exit 1).
- `scripts/run_dogfood.sh` — runs each bucket, asserts its exit code, then parses the JSON reports to
  check **per-case** polarity (every pass-case passes, every fail-case fails — the aggregate exit code
  alone is blind to one fail-case quietly passing), all four terminations, and the sequence
  error-recovery. `make dogfood` + a separate `dogfood` CI job (distinguishable from the pytest job).
- Suites double as documentation: every case is commented and mirrors a pass/fail pair.

---

## Up Next

> Committed work, ready to start. Ordered by the EPIC-001 dependency graph.

1. **AC-019** — release: README with an above-the-fold runnable example, asciinema GIF, PyPI publish,
   fold in the parked `COMPARISON.md` (re-verify every competitor row against promptfoo.dev first).

---

## Shipped

> Working in the codebase. Committed and tested.

### AC-016 — `init` scaffold and the 60-second target (2026-08-01, PR #17)
`agentcheck init` scaffolds a runnable example that goes green in **<60s with no API key and no
network** (SPEC §1.6). Measured cold start: **3s** in a clean Linux container (`make docker-smoke`),
4s locally.
- **New public spec surface (SPEC §4.4 amended):** `provider` is suite-level (a `fake` and an
  `anthropic` suite coexist); `script:` is a case-level field (tool_call / text / parallel / fails)
  driving a `provider: fake` case from YAML, mapped 1:1 to the `FakeGateway` helpers by
  `adapters/driven/spec/scripts.py`. New `ScriptStep` / `ScriptToolCall` models.
- **Per-case gateways:** a scripted `FakeGateway` is stateful, so `PlannedCase.gateway` overrides a
  run-level default `provider` (mirrors case-over-suite mocks); composition builds a fresh fake per
  fake-case in `_plan`. No churn to AC-012's tests.
- **Skip-on-missing-key:** `make_gateway("anthropic")` raises `MissingCredentials` with no key; `run`
  drops those cases with a visible note (exit 0), `trace` errors. The check lives in the seam tests
  already replace.
- **`init`:** `adapters/driven/scaffold/writer.py` copies `agentcheck/scaffold/template/**` (ships in
  the wheel, read via `importlib.resources`), refuses to clobber without `--force`, prints one next
  command. Template: `agentcheck.yaml`, keyless `hello.eval.yaml`, real `refund_agent.eval.yaml`
  (`$ref` schema, v0.1 assertions), `evals/README.md` — every top-level key commented (asserted).
- `scripts/measure_cold_start.sh` + `make smoke` / `make docker-smoke`.

### AC-015 — CLI surface and exit codes (2026-08-01, PR #16)
`run` / `validate` / `trace` with contractual exit codes (SPEC §7, §7.1) — the composition root that
exposes every library built so far. TDD, gate green (270 tests + 1 live-skipped, ruff, mypy --strict,
5/5 contracts).
- `composition.py` — the ONE module wiring concretes to the app (ARCHITECTURE §7): loader → resolve →
  **spec→domain mock map + merge** → scheduler → **price** → report → exit code. `cli.py` (typer)
  stays logic-free (parse flags → call composition → `typer.Exit(code)`).
- **Exit codes** (`0` pass · `1` assertion failure · `2` spec/config · `3` provider) — one test each.
  **Config is checked before anything network-touching**, so a spec error is `2` even when the
  provider is also unreachable. An unhandled internal exception → clean message + "please report" +
  exit `2`; `--debug` re-raises the traceback. (Provider errors surface as `provider_error`
  terminations from the scheduler → exit `3`.)
- `adapters/driven/spec/mocks.py` — **closes the deferred spec→domain mock mapper thread**
  (AC-005/009/012). `return: null` is mapped via `model_fields_set`; this surfaced that the domain
  `Return.value` / `ToolResult.content` were too narrow — widened both to `... | None` (a documented
  legitimate null tool result).
- **Cost is now wired end-to-end** (closes AC-017's thread): a `_price` post-pass computes
  `calculate(usage, catalog.rates(provider, model))` per case and attaches `total_cost_usd` — the
  reporter's cost column now shows real `$` values.
- Reporter selection: default terminal (+ `--json-out PATH` writes JSON too); `--reporter json` sends
  JSON to stdout and suppresses the terminal. `--filter`/`--tag` compose (AND); zero match → exit `0`
  with "no cases matched". `--model` overrides project+suite (highest-precedence override). `-v` dumps
  failing-case traces. Ruff: `typer.Option`/`Argument` added to bugbear `extend-immutable-calls`.

### AC-014 — JSON reporter and trace serialization (2026-08-01, PR #15)
- `adapters/driven/reporting/json_sink.py` — `render_run` / `write_run` / `deserialize_run`,
  `schema_version: 1`, complete Trace per case (incl. `Message.raw` + `malformed_arguments`), sorted
  keys, `allow_nan=False`, ISO-8601 `...Z` (injected timestamp), atomic temp-file+`os.replace` write.
  Round-trips to a `RunResult` that re-renders the terminal report. `tests/fixtures/run_schema.json`
  validated with `jsonschema` (dev-only). Atomicity mutation-verified.

### AC-013 — Terminal reporter (2026-07-31, PR #14)
- `adapters/driven/reporting/terminal.py` — pure `render_report(run, *, color=False) -> str`
  (byte-pinned golden) + `TerminalReporter` + `resolve_color`. Zero ANSI off a TTY / under
  `NO_COLOR` / `--no-color`; unknown cost → `—`; non-`end_turn` termination on the case line;
  failure blocks are AC-011's `render_failure` indented 6 spaces (truncates long args, never the
  trajectory). Golden matches SPEC §7.2's header/case-lines/summary byte-for-byte; the failure block
  uses the real v0.1 machinery (§7.2's sample was v0.2 `min_tool_calls`).

### AC-017 — Pricing data and cost computation (2026-07-31, PR #13)
- `domain/pricing/calculator.py` — pure `calculate(usage, rates) -> Cost | None`, **`Decimal`
  throughout**; unpriced model → None; cache tokens priced separately (input-rate fallback recorded).
  `application/ports/pricing_catalog.py` (`PricingCatalog`) + `adapters/driven/pricing/bundled.py`
  (`BundledPricingCatalog`, **exact match**, user `pricing_file` replaces+merges, `.updated`).
  `data/pricing.yaml` Anthropic list prices (quoted for exact Decimal), ships in the wheel.
  `--version` surfaces the pricing date. Only computes — wiring to the trace is AC-015.

### AC-012 — Concurrent case scheduler (2026-07-31, PR #12)
- `application/scheduler.py` — `run_suites(suites, provider, *, concurrency=4, fail_fast=False,
  on_progress=None) -> RunResult`. Worker-pool over a shared index iterator (task creation bounded to
  the concurrency); results assembled by index → **spec order regardless of completion order**.
  Three-level result `RunResult(suites, complete) → SuiteResult → CaseResult(trace, assertions,
  passed, error)`. **Evaluates assertions** per case (ARCHITECTURE §6.1); per-case isolation;
  `--fail-fast` cancels in-flight siblings and marks the run incomplete; fresh `MockResolver` per
  case. Spec→domain mock mapper re-assigned to AC-015. All 7 acceptance rows named tests.

### AC-009 — The agent loop (2026-07-31, PR #11)
- `application/loop.py` — `run_case(resolved_case, provider, resolver) -> Trace`. Drives the
  tool-calling loop with deterministic mocks; parallel calls resolved in call order; per-turn
  `request_messages` copies (load-bearing for v0.2 cassettes); usage summed. **Never raises for a
  normal outcome** — max_turns_exceeded / provider_error / unmocked_tool are recorded terminations.
  Imports domain + the `ModelGateway` port only (tests drive `FakeGateway`). All 12 acceptance rows
  are named tests. Added `tools: list[ToolDef]` to `ResolvedCase` (closes the tools half of AC-005's
  deferred thread); mocks stay a passed-in `MockResolver`.

### AC-007 — Anthropic adapter (2026-07-31, PR #10)
- `adapters/driven/providers/anthropic.py` — `to_wire`/`from_wire` (pure, SDK-free) +
  `AnthropicGateway` (lazy SDK import, `AsyncAnthropic`). Fixtures captured from REAL live payloads
  (criterion 8); live two-turn test passes, skips without a key. Closed the SPIKE-001 live probe.

### AC-011 — Structural assertions (2026-07-31, PR #8)
- `domain/assertions/structural.py` (the six: calls_tool/not_calls_tool/tool_args/call_order/
  max_turns/final_contains) + `trajectory.py` (render_trajectory + render_failure). SPEC §6 failure
  pinned byte-for-byte. `registry.build`; promoted shared `matches_subset`.

### AC-010 — Assertion framework (2026-07-31, PR #7)
- `domain/assertions/base.py` (Assertion protocol, AssertionResult, `@register`, `safe_evaluate`,
  DuplicateKind) + `registry.py` (`known_kinds`/`get`/`validate_args`). Rewired the loader to the
  registry with arg-validation. `Args` kept out of the protocol (structural conformance).

### AC-008 — Mock resolver (2026-07-31, PR #6)
- `domain/mocking/resolver.py` — domain mock types (MockRule/Return/Error/Sequence),
  `UNMOCKED`, `MockResolver` (first-match-wins, deep-subset `when`, sequence with per-resolver
  state, malformed→catch-all), `merge_mocks`. Closed AC-005's deferred mock-model thread.

### AC-006 — FakeGateway (2026-07-31, PR #5)
- `adapters/driven/providers/fake.py` (shipped) — `FakeGateway.script([...])` +
  `text()`/`tool_call()`/`parallel()`/`fails()`; scripted responses in order, `.requests`
  recording, deterministic `fake_call_N` ids, `ScriptExhausted` on over-run, no provider SDK.
  Satisfies `ModelGateway`.

### AC-005 — Configuration resolution (2026-07-31, PR #4)
- `domain/model/case.py` — frozen `ResolvedCase`; `adapters/driven/spec/config.py` —
  `resolve()` precedence chain (override > case > suite > project > built-in),
  `discover_config`/`load_project_config`/`glob_suites`. Extended `Case` with case-level
  settings; built-ins cover provider/model; tools/mocks deferred to the runner (AC-008/009).

### AC-004 — Spec loader with positioned errors (2026-07-31, PR #3)
- `adapters/driven/spec/`: `positions.py` (Position/load_positioned/locate, lifted),
  `errors.py` (SpecError, message table, render() caret output), `loader.py` (three-stage
  pipeline: $ref + env interpolation → assertion-kind → pydantic → sorted errors with
  cascade suppression; `load_suite`/`load_suites`). Golden fixture pins the five error
  classes.

### AC-003 — Spec models (2026-07-31, PR #2)
- `adapters/driven/spec/models.py` — ProjectConfig/Defaults/CassetteConfig/Suite/Case/
  MockRule/ToolSpec (SPEC §4); `extra="forbid"`, overridable defaults `| None`,
  MockRule exactly-one via `model_fields_set`. `$ref` assumed pre-resolved.

### AC-002 — Provider-neutral domain types (2026-07-31, PR #1)
- `domain/model/`: tooling (ToolDef, ToolCall+`malformed_arguments`, ToolResult),
  message (Usage, Message+`raw`, ModelResponse), stop_reason (`map_stop_reason` §3.3),
  trace (Turn, Trace with `tool_calls()`/`tool_names()` + finite-cost validator)
- Port `application/ports/model_gateway.py` — `ModelGateway` + `CompletionRequest` +
  `ModelParams`, following ARCHITECTURE §5.1 over SPEC §3.1 (no `cost()`; pricing is
  AC-017). Files per ARCHITECTURE §12.

### Makefile + Docker toolchain (2026-07-30)
- Self-documenting `Makefile` (`make help`) with categorized targets; `make check` is the
  single quality gate (lint + typecheck + arch + test)
- Dev `Dockerfile` (uv, layer-cached, venv at `/opt/venv` to survive bind mounts) and
  `docker-compose.yml` with one-shot `dev` (3.12) and `dev-313` (3.13, `matrix` profile)
  services — a local CI matrix, no long-running services
- Deliberately NOT adopted from terms-pilot: postgres/redis/worker services, SOPS secrets,
  production image, migrations — agentcheck is zero-infra by design (SPEC §1.4)

### AC-001 — Project scaffold and toolchain (2026-07-30)
- uv-managed project, hatchling, flat `agentcheck/` layout; version single-sourced from `__about__.py`
- Layered skeleton per ARCHITECTURE §2 (domain / application / adapters + composition seam)
- `.importlinter` with all five contracts, all KEPT; `mypy --strict`; ruff bans
  `unittest.mock` outside `tests/contracts/` (ADR-006)
- Typer CLI stub (`--help`, `--version`), name read from `APP_NAME`
- CI workflow: 3.12/3.13 matrix, no secrets — proves the suite is offline
- All six ticket acceptance criteria verified, incl. `import agentcheck` with no provider SDK

### Spikes 001–003 (pre-scaffold)
- SPIKE-001 provider normalization, SPIKE-002 cassette fingerprint (19 tests),
  SPIKE-003 positioned spec errors — reference code in `spikes/`, results in `SPIKE-REPORT.md`

---

## On Ice

> Paused or deferred. Not abandoned.

### `COMPARISON.md` — positioning + feature matrix (for AC-019)
**Why parked:** it's release/README material — feature matrix by version and honest
Promptfoo/Langfuse comparisons. Supersedes SPEC.md §1.4 (which wrongly claimed trajectory
assertions as a Promptfoo gap).
**Reactivate when:** AC-019 (release) — fold into the README; **re-verify every competitor
row against promptfoo.dev first** (the doc says so, and their feature set moves fast).

### ~~SPIKE-001 live probe run~~ — DONE (AC-007)
Ran live against Anthropic; parallel calls confirmed elicited and order-preserved. Real
payloads captured to `tests/fixtures/anthropic/`. The OpenAI half remains for v0.2 (needs an
OpenAI key). The spike's `CANNED` dict was left as-is (frozen reference); AC-007's fixtures are
the source of truth.

### ~~`make smoke` — clean-machine onboarding test~~ — DONE (AC-016)
`scripts/measure_cold_start.sh` + `make smoke` / `make docker-smoke` measure install → `init` → `run`
and assert the total is under the 60s target (EPIC-001 success criterion 1). Docker is the fair
harness: **3s** measured in a clean Linux container.

### docs/how-to-add-an-assertion.md
**Why paused:** the assertion framework (AC-010) doesn't exist yet; a walkthrough now would
document vapor.
**Reactivate when:** AC-011 ships — then write the walkthrough against the real seventh
assertion (EPIC-001 success criterion 7: exactly two files touched).

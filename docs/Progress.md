# Progress

**Last Updated:** 2026-07-31

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

### AC-013 — Terminal reporter (implemented, uncommitted)
The `rich`-policy terminal reporter matching SPEC §7.2 (ARCHITECTURE §12); TDD, gate green
(238 tests + 1 live-skipped, ruff, mypy --strict, 5/5 contracts).
- `adapters/driven/reporting/terminal.py` — **pure** `render_report(run, *, color=False) -> str`
  (byte-pinned by a golden fixture) + `TerminalReporter.report(run, stream)` + `resolve_color`.
  `color=False` emits **zero ANSI** (CI logs / non-TTY / `NO_COLOR` / `--no-color`); `color=True`
  wraps only the pass/fail glyphs. Case line `  <glyph> <name:<36><turns> turns   <tok:,> tok
  <cost>   <dur>s`; summary `<n> cases   <p> passed   <f> failed   <cost>   <dur>s`.
- **Unknown cost → `—`, never `$0.0000`.** Non-`end_turn` termination surfaced on the case line
  (e.g. `max_turns_exceeded`). Failure blocks are AC-011's `render_failure` indented 6 spaces —
  the reporter **formats, does not compose**; it truncates long argument values (`expected`/
  `message`) but **never the trajectory line** (`actual`). Zero-case run → "no cases matched".
- **§7.2 deviation (noted):** the SPEC sample uses the v0.2 `min_tool_calls` and puts the count on
  `actual:` / the trajectory as the continuation. AC-011's v0.1 convention is the reverse
  (trajectory on `actual:`, reason as continuation). The golden reproduces §7.2's header, both case
  lines, and the summary **byte-for-byte**, and renders the failure block via the real v0.1
  machinery. Cost/duration golden tests have teeth at display resolution (mutation-verified).
- Per-case cost is still `None` (→ `—`) until AC-015 attaches `total_cost_usd` to the trace.

---

## Up Next

> Committed work, ready to start. Ordered by the EPIC-001 dependency graph.

1. **AC-014** — JSON reporter + full trace serialization (`--json-out`, `schema_version: 1`,
   sorted keys for diffable output). Depends on AC-013.
2. **AC-015** — CLI: wire composition — the deferred **spec→domain mock mapper + merge** into
   `PlannedCase`s, and the **per-case cost step** (`calculate` + `PricingCatalog` → `total_cost_usd`,
   which lights up the reporter's cost column).
3. **AC-016 / AC-018 / AC-019** — init scaffold, dogfood, release.

---

## Shipped

> Working in the codebase. Committed and tested.

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

### `make smoke` — clean-machine onboarding test
**Why paused:** `agentcheck init` doesn't exist yet (AC-016).
**Reactivate when:** AC-016 lands. Docker is the natural harness for EPIC-001 success
criterion 1 (`uvx agentcheck init` → green in <60s on a clean machine, no API key).

### docs/how-to-add-an-assertion.md
**Why paused:** the assertion framework (AC-010) doesn't exist yet; a walkthrough now would
document vapor.
**Reactivate when:** AC-011 ships — then write the walkthrough against the real seventh
assertion (EPIC-001 success criterion 7: exactly two files touched).

# Progress

**Last Updated:** 2026-07-30

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

### AC-007 — Anthropic adapter (implemented, uncommitted)
Production Anthropic Messages adapter (SPEC §3.1, §3.3), TDD; gate green
(185 tests + 1 live-skipped, ruff, mypy --strict, 5/5 contracts).
- `adapters/driven/providers/anthropic.py` — `to_wire`/`from_wire` (pure module functions, SDK-free)
  + `AnthropicGateway` (lazy SDK import in `__init__`; missing → actionable install-command error;
  `AsyncAnthropic` in `complete()`, times the call). Uses AC-002's `map_stop_reason`.
- **Blocker resolved:** ran `spikes/probe.py --provider anthropic` **live** (with the user's key
  via a gitignored `.env`) and captured **real** payloads → `tests/fixtures/anthropic/*.json`
  (single / parallel / text-only / max_tokens). Criterion 8 satisfied; the outstanding SPIKE-001
  live probe is now done.
- Offline unit tests for all five payload classes + parallel-order both directions + verbatim
  `raw` echo (mutation-verified) + `is_error` on the wire + unknown stop_reason→error + missing-SDK
  error. `@pytest.mark.live` two-turn exchange passed live (4.5s), skips without `ANTHROPIC_API_KEY`.
- **Reality vs spike:** the real single-call response carries **no** text block (spike assumed one),
  and error-then-retry returns `end_turn` text, not a tool retry. Real fixtures capture this.

---

## Up Next

> Committed work, ready to start. Ordered by the EPIC-001 dependency graph.

1. **AC-009 — the agent loop** — ALL prerequisites now done (AC-007 ✓, AC-008 ✓, AC-010 ✓).
   Wires config→gateway→mocks→assertions via `to_wire`/`from_wire`, `merge_mocks`, `MockResolver`,
   `registry.build`, `safe_evaluate`. The heart of the product.

---

## Shipped

> Working in the codebase. Committed and tested.

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

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

### AC-011 — Structural assertions (implemented, uncommitted)
The six v0.1 assertions on the AC-010 framework (SPEC §6, §6.1), TDD; gate green
(170 tests, ruff, mypy --strict, 5/5 contracts).
- `domain/assertions/structural.py` — `calls_tool` (bare name or `{tool, count}`),
  `not_calls_tool` (names turn + args), `tool_args` (deep subset; malformed args named with
  the raw string), `call_order` (subsequence), `max_turns`, `final_contains`
  (case-insensitive, list = all present, names which are missing).
- `domain/assertions/trajectory.py` — `render_trajectory` (`a → b → (termination)`) and
  `render_failure` (the ✗/expected/actual block). SPEC §6 example pinned byte-for-byte
  (`tests/fixtures/assertions/spec6_not_calls_tool.txt`).
- `registry.build(kind, raw)` uniform constructor; `registry` imports `structural` so the six
  self-register; dropped the `_V01_KINDS` seed (now purely registration-driven).
- **Reuse:** promoted `resolver._matches_when` → public `matches_subset`, shared by the mock
  resolver's `when` and `tool_args` so they can't drift. Updated one AC-010 test whose premise
  (calls_tool unregistered) the six now change.

---

## Up Next

> Committed work, ready to start. Ordered by the EPIC-001 dependency graph.

1. **AC-007** — Anthropic adapter (lifts `spikes/adapters.py`; live probe still outstanding)
2. **AC-009** — the agent loop (last loop prerequisite; wires config→gateway→mocks→assertions
   via `registry.build`, `merge_mocks`, `MockResolver`, `safe_evaluate`)

---

## Shipped

> Working in the codebase. Committed and tested.

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

### SPIKE-001 live probe run
**Why paused:** needs `ANTHROPIC_API_KEY` (and OpenAI key for the v0.2 half).
**Reactivate when:** before building AC-007 — the recorded shapes in `spikes/probe.py::CANNED`
must be confirmed against reality (`SPIKE-REPORT.md` §"The one thing still open").

### `make smoke` — clean-machine onboarding test
**Why paused:** `agentcheck init` doesn't exist yet (AC-016).
**Reactivate when:** AC-016 lands. Docker is the natural harness for EPIC-001 success
criterion 1 (`uvx agentcheck init` → green in <60s on a clean machine, no API key).

### docs/how-to-add-an-assertion.md
**Why paused:** the assertion framework (AC-010) doesn't exist yet; a walkthrough now would
document vapor.
**Reactivate when:** AC-011 ships — then write the walkthrough against the real seventh
assertion (EPIC-001 success criterion 7: exactly two files touched).

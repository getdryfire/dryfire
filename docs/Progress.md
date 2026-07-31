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

### AC-003 — Spec models (implemented, uncommitted)
Pydantic schema for suite + project-config files (SPEC §4), TDD; gate green
(57 tests, ruff, mypy --strict, 5/5 contracts).
- `adapters/driven/spec/models.py` — `ProjectConfig`, `Defaults`, `CassetteConfig`,
  `Suite`, `Case`, `MockRule`, `ToolSpec`. All `extra="forbid"`; overridable
  defaults are `| None` (resolution deferred to AC-005); `expect` entries stay
  `list[dict]` (assertion-kind check is AC-004's pre-pass).
- `MockRule`: `return`→`.returns` alias (`populate_by_name`); exactly-one of
  return/error/sequence via `model_fields_set` (correct even for `return: null`).
- **Interpretation:** criterion 1 ("§4.3 example validates") is tested with the
  `$ref` tool resolved inline, since the ticket says a raw `$ref` reaching these
  models is a caller bug (AC-004 resolves refs first).
- Drive-by: removed dead `protected_namespaces=()` from AC-002's ModelParams/
  CompletionRequest (verified no-op under pydantic 2.13; a field named `model`
  does not trigger the `model_` namespace warning).

---

## Up Next

> Committed work, ready to start. Ordered by the EPIC-001 dependency graph.

1. **AC-004** — spec loader with positioned errors (three-stage pipeline, lifts
   `spikes/locate.py`)
2. **AC-005** — project config + default resolution
3. **AC-006 — FakeProvider**, then the AC-007/008/010 fan-out per the sequencing diagram

---

## Shipped

> Working in the codebase. Committed and tested.

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

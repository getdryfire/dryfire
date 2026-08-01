# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`dryfire` — git-native regression testing for LLM agent tool loops. It runs YAML-defined
agent suites, executes the full tool-calling loop with deterministic mocked tools, and
asserts on the **trajectory** (ordered tool calls), not the final text. Local-first: no
server, no database, no account; exit codes are the API.

## Current state: scaffold complete (AC-001), domain not yet implemented

The `dryfire/` package exists as a layered skeleton (uv-managed, hatchling, flat layout)
with toolchain gates wired; no domain logic yet. Next ticket: AC-002. The repo contains:

- **Authoritative docs** — read in this order when context is needed:
  1. `SPEC.md` — product spec: domain model, YAML spec format, agent loop, assertions, CLI, exit codes
  2. `ARCHITECTURE.md` — how code must be shaped (supersedes SPEC §8's package layout; migration table in its §12)
  3. `EPIC-001.md` — v0.1 goal, success criteria, ticket sequencing
  4. `TICKETS-AC-001-009.md`, `TICKETS-AC-010-019.md` — implementation tickets, written as test tables
  5. `SPIKE-REPORT.md` + `FINDINGS_*.md` — spike results and amendments (note: `FINDINGS_2.md` is SPIKE-003 and `FINDINGS_3.md` is SPIKE-002)
- **Living docs** (keep these current):
  - `docs/Progress.md` — what's in flight / up next / shipped / on ice. Update when work ships or priorities shift.
  - `docs/Learnings.md` — session-discovered pitfalls and patterns. Read before starting work; append when you hit something non-obvious.
- **Spike prototypes** (`spikes/`) — frozen reference implementations to lift into the
  package per SPIKE-REPORT's "Code to lift" table, not throwaway code. Excluded from ruff:
  - SPIKE-001 (provider normalization): `neutral.py`, `adapters.py`, `probe.py`
  - SPIKE-002 (cassette fingerprint): `fingerprint.py`, `test_stability.py`
  - SPIKE-003 (spec error UX): `locate.py`, `render.py`, `sample_broken.eval.yaml`, `escalate_to_human.json`

## Commands

The Makefile is the front door (`make help` lists everything, categorized):

```bash
make setup            # uv sync --all-extras (dev tools live in the `dev` extra — plain `uv sync` won't install them)
make check            # THE gate: lint + typecheck + arch + test. Every ticket must pass it.
make test             # offline test suite (tests/ only; never needs an API key)
make lint / lint-fix / format / typecheck / arch
make test-live        # @pytest.mark.live tests; needs ANTHROPIC_API_KEY (pre-release only)
make add pkg=X / add-dev pkg=X / remove pkg=X / lock / sync
make spike-tests / spike-probe / spike-errors
```

Single test: `uv run pytest tests/unit/test_about.py -k <name>`. CLI: `uv run dryfire --help`.

Docker is a reproducible Linux toolchain + local CI matrix — deliberately NO service
containers, no production image (dryfire is a zero-infra CLI shipped to PyPI):

```bash
make docker-check     # full gate in a clean Linux container (Python 3.12)
make docker-check-313 # same on 3.13 — run the CI matrix locally
make docker-shell     # bash inside the container
```

The image keeps its venv at `/opt/venv` (`UV_PROJECT_ENVIRONMENT`) so the bind mount of
the repo can't shadow it with the host's macOS `.venv` — don't "simplify" that away.

The SPIKE-001 live probe (`uv run python spikes/probe.py --provider anthropic`) is still
outstanding and must run before AC-007.

PRs use `.github/pull_request_template.md` — fill every checklist (quality gate, scope
discipline, public contracts, docs) honestly; it mirrors the rules in this file.

## Architecture (binding once implementation starts)

Hexagonal, three layers, dependencies point inward — enforced by import-linter in CI:

- `domain/` — pure values (Trace, Turn, ToolCall, assertions, mock resolution, cost math).
  No I/O, no clock, no env, no SDKs. Pydantic is the **only** third-party import allowed.
  All models frozen. Domain functions return outcomes (`UNMOCKED`, `passed=False`,
  `TerminationReason`) — they never signal control flow via exceptions.
- `application/` — ports (`ModelGateway`, `SpecSource`, `Clock`, `EventSink`, …) and the
  agent loop / use cases. Imports domain and port protocols only, never a concrete adapter.
- `adapters/` — driving (CLI) and driven (Anthropic gateway, YAML loader, reporters as
  event sinks, pricing, clock). `composition.py` is the only module wiring concretes to ports.

Key rules that recur across tickets:

- **Ubiquitous language** (ARCHITECTURE §3): Suite / Case / Run / Turn / Trajectory / Trace /
  Termination / Assertion / Mock / Gateway / Cassette. Banned synonyms are checked in CI.
- **Assertion registry (OCP test):** adding an assertion = one new file + one registry entry.
  No `if kind == ...` chains outside a registry.
- **Exit codes are contractual:** 0 pass, 1 assertion failure, 2 spec/config error, 3 provider error.
- **Test doubles only at port boundaries** (`FakeGateway`, `FrozenClock`, …). Never mock a
  domain object — construct it. `unittest.mock` is banned outside `tests/contracts/`.
- **Everything runs offline:** the full test suite needs no network and no API key.
  Determinism is a requirement; a flaky test means a missing port.
- **`ruamel.yaml` round-trip is mandatory in the spec-loading path** (positions for error
  messages); `pyyaml` is banned there. Spec loading is three ordered stages:
  $ref/env pre-pass → assertion-kind registry check → pydantic; all errors collected and
  reported in one pass, with cascade suppression.
- Protocols and composition over inheritance: no ABCs where a `Protocol` works, max one
  inheritance level.

## Load-bearing spike findings (do not rediscover)

- Tool-call ids are **verbatim on the wire path** but **normalised to positional
  placeholders (`call_0`, …) on the cassette hash path**. Both must be implemented together.
- Anthropic requires the assistant turn echoed back verbatim → `Message.raw` passthrough.
- OpenAI can emit unparseable tool arguments → `arguments={}` + `malformed_arguments`
  preserved, never an exception; `tool_args` failures must say "malformed", not empty-dict mismatch.
- Adapters never raise on unknown stop reasons — map to `error`.
- Fingerprint rule: when stability and sensitivity conflict, **sensitivity wins** (tool
  descriptions and tool order are hashed).

## Scope discipline

v0.1 is Anthropic-only. Explicitly deferred (EPIC-001 §4): OpenAI adapter, cassettes, JUnit,
GitHub Action, retries, `llm_judge`, `compare`, HTML report, `repeat`, export, `passthrough`
mocks, streaming, any server or database. If a ticket seems to need one of these, stop and
flag it instead of building forward. v0.1 source target is ~3,500–4,500 lines; ARCHITECTURE
§11 lists tripwires (repository classes, event buses, DI containers, …) that mean delete something.

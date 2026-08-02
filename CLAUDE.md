# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`dryfire` — git-native regression testing for LLM agent tool loops. It runs YAML-defined
agent suites, executes the full tool-calling loop with deterministic mocked tools, and
asserts on the **trajectory** (ordered tool calls), not the final text. Local-first: no
server, no database, no account; exit codes are the API.

## Current state: v0.2 shipped — `dryfire 0.2.0` on PyPI (repo: `getdryfire/dryfire`)

Both epics are complete. **v0.1** was the local-first trajectory runner: Anthropic + a scriptable
fake, YAML spec + positioned-error loader, the tool-calling loop, deterministic mocks
(subset/errors/sequences), the six structural assertions, terminal + JSON reporters, advisory
cost, and the full `init`/`validate`/`run`/`trace` CLI. **v0.2 ("CI-grade")** added the OpenAI
adapter, cassette record/replay, retries, budget + extra assertions, the JUnit reporter, a GitHub
Action, and passthrough mocks — with a v0.1→v0.2 backward-compat test in CI.

**The load-bearing architectural rule** (governs all future work): caching and retrying are
decorators over `ModelGateway`; **`application/loop.py` does not change**. The one sanctioned
exception was the DF-211 passthrough seam — a single `await invoker.invoke(...)` branch, signed
off explicitly because non-blocking concurrent passthrough required a yield point there.

- **Authoritative docs** — read in this order when context is needed:
  1. `SPEC.md` — product spec: domain model, YAML spec format, agent loop, assertions, CLI, exit codes
  2. `ARCHITECTURE.md` — how code must be shaped (supersedes SPEC §8's package layout; migration table in its §12)
- **Living docs** (keep these current):
  - `docs/Progress.md` — what's shipped / up next / on ice. Update when work ships or priorities shift.
  - `docs/Learnings.md` — session-discovered pitfalls and patterns. Read before starting work; append when you hit something non-obvious.

(The v0.1/v0.2 epic + ticket definitions and the spike prototypes were historical planning
artifacts, pruned after v0.2 shipped; they live in git history if ever needed.)

## Commands

The Makefile is the front door (`make help` lists everything, categorized):

```bash
make setup            # uv sync --all-extras (dev tools live in the `dev` extra — plain `uv sync` won't install them)
make check            # THE gate: lint + typecheck + arch + test. Every ticket must pass it.
make test             # offline test suite (tests/ only; never needs an API key)
make lint / lint-fix / format / typecheck / arch
make test-live        # @pytest.mark.live tests; needs ANTHROPIC_API_KEY (pre-release only)
make add pkg=X / add-dev pkg=X / remove pkg=X / lock / sync
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

Deferred to v0.3+ (not built): `llm_judge`, `compare` (model/prompt matrix), a self-contained
HTML report, `repeat: N` flakiness measurement, export to other languages, streaming, and any
server, database, or hosted/account features — dryfire stays a zero-infra local CLI. If a change
seems to need one of these, stop and flag it instead of building forward. ARCHITECTURE §11 lists
tripwires (repository classes, event buses, DI containers, …) that mean delete something.

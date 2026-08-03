# dryfire/ — coding rules (source package)

You're editing dryfire's source. This is the **at-edit-time checklist**. The binding detail
lives in `/ARCHITECTURE.md` and the root `/CLAUDE.md` — **when this file disagrees with them,
they win.** Each rule carries a `→ §` pointer into `/ARCHITECTURE.md` for the full reasoning.

## The one gate

Every change must pass `make check` (lint + typecheck + **arch** + test). The test suite is
**offline and deterministic — no network, no API key.** A flaky test means a missing port, not a
retry. (→ §9, §10)

## Layer rule — dependencies point inward

`domain ← application ← adapters`. Import-linter enforces this in CI; you cannot import outward.
`composition.py` is the **only** module that wires concretes to ports — nothing else constructs an
adapter. (→ §1, §8, §10)

## `domain/` — pure values

- **Pydantic is the only third-party import allowed.** No I/O, no clock, no env, no SDKs. (→ §4.3)
- All models **frozen**. The domain is entirely value objects. (→ §4.1)
- Functions **return outcomes** (`UNMOCKED`, `passed=False`, `TerminationReason`) — they never
  signal control flow via exceptions. (→ §4.3)
- **Adding an assertion = one new file in `domain/assertions/` + one import line in
  `registry.py`.** Kinds are registration-driven; there are **no `if kind == …` chains** anywhere.
  A pure `llm_judge` reads a verdict the enrichment stage attached — it makes no model call. (→ §6.3)

## `application/` — ports + agent loop

- Import **domain and port Protocols only** — never a concrete adapter. Ports live in
  `application/ports/` and are `Protocol`s. (→ §5)
- **`loop.py` does not change.** Caching and retrying are decorators over `ModelGateway`
  (`adapters/driven/providers/{caching,retrying}.py`), not loop edits. The **one** sanctioned seam
  is the judging-enrichment `await` after `price(...)` in the scheduler. (→ §4.4, §9.3)

## `adapters/` — driven + driving

- Concrete I/O only (gateways, YAML loader, reporters, pricing, clock, cache, CLI).
- **Spec loading (`adapters/driven/spec/`) must use `ruamel.yaml` round-trip; `pyyaml` is banned
  there** (positions power the error messages). Loading is three ordered stages —
  `$ref`/env pre-pass → assertion-kind registry check → pydantic — and **all errors are collected
  and reported in one pass** with cascade suppression. (→ §2)

## Ubiquitous language — one term, one meaning

Suite · Case · Run · Turn · Trajectory · Trace · Termination · Assertion · Mock · **Gateway**
(never client/service/provider internally) · Cassette. Banned synonyms fail a CI check over source
**and** docs. Use these exact words in identifiers, YAML keys, CLI output, and error messages. (→ §3)

## Contracts that bite

- **Exit codes are the API:** `0` pass · `1` assertion failure · `2` spec/config error ·
  `3` provider error. Map failures to the right code; don't invent new ones. (→ root CLAUDE.md)
- **Test doubles only at port boundaries** (`FakeGateway`, `FrozenClock`, …). Never mock a domain
  object — **construct it.** `unittest.mock` is banned outside `tests/contracts/`. (→ §9.2)
- **Protocols over ABCs**; composition over inheritance; **max one inheritance level.** (→ §7.5)

## Stop if…

You reach for a repository class, an event *bus* (the catalog is fine), a DI container, or any
server/database/account seam. Those are §11 tripwires — they mean **delete something**, not build
forward. Flag it instead. (→ §11, root CLAUDE.md "Scope discipline")

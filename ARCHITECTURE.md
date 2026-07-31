# agentcheck — Architecture

**Companion to:** `SPEC.md` (what it does) · `EPIC-001.md` + `TICKETS-*.md` (how it gets built)
**This document:** how the code is shaped, and what the compiler and CI enforce.

---

## 0. Decisions up front

You asked for SOLID, OOP, TDD, DDD, Event Storming, Hexagonal/Clean architecture, and
design patterns. Adopting all seven wholesale would produce a worse tool, so here is the
honest split, with reasons. The rest of the document implements column 1.

| Practice | Verdict | Why |
|---|---|---|
| **Hexagonal (Ports & Adapters)** | **Adopt fully** | Near-perfect fit. This tool is a pure decision core surrounded by four kinds of I/O (LLM APIs, YAML files, terminal, cache). SPEC §3.1's `Provider` protocol is already a port. |
| **SOLID** | **Adopt** | Already ~80% satisfied by the spec. Making it explicit and enforced costs nothing. |
| **TDD** | **Adopt fully** | The domain is pure functions over data — the ideal TDD target. `FakeProvider` (AC-006) and offline-only tests are already specified. Tickets are already written as test tables. |
| **Ubiquitous language** | **Adopt** | The single highest-value part of DDD here. Trace/Turn/Trajectory/Termination must mean exactly one thing across code, YAML, docs, and error messages. |
| **Value objects & immutability** | **Adopt** | The domain model is entirely values. Frozen models eliminate a whole class of bug in a concurrent runner. |
| **Design patterns** | **Adopt, where emergent** | Named where they already arise. Not imposed. |
| **Event model** | **Adapt** | Keep the event *catalog* — it's the natural seam for reporting, cassettes, and v0.3 HTML/compare. Skip the event *bus*. |
| **Event Storming (workshop)** | **Decline** | It is a collaborative discovery technique for unknown business domains with domain experts in the room. You are one person, the domain is one you invented, and it is already specified in 766 lines. Running it solo is theatre — you would be discovering your own decisions. §6 keeps the useful output and skips the ritual. |
| **DDD tactical patterns** (aggregates, repositories, factories, specifications, anti-corruption layers) | **Decline** | These manage invariants across entity clusters under transactional consistency, in domains with competing subdomains and evolving business rules. This tool has no database, no transactions, no aggregate roots, one bounded context, and no domain experts. A `TraceRepository` over JSON files is ceremony with a cost and no benefit. |
| **CQRS / Event Sourcing** | **Decline** | No write model, no read model, no projections, no reason. |
| **DI container** | **Decline** | A composition root (§8) is 40 lines and does the whole job. |
| **Inheritance-based polymorphism** | **Decline as default** | Protocols and composition throughout. See §7.5. |

> **The real risk to this project is not under-architecture. It is a 4,000-line CLI wearing
> twelve layers of enterprise scaffolding and never shipping.** Every structure below has to
> earn its place; §11 lists the tripwires that say you have gone too far.

---

## 1. The shape

```
                        DRIVING (primary) ADAPTERS
                     ┌──────────────────────────────┐
                     │   CLI (typer)                │
                     │   [v0.3] compare  [v0.4] export
                     └──────────────┬───────────────┘
                                    │ calls
                     ┌──────────────▼───────────────┐
                     │      APPLICATION             │
                     │  use cases · agent loop      │
                     │  depends ONLY on ports       │
                     └──────────────┬───────────────┘
                                    │ uses
                     ┌──────────────▼───────────────┐
                     │        DOMAIN                │
                     │  Trace · Turn · ToolCall     │
                     │  assertions · mock resolution│
                     │  cost math · event catalog   │
                     │  PURE. No I/O. No SDKs.      │
                     └──────────────────────────────┘
                                    ▲
                                    │ implements
        ┌───────────────────────────┴───────────────────────────┐
        │              DRIVEN (secondary) ADAPTERS               │
        │  AnthropicGateway · FakeGateway · YamlSpecSource       │
        │  FileCassetteStore · TerminalSink · JsonSink           │
        │  BundledPricingCatalog · SystemClock                   │
        └────────────────────────────────────────────────────────┘
```

**The dependency rule, stated once:** dependencies point inward. Domain imports nothing
from application or adapters. Application imports domain and port *interfaces*, never a
concrete adapter. Only the composition root (§8) knows both sides. This is enforced by
`import-linter` in CI (§10) — an architecture that is only a diagram decays within weeks.

---

## 2. Package layout

This **supersedes SPEC §8**. Migration table in §12.

```
agentcheck/
  __about__.py              APP_NAME, __version__, CONFIG_DIR

  domain/                   ── pure. no I/O, no SDKs, no filesystem, no clock
    model/
      tooling.py            ToolDef, ToolCall, ToolResult
      message.py            Message, ModelResponse, StopReason, Usage
      trace.py              Turn, Trace, TerminationReason
      case.py               ResolvedCase, ResolvedSuite
    assertions/
      base.py               Assertion protocol, AssertionResult
      registry.py           kind -> Assertion
      structural.py         the six v0.1 assertions
      trajectory.py         the "a → b → (end_turn)" renderer
    mocking/
      resolver.py           MockResolver, UNMOCKED, subset matching
    pricing/
      calculator.py         Usage + rates -> Decimal | None   (pure)
    events.py               the event catalog (§6)
    errors.py               domain error types

  application/              ── orchestration. depends on ports only
    ports/
      model_gateway.py      ModelGateway          (driven)
      spec_source.py        SpecSource            (driven)
      response_cache.py     ResponseCache         (driven, v0.2)
      pricing_catalog.py    PricingCatalog        (driven)
      event_sink.py         EventSink             (driven)
      clock.py              Clock                 (driven)
    loop.py                 run_case — the agent loop
    scheduler.py            concurrent case execution
    usecases/
      run_suites.py         RunSuites             (driving)
      validate_specs.py     ValidateSpecs         (driving)
      trace_case.py         TraceCase             (driving)

  adapters/
    driving/
      cli/                  typer app, flag parsing, exit-code mapping
    driven/
      providers/
        anthropic.py        AnthropicGateway
        fake.py             FakeGateway           (shipped, not test-only)
        openai.py           (v0.2)
      spec/
        yaml_source.py      YamlSpecSource
        positions.py        Position, load_positioned, locate
        errors.py           SpecError, renderer
        models.py           pydantic spec schema
      cache/                FileCassetteStore     (v0.2)
      reporting/
        terminal.py         TerminalSink
        json_sink.py        JsonSink
      pricing/
        bundled.py          BundledPricingCatalog
      clock/
        system.py           SystemClock

  composition.py            ── the ONLY module that wires concretes to ports
  data/pricing.yaml
```

---

## 3. Ubiquitous language

One term, one meaning, everywhere: code identifiers, YAML keys, CLI output, error
messages, docs. Where a synonym is tempting, it is banned outright.

| Term | Meaning | Never call it |
|---|---|---|
| **Suite** | One `*.eval.yaml` file: shared system prompt, tools, mocks, and cases | test file, spec, scenario |
| **Case** | One executable scenario: input + expectations | test, example, sample |
| **Run** | One invocation of the CLI across N suites | session, job, execution |
| **Turn** | One model call plus the tool results it produced | step, iteration, round |
| **Trajectory** | The ordered sequence of tool calls across all turns | path, history, sequence |
| **Trace** | The complete record of one case's execution | log, result, output, record |
| **Termination** | Why the loop stopped | exit, end, finish, completion |
| **Assertion** | One expectation evaluated against a Trace | check, test, validation, rule |
| **Mock** | A declarative fake tool implementation | stub, fixture, double |
| **Gateway** | A port to an external model provider | client, service, API, provider* |
| **Cassette** | One recorded provider response | recording, snapshot, fixture, VCR |

\* "Provider" survives as the user-facing name in YAML (`provider: anthropic`) because it is
the industry term. Internally the port is `ModelGateway` to keep port and vendor distinct.

**Enforcement:** a banned-synonym check over source and docs runs in CI. Cheap, and it stops
the vocabulary rotting the moment a second contributor arrives.

---

## 4. Domain model

### 4.1 Everything is a value object

There are **no entities** in this domain. Nothing has an identity that persists across time
and mutation. A `Trace` is not a thing that changes — it is the immutable record of
something that already happened.

Consequences, all of which are load-bearing:

- Every domain model is `model_config = ConfigDict(frozen=True)`.
- Equality is structural. Two Traces with the same content are the same Trace.
- Concurrency (AC-012) is safe by construction: nothing shared is mutable.
- Assertions cannot corrupt the trace they inspect, even by accident.

The loop builds mutable local lists and freezes the `Trace` at assembly. Mutation is
confined to one function.

### 4.2 Pydantic in the domain — a deliberate compromise

Strict hexagonal says the domain has zero third-party dependencies. We import pydantic
anyway, because validation and serialisation *are* domain concerns here (`Trace` is the
public JSON artifact, AC-014), and hand-rolling both would be worse code for a purity
score.

The compromise is bounded: **pydantic is the only third-party import permitted in
`domain/`**, enforced by an import-linter contract. No `httpx`, no SDKs, no `ruamel`, no
`rich`. If pydantic ever needs replacing, the blast radius is the model layer only.

### 4.3 Domain purity rules

`domain/` may not: perform I/O · read the clock · read environment variables · generate
randomness · import from `application/` or `adapters/` · raise on malformed input where a
result type is possible.

That last one matters: domain functions return outcomes, they do not signal control flow by
exception. `MockResolver` returns `UNMOCKED`. Assertions return `passed=False`. The loop
returns a `Trace` with a `TerminationReason`. Exceptions are for programmer error only.

---

## 5. Ports

Six driven ports and three driving ports. That count is a budget — adding a seventh driven
port should require an ADR.

### 5.1 Driven (the domain's needs)

```python
class ModelGateway(Protocol):
    name: str
    async def complete(self, request: CompletionRequest) -> ModelResponse: ...

class SpecSource(Protocol):
    def load(self, patterns: Sequence[str]) -> tuple[list[ResolvedSuite], list[SpecError]]: ...

class ResponseCache(Protocol):                       # v0.2
    def get(self, fingerprint: str) -> ModelResponse | None: ...
    def put(self, fingerprint: str, response: ModelResponse, meta: CassetteMeta) -> None: ...

class PricingCatalog(Protocol):
    def rates(self, provider: str, model: str) -> Rates | None: ...

class EventSink(Protocol):
    def emit(self, event: RunEvent) -> None: ...

class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic_ms(self) -> int: ...
```

**On `Clock`.** It looks like over-abstraction and is not. Without it, latency and
timestamps make every trace non-deterministic, which breaks golden-file tests (AC-013),
byte-identical JSON (AC-014), and — critically — v0.2 cassette fingerprints. `FrozenClock`
in tests is what makes "two identical runs produce identical output" an achievable
acceptance criterion rather than an aspiration.

### 5.2 Driving (how the world invokes us)

```python
class RunSuites(Protocol):
    async def execute(self, request: RunRequest) -> RunResult: ...

class ValidateSpecs(Protocol):
    def execute(self, patterns: Sequence[str]) -> list[SpecError]: ...

class TraceCase(Protocol):
    async def execute(self, address: CaseAddress) -> Trace: ...
```

The CLI is *an* adapter over these, not the only possible one. A future library API or LSP
server is another driving adapter with zero domain change — that is the payoff, and it is
also why `cli.py` must contain no logic (AC-015).

### 5.3 Port contract tests

Every port gets **one test suite that every implementation must pass**, including the
fakes. `tests/contracts/test_model_gateway_contract.py` runs against `FakeGateway`,
`AnthropicGateway` (recorded fixtures), and later `OpenAIGateway`.

This is what keeps `FakeGateway` honest. A fake that drifts from real adapter semantics is
worse than no fake, because every test above it becomes a lie. It is also how SPIKE-001's
findings get permanently encoded: the contract suite asserts opaque ids, unknown stop
reasons mapping to `error`, and malformed arguments never raising — for *every* gateway,
forever.

---

## 6. The event model

This is the salvage from Event Storming. **Skip the workshop, keep the model.**

The loop already produces a natural sequence of events. Making them explicit gives one
seam that four features hang off, instead of four features each reaching into the loop.

### 6.1 Catalog

| Event | Emitted when | Carries |
|---|---|---|
| `RunStarted` | run begins | suite count, case count, config summary |
| `SuiteStarted` | suite begins | suite name, path |
| `CaseStarted` | case begins | case name, resolved model |
| `TurnStarted` | before a gateway call | turn index |
| `ModelResponded` | gateway returns | `ModelResponse`, latency, cache hit/miss |
| `ToolCallResolved` | a mock resolves a call | `ToolCall`, `ToolResult`, matched rule index |
| `TurnCompleted` | turn's results appended | turn index, cumulative usage |
| `CaseTerminated` | loop exits | `TerminationReason` |
| `AssertionEvaluated` | one assertion runs | `AssertionResult` |
| `CaseCompleted` | case fully processed | `Trace`, pass/fail |
| `SuiteCompleted` / `RunCompleted` | totals available | aggregates |

### 6.2 Consumers

| Sink | Consumes | Ticket |
|---|---|---|
| `TerminalSink` | Case/Suite/Run lifecycle + assertions | AC-013 |
| `JsonSink` | everything, buffers, writes atomically | AC-014 |
| `CassetteRecorder` | `ModelResponded` | v0.2 |
| `HtmlReportSink` | everything | v0.3 |
| `NullSink` | nothing (Null Object) | AC-012 |

### 6.3 Deliberate constraints

- **Synchronous. A list of sinks, not a bus.** `emit()` iterates and calls. No queue, no
  async dispatch, no pub/sub library, no event store. Adding one buys nothing in a
  single-process CLI and costs debuggability.
- **Events are facts, never commands.** A sink may not influence execution. `emit()` returns
  `None`.
- **A sink that raises is caught, logged once, and disabled** for the rest of the run. A
  broken reporter must never fail a run.
- **Events are not the source of truth.** `Trace` is. Events are a notification stream
  derived from it. This is explicitly *not* event sourcing.

The payoff is concrete: AC-013 and AC-014 become sinks rather than callers, the loop never
imports a reporter, and v0.3's HTML report and `compare` are new sinks over an existing
stream instead of surgery on the loop.

---

## 7. SOLID, concretely

Abstract principles are useless. Here is what each one forbids in *this* codebase.

**SRP** — `cli.py` parses flags and maps results to exit codes; it never runs a loop or
formats a table. `loop.py` orchestrates turns; it never decides pass/fail. Assertions judge;
they never format output (AC-013 formats what AC-011 composes).
*Violation smell:* a module that imports both a gateway and a reporter.

**OCP** — the assertion registry is the canonical case: a new assertion is one new file plus
one registry import, with no change to the loop, loader, or reporters. EPIC-001 success
criterion 7 tests exactly this.
*Violation smell:* an `if kind == ...` chain anywhere outside a registry.

**LSP** — every `ModelGateway` passes the same contract suite (§5.3). `FakeGateway` is
substitutable for `AnthropicGateway` in every test above the port.
*Violation smell:* `if isinstance(gateway, FakeGateway)`.

**ISP** — `ModelGateway` has one method. `Clock` has two. Ports stay small enough that a
fake is trivial to write; if a fake is tedious, the port is too fat.
*Violation smell:* an adapter implementing a port method with `raise NotImplementedError`.

**DIP** — `loop.py` imports `ports.model_gateway`, never `adapters.driven.providers.anthropic`.
Enforced mechanically (§10), not by discipline.
*Violation smell:* any `from agentcheck.adapters` line inside `domain/` or `application/`.

### 7.5 On OOP

"OOP" here means **protocols, composition, and small cohesive types** — not inheritance
hierarchies. Concretely: no abstract base classes where a `Protocol` works; no more than one
level of inheritance anywhere; no template-method base class for the loop; behaviour shared
by composition and plain functions.

The domain is data plus functions over data. Forcing it into class hierarchies would be
OOP-as-costume. Assertions are the test case: each is a small object with an args model and
an `evaluate(trace)` method — enough to register and configure, no base-class ceremony.

---

## 8. Composition root

One module, `composition.py`, is the only place where a concrete adapter meets a port. No DI
framework.

```python
def build_run_suites(config: ResolvedConfig, overrides: CliOverrides) -> RunSuites:
    clock     = SystemClock()
    catalog   = BundledPricingCatalog(config.pricing_file)
    gateway   = _build_gateway(config, clock)          # anthropic | fake
    if config.cassettes.mode != "off":                 # v0.2
        gateway = CachingGateway(gateway, FileCassetteStore(config.cassettes.dir))
    sinks     = _build_sinks(overrides)                 # terminal, json, null
    return RunSuitesService(
        spec_source=YamlSpecSource(),
        gateway=gateway,
        pricing=catalog,
        clock=clock,
        events=CompositeSink(sinks),
    )
```

Two things worth noticing:

- **`CachingGateway` is a decorator over `ModelGateway`**, not a branch inside the loop.
  Cassettes (v0.2) therefore land with *zero* change to `loop.py`. This is the clearest
  proof the port boundary is in the right place.
- Tests build their own graphs with fakes. They never import `composition.py`, which is
  precisely why it stays thin.

---

## 9. TDD workflow

### 9.1 Test taxonomy

| Layer | Location | Speed | Doubles used |
|---|---|---|---|
| Domain unit | `tests/unit/domain/` | microseconds | none — construct real values |
| Port contract | `tests/contracts/` | fast | the implementation under test |
| Application | `tests/unit/application/` | fast | fakes at every port |
| Acceptance | `tests/acceptance/` | ~1s | fakes at every port, real CLI |
| Live | `tests/integration/` | slow | none — `@pytest.mark.live`, skipped by default |

### 9.2 The rule that matters

**Test doubles exist only at port boundaries.** `FakeGateway`, `FrozenClock`,
`InMemorySpecSource`, `RecordingSink`.

Never mock a domain object — they are pure values, so construct the real one. Never
`unittest.mock.patch` an internal function: needing to means a seam is missing, and the fix
is a port, not a patch.

`unittest.mock` is banned outside `tests/contracts/` by a lint rule. This one constraint
prevents the most common way a hexagonal codebase rots into an untestable one.

### 9.3 The loop

Outside-in, per ticket acceptance criterion:

1. **Red** — write the acceptance test from the ticket's criterion. It fails.
2. Drop inward: write the failing unit test for the domain behaviour it needs.
3. **Green** — simplest implementation that passes.
4. **Refactor** — with both tests green.
5. Repeat until the acceptance test passes.
6. Run `ruff`, `mypy --strict`, `import-linter`. All must be clean before the ticket closes.

The tickets are already written as test tables (AC-009's twelve rows, AC-011's per-assertion
pass/fail pairs). **Those tables are your red step.** Write them all as failing tests first,
then make them pass one at a time.

### 9.4 Determinism budget

Every test must be deterministic. The mechanisms: `FrozenClock` for time, `FakeGateway` for
model responses, seeded ids in fakes, sorted keys in serialisation, spec-order results from
the scheduler. A flaky test in this codebase is a design defect, not an annoyance — it means
an unabstracted source of nondeterminism, which is exactly what the ports exist to remove.

---

## 10. Enforcement

Architecture that is only documented is aspiration. These run in CI and fail the build.

**`import-linter` contracts** (`.importlinter`):

1. *Layered:* `adapters` → `application` → `domain`. Reversals fail.
2. *Domain independence:* `domain` may import nothing from `application` or `adapters`.
3. *Domain third-party allowlist:* `domain` may import only `pydantic` and the stdlib.
4. *Application purity:* `application` may not import any module under `adapters`.
5. *Composition isolation:* only `composition.py` and `adapters.driving.cli` may import
   concrete driven adapters.

**Other gates:**

- `mypy --strict` on `agentcheck/`.
- `ruff` with a custom rule banning `unittest.mock` outside `tests/contracts/`.
- Banned-synonym check over source and docs (§3).
- Dogfood suite (AC-018) as a separate CI job.
- Coverage floor on `domain/` and `application/` only — adapters are covered by contract
  tests, and chasing coverage on adapters produces mock-heavy tests that assert nothing.

---

## 11. Tripwires

Signs the architecture has become the product. Any of these means stop and delete something:

- A `Repository` class. There is no database.
- An event *bus*, queue, or async dispatcher.
- A DI container or service locator.
- An interface with exactly one implementation and no test fake.
- An abstract base class where a `Protocol` would do.
- More than one level of inheritance anywhere.
- `domain/` importing anything that touches the network, disk, clock, or environment.
- A layer added "for future flexibility" with no ticket needing it.
- More architecture documentation than domain code.
- A file under 20 lines that exists only to satisfy a layer.

**The v0.1 target is roughly 3,500–4,500 lines of source.** If the structure above pushes it
past ~6,000, the structure is wrong, not the estimate.

---

## 12. Migration from SPEC §8

The layout in §2 supersedes SPEC §8. Mapping:

| SPEC §8 path | New path | Ticket affected |
|---|---|---|
| `providers/base.py` | `domain/model/*.py` + `application/ports/model_gateway.py` | AC-002 |
| `providers/anthropic.py` | `adapters/driven/providers/anthropic.py` | AC-007 |
| `providers/fake.py` | `adapters/driven/providers/fake.py` | AC-006 |
| `runner/trace.py` | `domain/model/trace.py` | AC-002 |
| `runner/mocks.py` | `domain/mocking/resolver.py` | AC-008 |
| `runner/loop.py` | `application/loop.py` | AC-009 |
| `runner/scheduler.py` | `application/scheduler.py` | AC-012 |
| `assertions/*` | `domain/assertions/*` | AC-010, AC-011 |
| `spec/*` | `adapters/driven/spec/*` | AC-003, AC-004 |
| `config.py` | `application/usecases/` + `adapters/driven/spec/` | AC-005 |
| `reporters/*` | `adapters/driven/reporting/*` (as `EventSink`s) | AC-013, AC-014 |
| `cli.py` | `adapters/driving/cli/` | AC-015 |
| `pricing.py` | `domain/pricing/calculator.py` + `adapters/driven/pricing/bundled.py` | AC-017 |
| — | `application/ports/*`, `composition.py`, `domain/events.py` | **new work** |

**Ticket impact.** Every ticket's **Files** section needs its paths updated. Three tickets
need more than a path edit:

- **AC-002** splits: pure models into `domain/model/`, the port into `application/ports/`.
- **AC-013 / AC-014** become `EventSink` implementations rather than reporters called after
  the fact. Their acceptance criteria stand; the interface changes.
- **AC-001** must add `import-linter`, the `.importlinter` contracts, and the layered package
  skeleton.

Two tickets should be inserted before AC-002:

- **AC-000a — Layered skeleton and import-linter contracts.** All five contracts written and
  failing-by-construction against a deliberate violation, proving the gate works before any
  domain code exists.
- **AC-000b — Port definitions and fakes.** All six driven ports, all three driving ports,
  and a fake for each, plus the contract-test harness. This unblocks TDD on every subsequent
  ticket.

---

## Appendix — ADRs

**ADR-001 · Hexagonal architecture.** *Accepted.* Four distinct I/O concerns around a pure
core; SPEC §3.1's provider protocol was already a port. Cost: one extra indirection per
external call. Benefit: `CachingGateway` proves v0.2 lands without touching the loop.

**ADR-002 · No repository pattern.** *Accepted.* No database, no transactions, no aggregate
identity. `SpecSource` and `ResponseCache` are ports named for what they do; wrapping file
reads in repository ceremony adds vocabulary without behaviour.

**ADR-003 · Event sinks, not an event bus.** *Accepted.* Single process, synchronous, one
producer. A list of sinks gives the decoupling; a bus would add asynchrony we cannot debug
and ordering guarantees we would then have to specify. Revisit only if a consumer needs to
run out-of-process.

**ADR-004 · No DI container.** *Accepted.* A ~40-line composition root covers the entire
graph. Containers pay off past roughly 50 registrations; we have ~10.

**ADR-005 · Pydantic permitted in the domain.** *Accepted with constraint.* Validation and
JSON serialisation are genuinely domain concerns here (`Trace` is a public artifact).
Constraint: pydantic is the *only* third-party import allowed in `domain/`, enforced by
contract 3. Trade-off accepted knowingly — this is the one place we depart from strict
hexagonal purity.

**ADR-006 · Test doubles only at ports.** *Accepted.* Domain objects are pure values and are
constructed, never mocked. `unittest.mock` is banned outside contract tests. This is the
single rule that most reliably prevents a hexagonal codebase from rotting into a
mock-assertion codebase.

**ADR-007 · Event Storming declined as a workshop.** *Accepted.* It is a collaborative
discovery technique for unknown business domains with domain experts present. Solo, on a
self-invented and already-specified domain, it discovers only its own inputs. The event
catalog (§6) captures the genuinely useful output; the ritual is skipped.

**ADR-008 · Frozen value objects throughout.** *Accepted.* No entity in this domain has
persistent identity. Immutability makes the concurrent scheduler safe by construction and
makes assertions incapable of corrupting the trace they inspect. Cost: the loop builds
mutable locals and freezes at assembly — mutation confined to one function.

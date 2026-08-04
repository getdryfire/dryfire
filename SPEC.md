# dryfire — Technical Product Specification

**Status:** Draft 1 — pre-implementation
**Owner:** Carlos
**License:** MIT
**Repo layout target:** single Python package, no monorepo, no services.

---

## 1. Product definition

### 1.1 One-liner

Git-native regression testing for LLM agent tool loops.

### 1.2 The problem

Every existing open-source LLM eval tool asserts on the **final text output** of a single-turn
prompt. Production agents are not single-turn and their failures are not textual. They fail by:

- calling the wrong tool
- calling the right tool with wrong arguments
- calling tools in the wrong order
- calling a destructive tool that should have been gated behind an escalation
- looping forever instead of terminating
- failing to recover when a tool returns an error

None of these are detectable by asserting on a final string. There is no widely-adopted
open-source tool that asserts on the **trajectory** — the ordered sequence of model turns,
tool calls, and tool results.

### 1.3 The wedge

Assert on the trace, not the output. Everything else in this spec is plumbing around that
one decision.

### 1.4 Positioning

How dryfire compares to other tools (Promptfoo, DeepEval) lives in `COMPARISON.md`. The design
commitments that positioning implies — and that must not be traded away:

1. **No server, no database, no account.** Everything is files on disk.
2. **Everything is git-diffable.** Specs are YAML, traces are JSON, cassettes are JSON.
3. **Exit codes are the API.** The tool's primary consumer is CI.
4. **Framework-agnostic.** Talks to provider SDKs directly. Never depends on LangChain,
   LlamaIndex, or any agent framework.

### 1.5 Non-goals (permanent)

- Production observability / tracing of live traffic
- Hosted dashboards, teams, auth, sync
- Dataset management, labeling UI, annotation queues
- Fine-tuning, RAG-corpus evaluation, vector store integration
- Being an agent framework

### 1.6 Adoption target

`uvx dryfire init` → passing green test in **under 60 seconds**, no API key required for
the scaffolded example (its model turns are scripted via `provider: fake` — §4.4; cassettes
are v0.2). This number is a hard acceptance criterion on the v0.1 release, not an aspiration.

---

## 2. Roadmap overview

| Version | Theme | Epic | Ships |
|---|---|---|---|
| **v0.1** | Trajectory runner | EPIC-001 | Anthropic provider, YAML spec, tool loop, mocks, 6 structural assertions, terminal reporter, `init` / `validate` / `run` / `trace` |
| **v0.2** | CI-grade | EPIC-002 | OpenAI adapter, cassette record/replay, JUnit + JSON reporters, GitHub Action, cost & latency assertions, retry/backoff |
| **v0.3** | Judgment & comparison | EPIC-003 | `llm_judge` assertion, `compare` command, HTML report, `repeat`/pass-rate flakiness measurement |
| **v0.4** | Portability | EPIC-004 | `export` — spec → runnable client code in Python / TypeScript / Ruby via Jinja templates |

Each version is independently shippable and independently announceable. v0.1 is the only
one that must exist for the project to have been worth doing.

---

## 3. Core domain model

These types are provider-agnostic and are the contract every other subsystem depends on.
They live in `dryfire/providers/base.py` and `dryfire/runner/trace.py`.

```python
# ---- Provider-normalized types -------------------------------------------

class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

class ToolDef(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict                      # JSON Schema

class ToolCall(BaseModel):
    id: str                                 # provider call id, OPAQUE
    name: str
    arguments: dict                         # parsed, never a JSON string
    malformed_arguments: str | None = None  # set when the provider emitted
                                            # unparseable arguments (SPIKE-001 Q2)

class ToolResult(BaseModel):
    call_id: str
    content: str | dict
    is_error: bool = False

class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str | list[dict] | None = None # provider-neutral blocks
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    raw: dict | None = None                 # provider-opaque passthrough.
                                            # Anthropic rejects a reconstructed
                                            # assistant turn; it must be echoed
                                            # verbatim (SPIKE-001 Q4).

StopReason = Literal[
    "end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "error"
]

class ModelResponse(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]              # may contain >1 (parallel calls)
    stop_reason: StopReason
    usage: Usage
    latency_ms: int
    raw: dict                               # untouched provider payload, for debugging

# ---- Trace types ----------------------------------------------------------

class Turn(BaseModel):
    index: int
    request_messages: list[Message]         # what was sent this turn.
                                            # LOAD-BEARING: v0.2 cassettes cannot
                                            # be built without it. Do not remove
                                            # as redundant (SPIKE-002 Q5).
    response: ModelResponse
    tool_results: list[ToolResult]          # resolved after this turn

TerminationReason = Literal[
    "end_turn", "max_turns_exceeded", "provider_error",
    "unmocked_tool", "max_tokens", "refusal"
]

class Trace(BaseModel):
    case_name: str
    suite_name: str
    turns: list[Turn]
    final_text: str | None
    termination: TerminationReason
    total_usage: Usage
    total_cost_usd: float | None
    duration_ms: int
    error: str | None = None

    def tool_calls(self) -> list[ToolCall]:
        """Flattened, in call order across all turns."""

    def tool_names(self) -> list[str]:
        """Ordered tool names — the primary surface for structural assertions."""
```

### 3.1 Provider protocol

```python
class Provider(Protocol):
    name: str

    async def complete(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[Message],
        tools: list[ToolDef],
        params: ModelParams,
    ) -> ModelResponse: ...

    def cost(self, model: str, usage: Usage) -> float | None: ...
```

A provider adapter has exactly two jobs: translate `Message`/`ToolDef` into the vendor's
wire format, and translate the vendor's response back into `ModelResponse`. It holds no
loop logic, no retry logic, no assertion logic.

**Critical constraint:** if a provider cannot be expressed through this protocol without
leaking vendor concepts upward, the protocol is wrong and must be fixed *before* more
features land on top of it. SPIKE-001 confirmed the protocol holds for Anthropic and
OpenAI with no loop, retry, or assertion knowledge in either adapter.

**Adapter obligations** (normative, from SPIKE-001):

1. Tool-call ids are **opaque**. Never parse them, never assume a prefix, never regenerate
   them. Correlation is by exact string match only.
2. An adapter that introduces a new tool-call id key name **must** register it in
   `cassettes/fingerprint.py::_CALL_ID_KEYS`. Anthropic uses `tool_use_id` on the result
   side where OpenAI uses `tool_call_id`; missing one silently breaks cassette replay from
   turn 2 onward.
3. An adapter **must never raise** on an unrecognised stop reason — map to `error`.
4. Ids are preserved **verbatim on the wire path** and normalised **only on the
   fingerprint path**. Two representations, one source of truth.
5. `ToolResult.is_error` is **lossy for OpenAI**, which has no error flag. The adapter
   encodes it into the result content via a named constant (`OPENAI_ERROR_PREFIX`), which
   the model then reads. Error-recovery behaviour therefore differs across providers for
   an identical spec. This is documented user-visible behaviour, not a bug to paper over.

### 3.2 Pricing data

Cost is computed from a bundled `dryfire/data/pricing.yaml` keyed by
`provider:model → {input, output, cache_read, cache_write}` in USD per million tokens.
Users may override with `pricing_file:` in project config. Unknown model → `cost = None`,
never an exception, never a guess. Stale pricing is a documented, accepted limitation;
cost assertions are advisory.

---

### 3.3 Stop reason mapping

Verified in SPIKE-001. Adapters implement this table; unknown values map to `error`.

| Neutral | Anthropic | OpenAI | Notes |
|---|---|---|---|
| `end_turn` | `end_turn`, `pause_turn` | `stop` | `pause_turn` collapsed |
| `tool_use` | `tool_use` | `tool_calls`, `function_call` | |
| `max_tokens` | `max_tokens` | `length` | |
| `stop_sequence` | `stop_sequence` | — | no OpenAI analogue |
| `refusal` | `refusal` | `content_filter` | **not equivalent** — see below |
| `error` | *(fallback)* | *(fallback)* | unknown values land here |

`refusal` and `content_filter` are different events: the former is the model declining, the
latter is a separate moderation layer intervening. Collapsing them loses that distinction.
Accepted for v0.1 because neither terminates a tool loop differently; the raw payload is
retained on `ModelResponse.raw` so a future `terminated_by_policy` assertion can recover it.

**Malformed arguments.** Anthropic returns parsed tool input; OpenAI returns a JSON
*string* that can be truncated (typically when generation hits `max_tokens` mid-argument).
Policy: never raise, never coerce silently. Set `arguments = {}` and preserve the raw
string in `malformed_arguments`. Non-JSON, valid-JSON-that-is-not-an-object, and empty
string all route here. Assertions that read arguments **must** report malformed arguments
as the cause rather than an empty-dict mismatch (see §6.1, AC-011).

---

## 4. Spec file format

### 4.1 Files

**Load pipeline (normative, from SPIKE-003).** Spec loading is three ordered stages and the
order is not an implementation detail:

```
load_positioned()   ruamel.yaml round-trip -> node tree carrying .lc positions
      ↓
PRE-PASS 1          $ref resolution + env interpolation; records its own errors
      ↓
PRE-PASS 2          assertion-kind registry check + did-you-mean suggestions
      ↓
MAIN PASS           pydantic structural validation
      ↓
locate() + render() error loc -> line/col -> caret output
```

Both pre-passes must run **before** pydantic. Models declare `extra="forbid"` and would
reject a raw `$ref` key outright, masking the real error; and assertion kinds are
registry-driven (§6.3), so pydantic cannot check them at all. All errors from all stages
are collected and reported in **one pass**, sorted by source position.

**Cascade suppression:** any error that causes a node substitution (e.g. a failed `$ref`
replaced by a placeholder) must suppress downstream errors under that loc prefix. One user
mistake produces one error.

| File | Purpose |
|---|---|
| `dryfire.yaml` | Project config at repo root. Defaults, provider settings, paths. |
| `**/*.eval.yaml` | Suite files. Discovered by glob. |
| `.dryfire/cassettes/**` | Recorded responses (v0.2). Committed to git. |
| `.dryfire/runs/**` | Run artifacts, JSON traces. Gitignored. |

### 4.2 Project config

```yaml
# dryfire.yaml
version: 1

defaults:
  provider: anthropic
  model: claude-sonnet-4-6
  max_turns: 10
  temperature: 0
  on_unmocked: error          # error | null | passthrough

suites:
  - "evals/**/*.eval.yaml"

cassettes:
  dir: .dryfire/cassettes
  mode: auto                  # auto | record | replay | off

pricing_file: null
```

### 4.3 Suite file

```yaml
# evals/refund_agent.eval.yaml
name: refund_agent
description: Refund policy enforcement for the support agent
tags: [support, safety]

model: claude-sonnet-4-6      # overrides project default
max_turns: 6
temperature: 0

system: |
  You are a support agent for an e-commerce store.
  Never issue a refund over $500 without escalating to a human first.

tools:
  - name: lookup_order
    description: Retrieve order details by order ID.
    input_schema:
      type: object
      properties:
        order_id: {type: string}
      required: [order_id]

  - name: issue_refund
    description: Issue a refund against an order.
    input_schema:
      type: object
      properties:
        order_id: {type: string}
        amount:   {type: number}
      required: [order_id, amount]

  - $ref: ./schemas/escalate_to_human.json    # reuse existing schemas

# Deterministic fake tool implementations. This is what makes runs reproducible.
mocks:
  lookup_order:
    - when: {order_id: "A-991"}
      return: {total: 780.00, status: delivered, customer_tier: standard}
    - return: {error: "order not found"}        # catch-all, no `when`

  issue_refund:
    - return: {refund_id: "R-1", status: "ok"}

  escalate_to_human:
    - return: {ticket_id: "T-55", status: "queued"}

cases:
  - name: escalates_refund_over_limit
    input: "I want a refund for order A-991, it arrived broken."
    expect:
      - calls_tool: lookup_order
      - tool_args:
          tool: lookup_order
          match: {order_id: "A-991"}
      - calls_tool: escalate_to_human
      - not_calls_tool: issue_refund
      - call_order: [lookup_order, escalate_to_human]
      - max_turns: 4

  - name: recovers_from_tool_error
    input: "Refund order A-100, it's only $20."
    mocks:                                       # case-level mock override
      issue_refund:
        - sequence:
            - error: "payment gateway timeout"   # first call fails
            - return: {refund_id: "R-2"}         # retry succeeds
    expect:
      - calls_tool: issue_refund
      - min_tool_calls: {tool: issue_refund, count: 2}
      - final_contains: "refund"
```

### 4.4 Field semantics

**`input`** — either a string (becomes one user message) or a list of `{role, content}`
objects for multi-turn setup.

**`tools[]`** — inline `ToolDef` or `{$ref: path}` pointing at a JSON file containing one.
Paths resolve relative to the suite file.

**`mocks`** — a mapping of `tool_name → list[MockRule]`, evaluated **in order, first match
wins**. A rule is:

```yaml
- when: {arg: value}      # optional. Deep SUBSET match on parsed arguments.
                          # Absent `when` = matches anything (catch-all).
  return: <any>           # value delivered as tool result content
  # OR
  error: "message"        # delivered as ToolResult(is_error=True)
  # OR
  sequence:               # consumed one entry per matching call, in order.
    - error: "..."        # Last entry repeats if calls exceed sequence length.
    - return: {...}
  # OR
  impl: pkg.mod:func      # (v0.2) passthrough — invoke real Python code. See §4.4a.
```

Exactly one of `return` / `error` / `sequence` / `impl` per rule. `sequence` is what makes
error-recovery testing possible and is a first-class feature, not an edge case.

Case-level `mocks` **merge over** suite-level mocks per tool name (whole tool's rule list
is replaced, not appended).

**`on_unmocked`** — when the model calls a tool with no matching rule:
- `error` (default) — terminate the trace with `termination: unmocked_tool` and fail the
  case with a message naming the tool and its arguments. Loud by design.
- `null` — return empty content, continue.

(A per-tool `impl:` rule is the v0.2 way to invoke real code — see §4.4a. A global
`on_unmocked: passthrough` fallback is reserved, not implemented in v0.2.)

#### 4.4a Passthrough mocks (`impl:`) — v0.2

A mock rule may carry `impl: package.module:function` instead of `return`/`error`/`sequence`.
dryfire imports the callable and invokes it with the tool arguments as **one positional dict**
(`func(args)`, never `**kwargs` — JSON keys aren't guaranteed valid identifiers); the return
value becomes the tool result. Sync callables run off the event loop (a thread) so they don't
serialise concurrent cases; async callables are awaited natively. A raise becomes an error
result and the run continues; each call is bounded by a timeout (default 30 s, or per-rule
`timeout_s`). `impl:` is resolved at **validate** time — a bad target is a positioned spec
error (exit 2) before any API spend — and importing the module runs its top-level code.
Passthrough results are **never cached**; a case using one is excluded from cassette recording
with a visible note. Full behaviour and the security posture: `docs/mocks.md`.

**Env interpolation** — `${VAR}` anywhere in a string value resolves from the environment
at load time. Missing var is a spec error, not an empty string.

**`provider`** — settable at the project default, suite, or run (`--model` is model-only)
level. Recognised values: `anthropic`, `openai`, `gemini`, `xai`, `moonshot`, `zhipu`,
`deepseek`, `openrouter`, `fake`, and any user-defined name declared in the `providers:`
block of `dryfire.yaml` (an OpenAI-compatible `base_url` + `api_key_env`; built-in names always
win). Each real provider needs its own `*_API_KEY` — see the
[provider matrix](docs/providers.md). Suite-level provider is what lets a keyless `fake` suite
and a real provider suite live in one project. A case whose real provider has no key in the
environment is **skipped** by `run` (a visible note, not a failure); `trace` surfaces it as an
error.

**`script`** — case-level, and only for `provider: fake`. It scripts the model's side of the
conversation, one entry per turn, so a suite runs deterministically with no API key. This is
what makes the `init` example green in seconds (§1.6) and what the dogfood suite runs on.
Each entry is exactly one of:

```yaml
script:
  - tool_call: {name: get_weather, arguments: {city: "SF"}}   # one tool call this turn
  - parallel:                                                 # several calls in one turn
      - {name: a, arguments: {}}
      - {name: b, arguments: {}}
  - text: "It's 65F in SF."                                   # a final text turn (end_turn)
  - fails: "provider exploded"                                # simulate a provider error
```

A `fake` case must have a `script`; a `script` on a real-provider case is meaningless. Tool
*results* still come from `mocks` — `script` only drives what the model asks for.

---

## 5. The agent loop

Implemented in `dryfire/runner/loop.py`. This is the single most important algorithm in
the product; it must be readable and directly testable without network access.

```
run_case(case, suite, provider, mocks) -> Trace

1.  messages ← build from case.input
2.  turn_index ← 0
3.  loop:
4.      if turn_index >= max_turns:
5.          termination ← "max_turns_exceeded"; break
6.      response ← await provider.complete(model, system, messages, tools, params)
7.      record Turn(index=turn_index, request_messages=copy(messages), response=response)
8.      if response.stop_reason != "tool_use":
9.          termination ← map(response.stop_reason); break
10.     results ← []
11.     for call in response.tool_calls:              # may be >1 — parallel calls
12.         result ← mocks.resolve(call)
13.         if result is UNMOCKED and on_unmocked == "error":
14.             termination ← "unmocked_tool"; break outer
15.         results.append(result)
16.     attach results to current Turn
17.     messages.append(assistant message carrying response.tool_calls)
18.     messages.append(tool result message(s)) — in the same order as calls
19.     turn_index += 1
20. assemble Trace: final_text, termination, summed usage, cost, duration
```

**Invariants that must hold and must have tests:**

- Parallel tool calls in one response produce tool results in **call order**, in a single
  follow-up message where the provider requires it.
- `max_turns_exceeded` is a normal termination, never an exception.
- A provider error after retries is captured into `Trace.error` and terminates with
  `provider_error` — the run continues to the next case.
- The loop never mutates the case spec.
- The loop is pure with respect to the mock resolver: swap in a resolver, get a
  deterministic trace, no network.

**Concurrency:** cases run under `asyncio` with a semaphore, default concurrency 4,
`--concurrency N` to override. Ordering of results in reports is spec order, not
completion order.

---

## 6. Assertions

An assertion receives the whole `Trace` and returns:

```python
class AssertionResult(BaseModel):
    kind: str
    description: str          # human-rendered, e.g. 'not_calls_tool: issue_refund'
    passed: bool
    message: str              # failure explanation; empty when passed
    expected: Any | None
    actual: Any | None
```

**Failure messages are the product's UX.** Every structural failure message must include
the actual ordered tool-call sequence. Example required output:

```
✗ not_calls_tool: issue_refund
    expected: issue_refund never called
    actual:   lookup_order → issue_refund → (end_turn)
              issue_refund called at turn 2 with {"order_id": "A-991", "amount": 780.0}
```

### 6.1 v0.1 assertion set

| Kind | Args | Passes when |
|---|---|---|
| `calls_tool` | `str` or `{tool, count}` | Tool appears in trace (optionally exactly `count` times) |
| `not_calls_tool` | `str` | Tool never appears |
| `tool_args` | `{tool, match, index?}` | Deep subset match of `match` against that tool's call arguments (first call unless `index` given) |
| `call_order` | `list[str]` | Names appear in this relative order (subsequence, not contiguous) |
| `max_turns` | `int` | `len(trace.turns) <= n` |
| `final_contains` | `str` or `list[str]` | Case-insensitive substring(s) present in `final_text` |

### 6.2 Later assertions

- v0.2: `cost_under: float`, `latency_under_ms: int`, `min_tool_calls`, `final_matches` (regex), `final_json` (pydantic-validated JSON shape)
- v0.3: `llm_judge: {rubric, model?, threshold?}`

### 6.3 Registry

Assertions self-register by kind string into `assertions/registry.py`. Adding one must
require touching exactly one new file plus a registry entry — no changes to the loop, the
spec loader, or reporters. Unknown assertion kind is a **spec validation error**, caught by
`validate` before any API call.

---

## 7. CLI

```
dryfire init [--dir .]              scaffold example project
dryfire validate [paths...]         parse + validate specs, zero network calls
dryfire run [paths...]              execute suites
dryfire trace <suite::case>         run one case, print full turn-by-turn trace
dryfire compare ...                 (v0.3)
dryfire export ...                  (v0.4)
```

`run` flags:

```
--filter TEXT            substring match on case name
--tag TEXT               filter by suite tag (repeatable)
--model TEXT             override model for this run
--concurrency INT        default 4
--cassette-mode MODE     auto|record|replay|off        (v0.2)
--reporter NAME          terminal|json|junit           (junit in v0.2)
--json-out PATH          write full traces as JSON
--junit-out PATH         write JUnit XML to a file      (v0.2; composes with any reporter)
--fail-fast              stop on first failing case
-v/--verbose             print traces for failing cases
```

### 7.1 Exit codes — contractual

| Code | Meaning |
|---|---|
| 0 | All cases passed |
| 1 | One or more assertion failures |
| 2 | Spec / config error (invalid YAML, unknown assertion kind, missing env var) |
| 3 | Provider or network error prevented execution |

These are part of the public interface. Changing them is a breaking change.

### 7.2 Terminal output

```
refund_agent  evals/refund_agent.eval.yaml

  ✓ escalates_refund_over_limit         3 turns   1,204 tok   $0.0041   2.1s
  ✗ recovers_from_tool_error            5 turns   2,890 tok   $0.0096   4.7s
      ✗ min_tool_calls: issue_refund >= 2
          expected: issue_refund called at least 2 times
          actual:   called 1 time
                    lookup_order → issue_refund → (end_turn)

2 cases   1 passed   1 failed   $0.0137   6.8s
```

Uses `rich`. Must degrade cleanly when not a TTY (no ANSI, no spinners) — CI logs are a
primary consumer.

---

## 8. Package layout

```
dryfire/
  __about__.py            APP_NAME, __version__
  cli.py                  typer app, flag parsing, exit codes
  config.py               dryfire.yaml loading, defaults resolution
  spec/
    models.py             pydantic models for suites and cases
    loader.py             YAML → models, $ref resolution, env interpolation
    errors.py             SpecError with file/line/col
  providers/
    base.py               Provider protocol + normalized types
    registry.py
    anthropic.py
    openai.py             v0.2
  runner/
    loop.py               run_case
    mocks.py              MockResolver, rule matching, sequences
    trace.py              Trace, Turn, TerminationReason
    scheduler.py          asyncio orchestration, semaphore, progress
  assertions/
    base.py               Assertion protocol, AssertionResult
    registry.py
    structural.py         v0.1 set
    budget.py             v0.2
    judge.py              v0.3
  cassettes/              v0.2
    store.py
    fingerprint.py
  reporters/
    terminal.py
    json_reporter.py
    junit.py              v0.2
    html.py               v0.3
  export/                 v0.4
    templates/
  scaffold/
    template/             files copied by `init`
  data/
    pricing.yaml
tests/
  unit/
  integration/            uses FakeProvider, no network
  fixtures/
```

### 8.1 Dependencies

Core: `typer`, `pydantic>=2`, `ruamel.yaml`, `rich`, `httpx`, `anyio`.

> **`ruamel.yaml` is a required core dependency, not optional.** Round-trip mode is the
> only practical source of line/column data for positioned validation errors (SPIKE-003).
> **`pyyaml` must not be used anywhere in the spec-loading path** — it discards position
> information. Measured overhead of round-trip loading on a 488-line suite is ~40 ms
> (2.2× `pyyaml`), which is negligible against a single provider call. Do not build a fast
> path.
Extras: `dryfire[anthropic]` → `anthropic`; `dryfire[openai]` → `openai`;
`dryfire[all]`.
Dev: `pytest`, `pytest-asyncio`, `ruff`, `mypy`, `uv`.

Provider SDKs are **optional extras**. Importing `dryfire` must not require any provider
SDK. A missing extra produces an actionable error naming the exact install command.

### 8.2 Testing strategy

- `FakeProvider` returns scripted `ModelResponse` sequences. Every loop, mock, and
  assertion test uses it. **The entire test suite runs offline with no API key.**
- One `@pytest.mark.live` integration test per provider, skipped without a key, run
  manually before release.
- Golden-file tests for terminal output.
- The repo runs its own eval suite against `FakeProvider` in CI — dogfooding as a test.

---

## 9. Version specifications

### v0.1 — Trajectory runner

**Ships:** everything in sections 3–8 marked v0.1.
**Provider:** Anthropic only.
**Definition of done:**
- `uvx dryfire init && dryfire run` produces a green result in <60s with no API key
  (scaffold ships a `FakeProvider`-backed example; a second example requires a key).
- Full test suite passes offline.
- README with runnable example above the fold and an asciinema GIF.
- Published to PyPI.

### v0.2 — CI-grade

- **OpenAI adapter** behind the existing `Provider` protocol. Zero changes to `loop.py`
  are permitted; if changes are needed, SPIKE-001 failed and the protocol is refactored
  first.
- **Cassettes.** Fingerprint = SHA-256 (truncated to 16 hex chars) over canonical JSON —
  sorted keys, no whitespace, NFC-normalised strings, `allow_nan=False`, int/float **not**
  unified — of a reduced request. Verified in SPIKE-002 (19 tests).

  **Hashed** — everything reaching the model: `schema_version`, `provider`, `model`,
  `system`, `messages` (id-normalised, see below), tool `name` + `description` +
  `input_schema` **in list order**, and `temperature` / `top_p` / `max_tokens` /
  `stop_sequences`.

  **Excluded** — API keys, headers, user-agent, request ids, timestamps, retry counts,
  adapter version, suite `name`/`description`/`tags`, case `name`, YAML position metadata.

  > **Tool `description` IS hashed.** It is prompt text the model reads and the primary
  > lever for steering tool selection. Excluding it means editing a description, re-running,
  > seeing green, and shipping a regression. **General rule: when stability and sensitivity
  > conflict, sensitivity wins.** A spurious re-record costs pennies; a false-stable replay
  > costs trust in every green run.

  **Tool order is hashed.** Tools are sent as an ordered list and position may influence
  selection; we cannot prove neutrality, and a needless re-record beats a stale replay.

  **Tool-call id normalisation is mandatory.** Provider call ids are minted fresh per
  request and echoed back from turn 2 onward. Hashed raw, every multi-turn cassette misses
  forever — the feature would demo correctly on single-call examples and fail on exactly
  the trajectories this product exists to test. Before hashing, rewrite every id to a
  positional placeholder (`call_0`, `call_1`, …) in first-appearance order. Applies to the
  **hash path only**; the wire path keeps ids verbatim (§3.1 obligation 4).

  `schema_version` is inside the hash input, so bumping it invalidates every cassette
  globally by construction — no migration code, ever.

  **Storage:** `.dryfire/cassettes/<suite>/<case>/<NN>-<fingerprint>.json`, where `NN` is
  the turn index. Each file carries a human-readable pretty-printed request digest
  alongside the raw response, so a stale cassette is debuggable rather than opaque hex.
  Renaming a suite or case orphans its cassettes; `dryfire prune` removes orphans.

  **Modes:**

  | Mode | Behaviour on miss |
  |---|---|
  | `auto` | record silently |
  | `record` | always call live, overwrite |
  | `replay` | **exit code 3**, naming the missing fingerprint and case. Never falls through to a live call. |
  | `off` | ignore cassettes entirely |

  `replay` never making a live call is what makes CI runs cost-bounded and airgap-safe.
- **Reporters:** JUnit XML (for CI test reporting), JSON.
- **GitHub Action** at `.github/actions/dryfire` + a documented workflow snippet.
- **Assertions:** `cost_under`, `latency_under_ms`, `min_tool_calls`, `final_matches`,
  `final_json` (a pydantic-validated JSON shape — required keys + per-field types — not full
  JSON Schema, chosen to avoid a runtime `jsonschema` dependency in the pure domain; DF-208).
- **Retries:** exponential backoff on 429/5xx, `--max-retries` (default 3), retries never
  counted as turns.
- **`passthrough` mocks** via `impl: pkg.mod:func`.

### v0.3 — Judgment & comparison

- **`llm_judge`** assertion: `{rubric, model?, threshold?}`. Judge calls go through the
  same `Provider` layer and are cassette-backed. Judge cost is reported separately from
  case cost — never silently folded into the total.
- **`compare`**: run one suite across N models or N prompt variants, emit a matrix
  (pass rate, cost, latency, mean turns per model). Terminal + HTML output. This is the
  single most shareable artifact the tool produces; design its output for a screenshot.
- **`repeat: N`** on cases: run N times, report pass rate `k/N`. Flakiness is a real agent
  failure mode and nothing else measures it. Interacts with cassettes: `repeat` forces
  `cassette-mode=off` for that case unless N cassette variants exist.
- **HTML report:** single self-contained file, no CDN, no build step.

### v0.4 — Portability

- **`export --lang python|typescript|ruby --out DIR`**: generate runnable client code for
  a suite's prompt + tool definitions.
- Templates are **Jinja2 files under `export/templates/<lang>/`**. Adding a language is
  adding a template directory — never a new code path in the exporter.
- Generated code covers: client construction, system prompt, tool schema declarations, and
  a tool-dispatch loop skeleton with `TODO` markers where real implementations go.
- Generated code is **not** round-trippable and this is documented. The YAML spec is the
  source of truth; export is a starting point, not a sync target.
- Every generated Python export is smoke-tested in CI (import + syntax check). TS and Ruby
  are syntax-checked only.

---

## 10. Open risks

| # | Risk | Status |
|---|---|---|
| 1 | The normalized `ModelResponse` leaks vendor concepts, forcing a v0.2 rewrite | **Retired** — SPIKE-001: protocol holds, 4 additive amendments applied. Live probe run still outstanding before AC-002 closes. |
| 2 | Cassettes invalidate on irrelevant changes, or replay stale responses | **Retired** — SPIKE-002: fingerprint verified, 19 tests. Id normalisation was the critical catch. |
| 3 | Spec validation errors are unreadable, killing the sub-60s onboarding target | **Retired** — SPIKE-003: positioned errors verified end to end. |
| 4 | Pricing data goes stale | Open — bundled data file, user override, cost always advisory |
| 5 | Scope creep into a platform | Open — §1.5 is binding |
| 6 | Provider error-recovery behaviour differs for identical specs (OpenAI `is_error` lossiness) | Accepted and documented, §3.1 obligation 5 |

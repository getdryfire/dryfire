# Changelog

All notable changes to dryfire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-08-02

"CI-grade" (EPIC-002). dryfire is now built to live in your merge gate: a second provider,
offline cassette replay, retries, budget/extra assertions, JUnit output, and a GitHub Action —
with **no breaking changes to the v0.1 spec** (a v0.1 suite runs unchanged; guarded by a
backward-compatibility test in CI).

The headline is architectural: **OpenAI support landed with zero changes to `application/loop.py`.**
Adding a second provider touched only a `to_wire`/`from_wire` adapter behind the `ModelGateway`
port — the strongest available evidence that the hexagonal boundary is real. Caching and retrying
are likewise decorators over that port; the loop never learned they exist.

### Added

- **OpenAI provider** (`dryfire[openai]`) — a second first-class gateway. Separate `role: tool`
  messages, defensively-parsed tool arguments (malformed args are preserved, never an exception).
- **Cassette record/replay** — `--cassette-mode auto|record|replay|off`. Replay serves every model
  turn from disk: CI runs free, offline, and deterministic with no API key. A content fingerprint
  keys each turn; see [`docs/cassettes.md`](docs/cassettes.md) for what invalidates one (and why
  tool descriptions are part of the key). `dryfire prune` removes orphaned/stale cassettes.
- **Retries with backoff** — exponential backoff + jitter on transient provider errors,
  `--max-retries` (default 3), honours `Retry-After`. A retried call is still one turn.
- **Budget assertions** — `cost_under` (fails loudly, and names the model, on an unpriced model)
  and `latency_under_ms`.
- **Extended assertions** — `min_tool_calls` (the retry-recovery assertion), `final_matches`
  (regex, compiled at validate time), and `final_json` (a pydantic-validated JSON *shape* —
  required keys + per-field types — no new dependency).
- **JUnit XML reporter** — `--reporter junit` (stdout) and `--junit-out PATH` (atomic file),
  independent of `--json-out`; a failing assertion shows the ordered trajectory in the PR check.
- **GitHub Action** — a composite `action.yml`; drop the under-10-line workflow from the README
  into any repo. Replay by default; gates the job on the exit code; renders JUnit as a check.
- **Passthrough mocks** — `impl: pkg.mod:func` invokes real Python code as a tool result. Sync
  callables run off the event loop, async natively; a bad `impl:` is a positioned validate error;
  passthrough results are never cached. See [`docs/mocks.md`](docs/mocks.md) for the security note.

### Fixed

- `dryfire run` now expands glob patterns in its CLI suite arguments
  (`dryfire run "evals/**/*.eval.yaml"`), consistent with `dryfire.yaml` — previously a literal
  path was assumed. A pattern matching nothing is a clean config error, not an internal error.

### Changed

- Composition order is `Caching(Retrying(Real))` — a cache hit returns before the retry layer.

## [0.1.0] — 2026-08-01

First release: the v0.1 trajectory runner (EPIC-001). Anthropic-only, local-first, offline.

### Added

- **CLI** — `init`, `validate`, `run`, `trace`, with contractual exit codes
  (`0` pass · `1` assertion failure · `2` spec/config error · `3` provider error).
- **`dryfire init`** — scaffolds a runnable example project that goes green in **under 60
  seconds with no API key and no network** (a keyless example whose model turns are scripted
  via `provider: fake`), plus a real Anthropic example that is skipped, not failed, when no
  key is present.
- **Agent loop** — drives the full tool-calling loop with deterministic mocked tools;
  parallel tool calls; every termination reason recorded, never raised
  (`end_turn`, `max_turns_exceeded`, `unmocked_tool`, `provider_error`).
- **Declarative tool mocking** — ordered rules, deep-subset `when` matching, error injection,
  and **sequences** (fail once, then succeed) for retry testing; case-level overrides.
- **Six structural assertions** — `calls_tool`, `not_calls_tool`, `tool_args`, `call_order`,
  `max_turns`, `final_contains`. The trajectory is shown on every failure.
- **YAML spec** — suites/cases with `$ref` and `${ENV}` interpolation; positioned spec errors
  (file, line, column, caret, and a did-you-mean for unknown assertion kinds), all collected
  in one pass.
- **Reporters** — a terminal reporter (TTY-aware colour, honours `NO_COLOR`) and a JSON run
  artifact (`--json-out` / `--reporter json`).
- **Concurrency** — bounded concurrent case execution (`--concurrency`), results in spec order,
  `--fail-fast`.
- **Advisory cost** — bundled pricing table; per-case cost, degrading to `—` for an unknown
  model rather than guessing. `--version` shows the pricing date.
- **Anthropic provider** as an optional extra (`dryfire[anthropic]`); importing dryfire never
  requires a provider SDK.
- **Dogfood suite** — dryfire runs its own eval suite against the fake provider in CI.

### Known limitations

- Anthropic only. OpenAI, cassettes, JUnit output, a GitHub Action, retries, `llm_judge`,
  `compare`, and cost/latency assertions are planned for v0.2+.
- Cost is advisory; stale pricing is an accepted, documented limitation.

[0.2.0]: https://github.com/getdryfire/dryfire/releases/tag/v0.2.0
[0.1.0]: https://github.com/getdryfire/dryfire/releases/tag/v0.1.0

# Changelog

All notable changes to dryfire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/csmatar/dryfire/releases/tag/v0.1.0

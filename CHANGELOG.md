# Changelog

All notable changes to dryfire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-08-04

**Model breadth.** Six new providers, plus user-defined ones — all speaking the trajectory
contract unchanged. The deterministic structural core (`application/loop.py`) did not move;
caching, retries, and every new provider remain decorators/data over the model gateway.

### Added

- **Gemini** provider — native `generateContent` over HTTP, needing **no SDK and no optional
  extra** (`provider: gemini`, key from `GEMINI_API_KEY`).
- **Grok (xAI)**, **Kimi (Moonshot)**, **GLM (Zhipu)**, **DeepSeek**, and **OpenRouter**
  providers — all OpenAI Chat Completions-compatible, reachable via `dryfire[openai]`. OpenRouter
  reaches many frontier and open-weight models behind a single key.
- **User-defined OpenAI-compatible providers** — declare any Chat Completions endpoint
  (self-hosted vLLM/Ollama, another aggregator, a private gateway) under a `providers:` block in
  `dryfire.yaml` and reference it by name from any suite.
- **Provider support matrix** documentation (`docs/providers.md`): the `provider:` value, wire
  family, install, API-key env var, and pricing per model.

### Changed

- The `dryfire[openai]` extra now also covers the OpenAI-compatible providers (Grok, Kimi, GLM,
  DeepSeek, OpenRouter) — no new dependency; they reuse the OpenAI adapter.

### Notes

- New providers are **additive**: existing suites, exit codes, YAML, and trace JSON are unchanged.
- Only Anthropic ships bundled pricing; every other provider reports advisory `—` rather than a
  guessed cost. Supply a `pricing_file` to add rates. Direct-key native wire quirks for the
  OpenAI-compatible providers are OpenAI-assumed (they are exercised via OpenRouter, which
  normalizes responses) — see the provider matrix.

## [0.3.2] — 2026-08-03

Docs/packaging patch (no code changes) — brands the project's public surfaces.

### Added

- A **project logo** on the README, and a **logo + favicon** on the documentation site.
- A fuller PyPI **project-links sidebar** — Homepage, Documentation, and Changelog now sit
  alongside Repository (`[project.urls]`).

### Changed

- The `--concurrency` / `--max-retries` help text now shows its default straight from the
  underlying constant, so `--help` can't drift from the actual default.

## [0.3.1] — 2026-08-03

Docs-only patch (no code changes) — refreshes the PyPI project page to point at the new
documentation site.

### Added

- A **getting-started guide** and a searchable **documentation site** (MkDocs + Material,
  deployed to GitHub Pages): <https://getdryfire.github.io/dryfire/>. The README now links to
  it; the site organises the existing per-feature docs behind a guided walkthrough.

## [0.3.0] — 2026-08-02

**Judgment & comparison.** Three capabilities for behaviour a structural check can't express
— all opt-in, none of it on the default path. A suite with no `llm_judge` and no `repeat` runs
at v0.2 speed and cost (benchmarked: `docs/benchmark.md`), and v0.1/v0.2 suites run unchanged
(CI backward-compat test). The load-bearing rule held: `application/loop.py` did not change —
judging is an enrichment stage *outside* the loop (`ARCHITECTURE.md` §4.4).

### Added

- **`llm_judge` assertion** — a rubric-graded assertion (`{rubric, model?, threshold?}`) for
  behaviour structure can't capture. The judge call routes through the same `ModelGateway`, so
  it's cassette-backed and retried for free; `temperature=0` always; an unparseable response or
  provider error is a distinct judge *error*, never a silent score of 0. Every verdict pins the
  judge-model version and a **rubric hash** so scores stay comparable over time. Judge cost is a
  **separate channel** — never folded into case cost, so `cost_under` stays blind to it.
  (`docs/judging.md`.)
- **`repeat: N`** — run a case N times and report a `k/N` pass rate with a Wilson 95% confidence
  interval, to catch flakiness a single run hides. `require_pass_rate` (default 1.0) governs the
  build verdict; a disagreeing case is surfaced distinctly. Each repetition records/replays under
  its own cassette key — five runs store five distinct responses, never one served five times.
  (`docs/flakiness.md`.)
- **`dryfire compare --models a,b,c` / `--prompts f1,f2`** — one suite across N models (or prompt
  variants) → a matrix (pass rate, cost, latency, mean turns per model), with disagreements made
  visually obvious. Orchestration over the existing runner; a failing model is an isolated failed
  column. A cost estimate is shown before execution and gated above a threshold (`--yes` to
  bypass). (`docs/compare.md`.)
- **Self-contained HTML report** — `dryfire report run.json [--html-out]` regenerates an offline
  HTML report (no CDN, no JS, opens from `file://`) from a JSON artifact with no re-execution;
  `compare --html-out` writes the matrix as a table. Expandable per-case failure detail with
  trajectory, tool args, assertion messages, and judge reasoning.
- The run JSON artifact is now `schema_version: 2` — additive (`judge_verdicts`, `judge_usage`,
  `judge_cost`, and repetition fields), so a structural-only run serialises identically to v0.2.

## [0.2.2] — 2026-08-02

Docs-only patch (no code changes).

### Added

- A demo GIF in the README (recorded from `docs/demo.tape`): `init` → `run` green → break a
  trajectory assertion → `run` red with the broken trajectory → fix → `run` green. Referenced by
  an absolute URL so it renders on both GitHub and the PyPI project page.

## [0.2.1] — 2026-08-02

Docs-only patch (no code changes) to refresh the PyPI project page.

### Fixed

- Removed a broken `docs/demo.gif` image reference from the README (the GIF was never recorded;
  it rendered as a broken image on PyPI and GitHub).
- README documentation links are now absolute URLs so they resolve on the PyPI project page
  (relative links 404 there). The CI-snippet example now points at `getdryfire/dryfire@v0.2.1`
  and `actions/checkout@v5` — the current, non-Node-20-deprecated versions.

### Changed

- Slimmed the README's "How it compares" section to a positioning paragraph plus a link to
  `COMPARISON.md`; dropped the Langfuse comparison (a different category — production
  observability); removed the superseded SPEC §1.4 positioning table. `COMPARISON.md` keeps the
  maintained, dated Promptfoo and DeepEval head-to-heads.

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

[0.4.0]: https://github.com/getdryfire/dryfire/releases/tag/v0.4.0
[0.3.2]: https://github.com/getdryfire/dryfire/releases/tag/v0.3.2
[0.3.1]: https://github.com/getdryfire/dryfire/releases/tag/v0.3.1
[0.3.0]: https://github.com/getdryfire/dryfire/releases/tag/v0.3.0
[0.2.2]: https://github.com/getdryfire/dryfire/releases/tag/v0.2.2
[0.2.1]: https://github.com/getdryfire/dryfire/releases/tag/v0.2.1
[0.2.0]: https://github.com/getdryfire/dryfire/releases/tag/v0.2.0
[0.1.0]: https://github.com/getdryfire/dryfire/releases/tag/v0.1.0

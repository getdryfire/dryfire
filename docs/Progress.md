# Progress

**Last Updated:** 2026-08-01 · **Active epic:** EPIC-002 (v0.2, CI-grade)

---

## How This Works

Global tracker for dryfire. Answers three questions without digging through the codebase:
1. What's actively being built?
2. What's shipped and working?
3. What's next?

**Epic reference:** `EPIC-001.md` (v0.1, **shipped** — AC-001…AC-019) and `EPIC-002.md` (v0.2,
active — DF-201…DF-212, tickets inline in that file). v0.1 is code-complete on `main` at version
`0.1.0`; the PyPI publish is deliberately deferred (owner's call).

Update this file when work ships, phases change, or priorities shift.

---

## In Development

> Actively building. Code is being written.

### DF-204 — CachingGateway decorator + four modes (implemented, PR open)
The ticket that proves the architecture: cassette record/replay lands as a **decorator over
`ModelGateway`** with **`application/loop.py` byte-for-byte unchanged** (verified). Gate green (358
tests + 1 live-skipped), dogfood green, loop unchanged.
- `adapters/driven/providers/caching.py` — `CachingGateway` wraps any `ModelGateway`. Modes: `off`
  (bypass), `auto` (miss→live+record), `record` (always live, overwrite), `replay` (hit→serve,
  **miss→`CassetteMiss`, never a live call**). Request reduced to the fingerprint form (`raw` stripped);
  provider from `inner.name`; `recorded_at` injected.
- **Event-model decision (was deferred to here):** cache-hit rides on **`ModelResponse.cache_hit`**
  (default `False`), set by the gateway. The loop only *stores* the response, so it never learns caching
  exists — no `EventSink` build, no loop change. Additive trace-JSON field (round-trip + schema
  unaffected). Terminal reporter shows `⚡N cached` **only when present** (existing goldens stay green).
- **Replay bypasses the credential check entirely** — no key needed. A `replay` miss raises
  `CassetteMiss`, which the loop already turns into `provider_error` → **exit 3** (no loop change). A
  `_NoLiveGateway` inner raises if a live call is ever attempted → airgap.
- Wired in `composition.py` (`--cassette-mode` flag > project `cassettes.mode` > `off`; store rooted at
  `cassettes.dir`). Acceptance test records a 2-turn suite then replays it with `make_gateway` patched
  to raise — green, proving a fully offline run incl. turn 2+ (the SPIKE-002 failure mode). Airgap +
  replay-miss both mutation-checked.

---

## Up Next

> Committed work, ready to start. Ordered by the EPIC-002 dependency graph (`EPIC-002.md`).

1. **DF-205** — `prune` command (delete orphaned/stale cassettes; dry-run by default). Needs DF-204.
2. **DF-201** — OpenAI gateway (independent; lifts SPIKE-001; `git diff application/` must be empty).
3. **DF-206** retries — needs a new **Clock port** (surfaced in review) so backoff tests don't wait.
   When it lands, composition wiring becomes `Caching(Retrying(Real))` (order is load-bearing).
4. Remaining: DF-207/208 assertions · DF-209 JUnit · DF-210 Action · DF-211 passthrough · DF-212
   release. Two half-day spikes first: SPIKE-004 (passthrough), SPIKE-005 (JUnit).

---

## Shipped

> Working in the codebase. Committed and tested.

### DF-203 — File cassette store (2026-08-01, PR #22)
The file-backed `ResponseCache`: declared the port + `FileCassetteStore`. Layout
`.dryfire/cassettes/<suite>/<case>/<NN>-<fingerprint>.json`, **reads keyed by fingerprint alone**,
atomic writes (temp + `os.replace`), stable-key JSON for small diffs, `schema_version` mismatch → miss.
Injective path sanitisation (`a/b`/`a:b`/`a_b` never collide). First `tests/contracts/` suite runs the
port contract against `FileCassetteStore` + an `InMemoryCache` fake.

### DF-202 — Request fingerprinting (2026-08-01, PR #21) — first EPIC-002 ticket
Lifted SPIKE-002's cassette fingerprint into `domain/fingerprint.py` (pure, stdlib-only, dict-based).
19 spike tests ported + 2 additions (cross-process subprocess determinism under `PYTHONHASHSEED=random`;
real 3-turn stability across different call-id sets). Tool-call ids normalised to positional
placeholders on the **hash path only**; tool descriptions + order hashed (sensitivity wins);
`SCHEMA_VERSION` inside the hash. Contract 3 (domain = pydantic + stdlib) kept.

### AC-019 — README, demo, and PyPI release (2026-08-01, PR #20) — v0.1.0, EPIC-001 complete
Version `0.1.0`. README leads with the differentiator + an authentic `not_calls_tool` failure block
above the fold; non-goals cite SPEC §1.5; fair Promptfoo/Langfuse comparison re-verified against
promptfoo.dev. `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/demo.tape` (vhs), and
`.github/workflows/release.yml` (PyPI Trusted Publishing on a `v*` tag). Wheel verified end-to-end
(clean-venv install → `init → run` green). **Publish is deferred by the owner** — record the GIF,
register the PyPI trusted publisher, and push the `v0.1.0` tag when ready.

### Rename: agentcheck → dryfire (2026-08-01, PR #19)
The name `agentcheck` was taken, so the project is now `dryfire`. Package dir, CLI command, dist
name, config file (`dryfire.yaml`), `CONFIG_DIR` (`.dryfire`), and every doc swept in one pass; GitHub
repo renamed to `csmatar/dryfire`; local folder + `.claude/settings.local.json` updated. Pure rename,
no behaviour change.

### AC-018 — Dogfood suite in CI (2026-08-01, PR #18)
dryfire runs its own eval suite against the fake provider — proving the tool works by using it,
offline, as a separate CI job (SPEC §8.2). Mutation-checked (break a pass-case → red; flip a fail-case
to pass → red). Runtime ~2s.
- `evals/self/{pass,fail,provider_error}.eval.yaml` — the six assertions passing and deliberately
  failing, all four terminations, and a `sequence` error-then-success recovery. Exit 0 / 1 / 3
  respectively.
- `scripts/run_dogfood.sh` — asserts each bucket's exit code, then parses the JSON to check **per-case**
  polarity (the aggregate exit code alone is blind to one fail-case quietly passing) + termination and
  sequence coverage. `make dogfood` + a separate `dogfood` CI job.

### AC-016 — `init` scaffold and the 60-second target (2026-08-01, PR #17)
`dryfire init` scaffolds a runnable example that goes green in **<60s with no API key and no
network** (SPEC §1.6). Measured cold start: **3s** in a clean Linux container (`make docker-smoke`),
4s locally.
- **New public spec surface (SPEC §4.4 amended):** `provider` is suite-level (a `fake` and an
  `anthropic` suite coexist); `script:` is a case-level field (tool_call / text / parallel / fails)
  driving a `provider: fake` case from YAML, mapped 1:1 to the `FakeGateway` helpers by
  `adapters/driven/spec/scripts.py`. New `ScriptStep` / `ScriptToolCall` models.
- **Per-case gateways:** a scripted `FakeGateway` is stateful, so `PlannedCase.gateway` overrides a
  run-level default `provider` (mirrors case-over-suite mocks); composition builds a fresh fake per
  fake-case in `_plan`. No churn to AC-012's tests.
- **Skip-on-missing-key:** `make_gateway("anthropic")` raises `MissingCredentials` with no key; `run`
  drops those cases with a visible note (exit 0), `trace` errors. The check lives in the seam tests
  already replace.
- **`init`:** `adapters/driven/scaffold/writer.py` copies `dryfire/scaffold/template/**` (ships in
  the wheel, read via `importlib.resources`), refuses to clobber without `--force`, prints one next
  command. Template: `dryfire.yaml`, keyless `hello.eval.yaml`, real `refund_agent.eval.yaml`
  (`$ref` schema, v0.1 assertions), `evals/README.md` — every top-level key commented (asserted).
- `scripts/measure_cold_start.sh` + `make smoke` / `make docker-smoke`.

### AC-015 — CLI surface and exit codes (2026-08-01, PR #16)
`run` / `validate` / `trace` with contractual exit codes (SPEC §7, §7.1) — the composition root that
exposes every library built so far. TDD, gate green (270 tests + 1 live-skipped, ruff, mypy --strict,
5/5 contracts).
- `composition.py` — the ONE module wiring concretes to the app (ARCHITECTURE §7): loader → resolve →
  **spec→domain mock map + merge** → scheduler → **price** → report → exit code. `cli.py` (typer)
  stays logic-free (parse flags → call composition → `typer.Exit(code)`).
- **Exit codes** (`0` pass · `1` assertion failure · `2` spec/config · `3` provider) — one test each.
  **Config is checked before anything network-touching**, so a spec error is `2` even when the
  provider is also unreachable. An unhandled internal exception → clean message + "please report" +
  exit `2`; `--debug` re-raises the traceback. (Provider errors surface as `provider_error`
  terminations from the scheduler → exit `3`.)
- `adapters/driven/spec/mocks.py` — **closes the deferred spec→domain mock mapper thread**
  (AC-005/009/012). `return: null` is mapped via `model_fields_set`; this surfaced that the domain
  `Return.value` / `ToolResult.content` were too narrow — widened both to `... | None` (a documented
  legitimate null tool result).
- **Cost is now wired end-to-end** (closes AC-017's thread): a `_price` post-pass computes
  `calculate(usage, catalog.rates(provider, model))` per case and attaches `total_cost_usd` — the
  reporter's cost column now shows real `$` values.
- Reporter selection: default terminal (+ `--json-out PATH` writes JSON too); `--reporter json` sends
  JSON to stdout and suppresses the terminal. `--filter`/`--tag` compose (AND); zero match → exit `0`
  with "no cases matched". `--model` overrides project+suite (highest-precedence override). `-v` dumps
  failing-case traces. Ruff: `typer.Option`/`Argument` added to bugbear `extend-immutable-calls`.

### AC-014 — JSON reporter and trace serialization (2026-08-01, PR #15)
- `adapters/driven/reporting/json_sink.py` — `render_run` / `write_run` / `deserialize_run`,
  `schema_version: 1`, complete Trace per case (incl. `Message.raw` + `malformed_arguments`), sorted
  keys, `allow_nan=False`, ISO-8601 `...Z` (injected timestamp), atomic temp-file+`os.replace` write.
  Round-trips to a `RunResult` that re-renders the terminal report. `tests/fixtures/run_schema.json`
  validated with `jsonschema` (dev-only). Atomicity mutation-verified.

### AC-013 — Terminal reporter (2026-07-31, PR #14)
- `adapters/driven/reporting/terminal.py` — pure `render_report(run, *, color=False) -> str`
  (byte-pinned golden) + `TerminalReporter` + `resolve_color`. Zero ANSI off a TTY / under
  `NO_COLOR` / `--no-color`; unknown cost → `—`; non-`end_turn` termination on the case line;
  failure blocks are AC-011's `render_failure` indented 6 spaces (truncates long args, never the
  trajectory). Golden matches SPEC §7.2's header/case-lines/summary byte-for-byte; the failure block
  uses the real v0.1 machinery (§7.2's sample was v0.2 `min_tool_calls`).

### AC-017 — Pricing data and cost computation (2026-07-31, PR #13)
- `domain/pricing/calculator.py` — pure `calculate(usage, rates) -> Cost | None`, **`Decimal`
  throughout**; unpriced model → None; cache tokens priced separately (input-rate fallback recorded).
  `application/ports/pricing_catalog.py` (`PricingCatalog`) + `adapters/driven/pricing/bundled.py`
  (`BundledPricingCatalog`, **exact match**, user `pricing_file` replaces+merges, `.updated`).
  `data/pricing.yaml` Anthropic list prices (quoted for exact Decimal), ships in the wheel.
  `--version` surfaces the pricing date. Only computes — wiring to the trace is AC-015.

### AC-012 — Concurrent case scheduler (2026-07-31, PR #12)
- `application/scheduler.py` — `run_suites(suites, provider, *, concurrency=4, fail_fast=False,
  on_progress=None) -> RunResult`. Worker-pool over a shared index iterator (task creation bounded to
  the concurrency); results assembled by index → **spec order regardless of completion order**.
  Three-level result `RunResult(suites, complete) → SuiteResult → CaseResult(trace, assertions,
  passed, error)`. **Evaluates assertions** per case (ARCHITECTURE §6.1); per-case isolation;
  `--fail-fast` cancels in-flight siblings and marks the run incomplete; fresh `MockResolver` per
  case. Spec→domain mock mapper re-assigned to AC-015. All 7 acceptance rows named tests.

### AC-009 — The agent loop (2026-07-31, PR #11)
- `application/loop.py` — `run_case(resolved_case, provider, resolver) -> Trace`. Drives the
  tool-calling loop with deterministic mocks; parallel calls resolved in call order; per-turn
  `request_messages` copies (load-bearing for v0.2 cassettes); usage summed. **Never raises for a
  normal outcome** — max_turns_exceeded / provider_error / unmocked_tool are recorded terminations.
  Imports domain + the `ModelGateway` port only (tests drive `FakeGateway`). All 12 acceptance rows
  are named tests. Added `tools: list[ToolDef]` to `ResolvedCase` (closes the tools half of AC-005's
  deferred thread); mocks stay a passed-in `MockResolver`.

### AC-007 — Anthropic adapter (2026-07-31, PR #10)
- `adapters/driven/providers/anthropic.py` — `to_wire`/`from_wire` (pure, SDK-free) +
  `AnthropicGateway` (lazy SDK import, `AsyncAnthropic`). Fixtures captured from REAL live payloads
  (criterion 8); live two-turn test passes, skips without a key. Closed the SPIKE-001 live probe.

### AC-011 — Structural assertions (2026-07-31, PR #8)
- `domain/assertions/structural.py` (the six: calls_tool/not_calls_tool/tool_args/call_order/
  max_turns/final_contains) + `trajectory.py` (render_trajectory + render_failure). SPEC §6 failure
  pinned byte-for-byte. `registry.build`; promoted shared `matches_subset`.

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
  production image, migrations — dryfire is zero-infra by design (SPEC §1.4)

### AC-001 — Project scaffold and toolchain (2026-07-30)
- uv-managed project, hatchling, flat `dryfire/` layout; version single-sourced from `__about__.py`
- Layered skeleton per ARCHITECTURE §2 (domain / application / adapters + composition seam)
- `.importlinter` with all five contracts, all KEPT; `mypy --strict`; ruff bans
  `unittest.mock` outside `tests/contracts/` (ADR-006)
- Typer CLI stub (`--help`, `--version`), name read from `APP_NAME`
- CI workflow: 3.12/3.13 matrix, no secrets — proves the suite is offline
- All six ticket acceptance criteria verified, incl. `import dryfire` with no provider SDK

### Spikes 001–003 (pre-scaffold)
- SPIKE-001 provider normalization, SPIKE-002 cassette fingerprint (19 tests),
  SPIKE-003 positioned spec errors — reference code in `spikes/`, results in `SPIKE-REPORT.md`

---

## On Ice

> Paused or deferred. Not abandoned.

### `COMPARISON.md` — positioning + feature matrix (for AC-019)
**Why parked:** it's release/README material — feature matrix by version and honest
Promptfoo/Langfuse comparisons. Supersedes SPEC.md §1.4 (which wrongly claimed trajectory
assertions as a Promptfoo gap).
**Reactivate when:** AC-019 (release) — fold into the README; **re-verify every competitor
row against promptfoo.dev first** (the doc says so, and their feature set moves fast).

### ~~SPIKE-001 live probe run~~ — DONE (AC-007)
Ran live against Anthropic; parallel calls confirmed elicited and order-preserved. Real
payloads captured to `tests/fixtures/anthropic/`. The OpenAI half remains for v0.2 (needs an
OpenAI key). The spike's `CANNED` dict was left as-is (frozen reference); AC-007's fixtures are
the source of truth.

### ~~`make smoke` — clean-machine onboarding test~~ — DONE (AC-016)
`scripts/measure_cold_start.sh` + `make smoke` / `make docker-smoke` measure install → `init` → `run`
and assert the total is under the 60s target (EPIC-001 success criterion 1). Docker is the fair
harness: **3s** measured in a clean Linux container.

### docs/how-to-add-an-assertion.md
**Why paused:** the assertion framework (AC-010) doesn't exist yet; a walkthrough now would
document vapor.
**Reactivate when:** AC-011 ships — then write the walkthrough against the real seventh
assertion (EPIC-001 success criterion 7: exactly two files touched).

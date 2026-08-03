# Progress

**Last Updated:** 2026-08-02 · **Status:** v0.3 in development (EPIC-003) — v0.2.2 on PyPI

---

## How This Works

Global tracker for dryfire. Answers three questions without digging through the codebase:
1. What's actively being built?
2. What's shipped and working?
3. What's next?

**Version:** `main` is at `0.2.0`, **published to PyPI** and tagged `v0.2.0`. Both epics (v0.1
AC-001…019, v0.2 DF-201…212) are complete; their ticket/spike planning docs were pruned after
release and live in git history.

Update this file when work ships, phases change, or priorities shift.

---

## In Development

> **EPIC-003 (v0.3 — Judgment & Comparison).** Scoped in `EPIC-003.md` (inline test-table
> tickets: SPIKE-006/007 → DF-301…310). Theme: measuring things that aren't boolean, without
> regressing the deterministic/free/never-flaky core (a structural-only suite must run at v0.2
> speed and cost).
>
> - **SPIKE-006 (async assertion seam) — DONE.** Verdict: **Model C** (judge as a pre-assertion
>   enrichment stage), mirroring the DF-207 `price(trace, case)` seam but async + gateway-backed.
>   Assertions stay pure and sync; `loop.py` unchanged; contract 3 kept. Reference impl +
>   8 passing proof tests in `spikes/006_async_assertions/`. See its `FINDINGS.md` for the 5
>   answers and the ARCHITECTURE §4.4 amendment.
> - **DF-301 (judge domain model) — DONE.** `domain/judging/{verdict,rubric}.py`: `JudgeVerdict`
>   with **required** `judge_model_version` + `rubric_hash` (a verdict without provenance is
>   unconstructable), and `Rubric.hash()` reusing `fingerprint.canonical_json` (stable across dict
>   key order, sensitive to any text/whitespace/threshold/examples change). `Trace.judge_verdicts`
>   added (additive, default `{}`); json-artifact `SCHEMA_VERSION` 1→2 (capability signal; trace def
>   was already permissive so the round-trip needed only the const bump). 12 new tests; 474 total.
> - **DF-302 (judge evaluator) — DONE.** `application/judging/evaluator.py`: `JudgeEvaluator` grades a
>   `Trace` against rubrics via the injected `ModelGateway` — same port as the agent under test, so
>   judge calls are cassette-backed + retried for free (proved with a real `CachingGateway`
>   record→replay test). `temperature=0` always; defensive parsing (markdown-fence tolerant) →
>   `JudgeVerdict.error` on unparseable/provider failure, never a silent score 0; single shared
>   semaphore bounds judge concurrency independently of case concurrency. Added the `error` field +
>   `from_score`/`from_error` factories to `JudgeVerdict` (deferred from DF-301). 12 new tests; 486 total.
> - **DF-303 (`llm_judge` assertion + the enrichment wiring) — DONE.** `domain/assertions/judge.py`:
>   pure `LlmJudge` reads a verdict keyed by `judge_key(model, rubric_hash)` and applies the threshold;
>   required non-empty `rubric` → positioned spec error at load (zero network); judge error and missing
>   verdict are distinct failures, never a silent pass. Failure message carries score/threshold/reasoning/
>   rubric-hash/trajectory. **Wiring (the sanctioned SPIKE-006 seam):** `scheduler._process_case` gained
>   one `await judge(...)` line after `price(...)` (mirrors DF-207); `application/judging/collect.py`
>   turns a case's `expect` into deduped `JudgeRequest`s; `composition._make_judge` closes over one shared
>   semaphore and grades through the case's own gateway (cassette-backed for free); `judge=None` for
>   structural-only runs (exact v0.2 path). Full offline e2e via a fake-provider script. `docs/judging.md`
>   carries the cost/variance/merge-gate warning. 19 new tests; 505 total.
> - **DF-304 (separate judge cost accounting) — DONE.** `Trace` gained `judge_usage`/`judge_cost` as a
>   distinct channel; `JudgeVerdict` carries per-call `usage`; the enrichment totals judge usage
>   (`sum_usage`) and prices judge cost by each verdict's own judge model, never folding it into
>   `total_usage`/`total_cost_usd`. **`cost_under`/`latency_under_ms` are blind by construction** (judge
>   calls are neither turns nor part of `total_usage`) — the regression test that is the point of the
>   ticket pins it. Terminal shows a separate `judge:` summary line, absent entirely for structural-only
>   runs (never a phantom `$0.0000`); JSON artifact keeps the channels apart. 8 new tests; 513 total.
>   **This closes the judge sub-track (DF-301→304); `llm_judge` is complete.**
> - **SPIKE-007 (repeat keying + pass-rate stats) — DONE.** Verdict: **the repetition index lives in
>   the storage key (`fp` for index 0, `fp#i` for i≥1), never in the hash** → `fingerprint()` is
>   untouched, so all 19 SPIKE-002 tests pass by construction and `repeat: 1` is byte-identical. Wilson
>   95% interval (`stats.py`, no dep) for `k/N`, shown only for disagreeing cases; recommended min N=5
>   (warn, never refuse). Partial-cassette policy per mode (replay refuses to fabricate missing reps →
>   exit 3). `repeat`×`compare` allowed+warned via DF-307's cost prompt (single source of truth). Full
>   prototype + 34 tests in `spikes/007_repeat/`; see its `FINDINGS.md`.
> - **DF-305 (`repeat: N` execution + pass rates) — DONE.** `repeat`/`require_pass_rate` resolve through
>   the spec (case/suite/defaults precedence; positioned errors for `repeat<1` / `rate>1`). The scheduler
>   expands each case into `repeat` units in the ONE worker pool (not a nested pool) and aggregates them —
>   `repeat: 1` returns the sole result unchanged (byte-identical to v0.2). `CaseResult` gained optional
>   `repetitions`/`require_pass_rate` + `passes`/`total`/`pass_rate` props; a case passes iff `k/N ≥
>   require_pass_rate`. Terminal: `~` glyph + `k/N` + Wilson 95% CI for disagreeing cases only, wide-interval
>   warning below N=5 (`domain/pass_rate.py`). JSON keeps all N traces (repeat:1 artifact byte-identical).
>   18 new tests; 531 total.
> - **DF-306 (repetition-aware cassette keys) — DONE.** `storage_key(fp, i)` in `domain/fingerprint.py`
>   (hash untouched → SPIKE-002's 19 tests pass unmodified); `CachingGateway` carries a per-run
>   `repeat_index` and keys via `storage_key`, so a multi-turn repetition keys all its turns under one
>   index. Composition sets a per-repetition `gateway_factory` (`_wrap_cases`); the scheduler passes the
>   deterministic repeat index (which is also the aggregation slot). **`repeat: 5` replay yields 5 DISTINCT
>   responses** (asserted individually), a committed v0.2 cassette fixture still replays (index 0 → bare
>   key), partial cassettes behave per mode (replay errors on missing, auto backfills, off bypasses), and
>   `prune` keeps/removes repetition cassettes by case validity (directory-based → no change). End-to-end
>   record→replay through `composition.run`: 5 distinct cassettes, 0 live calls on replay. 21 new tests; 544 total.
> - **This closes the `repeat` sub-track (SPIKE-007 + DF-305/306).**
> - **DF-307 (`compare` execution) — DONE.** `application/usecases/compare.py` is a pure, injected
>   orchestrator (`run_compare(axis, labels, run_one)`) OVER `run_suites` — no second runner; per column:
>   pass rate / total cost / mean latency / mean turns; a raised label is an isolated failed column, order
>   is request order. `composition.compare()` plans per label (model override, or `system` override for
>   `--prompts`), shows a pre-execution run estimate, and gates above a threshold (bypass `--yes`);
>   `--models`+`--prompts` refused. CLI `dryfire compare`. Basic per-column text output (DF-308 makes it a
>   matrix). `repeat`×`compare` allowed+warned via this estimate (SPIKE-007). 13 new tests; 557 total.
> - **DF-308 (compare matrix output) — DONE.** `adapters/driven/reporting/compare_terminal.py`: models as
>   columns, cases as rows, a summary block (pass rate / cost / mean latency per model). **Disagreement is
>   the finding** — a row where models disagree is marked with a `~` (a real character, grep-able in a CI
>   log, not just colour) and its cells stay `✓`/`✗`. Pure function, zero ANSI unless `color=True`; unknown
>   cost renders `—`; a failed column shows `FAILED` + `·` cells. Wide-matrix strategy: truncate long labels,
>   cap at 8 columns with a `--json-out` note (transposition rejected — documented). Golden-file test for the
>   3×5 two-disagreement matrix. Composition now renders the matrix (TTY-aware colour). 10 new tests; 566 total.
> - **This closes the `compare` sub-track (DF-307/308).**
> - **DF-309 (HTML report sink) — DONE.** `adapters/driven/reporting/html_sink.py`: `render_run_html` +
>   `render_compare_html` produce ONE self-contained file — inlined CSS, **no JS** (expandable detail via
>   native `<details>`/`<summary>`), no CDN/external refs → opens from `file://` air-gapped. The shell+CSS is
>   an embedded module constant, not a packaged template file (guaranteed in the wheel; no package-data risk
>   that would surface only after publish). Failing cases render open with full trajectory + tool args +
>   assertion messages + judge reasoning. `dryfire report run.json [--html-out]` regenerates from the JSON
>   artifact with no re-execution; `compare --html-out` writes the matrix as a table. <500KB/50 cases,
>   HTML-escaped, valid markup. **No loop/scheduler/existing-reporter changes** (git diff proves it). 9 new
>   tests; 575 total.
> - **DF-310 (docs + v0.3.0 release prep) — DONE (release owner-gated).** Version bumped to `0.3.0` +
>   CHANGELOG `[0.3.0]`. `docs/judging.md` expanded (judge drift: pinned versions, rubric hashing, why a
>   score under a different rubric hash isn't comparable); new `docs/flakiness.md`, `docs/compare.md` (with
>   the matrix screenshot), `docs/benchmark.md`. README gained an **additive** v0.3 section — centre of
>   gravity unchanged (still leads with deterministic structural testing). `COMPARISON.md` re-verified
>   (2026-08-02, competitor strengths stated: Promptfoo/DeepEval stay more mature on judging). Benchmark
>   (`scripts/benchmark_structural.py`): 50 structural-only cases, **0 judge activity, $0 cost** — no
>   regression. **v0.1 AND v0.2 backward-compat tests** (both suites run green on v0.3). 4 new tests; 577 total.
> - **REMAINING (owner-gated):** tag `v0.3.0` → `release.yml` publishes via Trusted Publishing. Do NOT tag
>   without the owner's go-ahead.

---

## v0.3 — EPIC-003 COMPLETE

All 10 tickets shipped (SPIKE-006/007 + DF-301…310), each its own merged PR, `make check` green
throughout. `application/loop.py` never changed. `llm_judge` (with rubric-hash provenance + separate cost),
`repeat: N` (Wilson interval, per-repetition cassette keys), `compare` (matrix, cost gate), and a
self-contained HTML report. Structural-only suites run at v0.2 speed and cost (benchmarked). Awaiting the
owner's `v0.3.0` tag to publish.

---

## Up Next

- **v0.3 remaining** (per `EPIC-003.md`): DF-301→304 (llm_judge), SPIKE-007 + DF-305/306 (repeat),
  DF-307/308 (compare), DF-309 (HTML report), DF-310 (docs + release). Still zero-infra — no
  server/database.
- **Housekeeping candidates:** bump release-workflow actions off deprecated Node 20; consider
  flipping `.github/workflows/example-usage.yml` from `workflow_dispatch` to `push`/`pull_request`
  now that `getdryfire/dryfire@v0.2.0` resolves.

---

## Shipped

### v0.2.0 released to PyPI (2026-08-02) — EPIC-002 complete
`dryfire 0.2.0` published via Trusted Publishing (`release.yml`) and tagged `v0.2.0`; verified with
`uvx dryfire@0.2.0`. DF-212 landed the docs (README "In CI" section, `docs/cassettes.md`,
`docs/ci.md`), the `COMPARISON.md` re-verification (Promptfoo acquisition confirmed; DeepEval section
added), the `[0.2.0]` CHANGELOG (leading with "OpenAI landed with zero changes to the loop"), and a
v0.1→v0.2 backward-compat test. The publish itself hit one transient ghcr.io image-pull timeout;
re-running the failed job fixed it (nothing double-published).

### Repo → `getdryfire/dryfire` (2026-08-02) — pre-release
Canonical home moved from the personal `csmatar/dryfire` to the **`getdryfire` org** (`dryfire` was taken)
so the public Action reference reads `uses: getdryfire/dryfire@v0.2.0`, not a username. Owner **created the
org and transferred the repo**; the 8 active references were updated (README badge + snippet, `docs/ci.md`,
`example-usage.yml`, `pyproject.toml` Repository, CHANGELOG tag links) and the working remote repointed to
`getdryfire/dryfire`. **Still owner-gated:** repoint PyPI Trusted Publishing at `getdryfire/dryfire` before
publishing. The historical rename note below (`csmatar/dryfire`, PR #19) is left intact as accurate record.

### DF-210 — GitHub composite Action (2026-08-02, PR #33) — **owner-verified in a throwaway repo**
Composite `action.yml` (install from `github.action_path`, works pre-PyPI) + `example-usage.yml` + `docs/ci.md`.
Replay default, JUnit-always via `--junit-out`, `if: always()` so the report renders on failure, exit-code
enforced last, inputs via `env:` (injection-safe), dorny/test-reporter pinned to a commit SHA. **Verified
live** by the owner: separate repo, cold-start ~7 s, failing case fails the job, JUnit renders in the PR check,
keyless replay.

### fix — `dryfire run` globs its CLI suite paths (2026-08-02, PR #34)
Surfaced by DF-210's throwaway-repo run: `dryfire run "evals/**/*.eval.yaml"` treated the glob as a literal
path (exit 2, "internal error"). `_load` now globs CLI paths (relative to cwd, `**` recursive), consistent
with `dryfire.yaml`; a non-matching pattern is a clean config error.

### DF-211 — Passthrough mocks (`impl: pkg.mod:func`) (2026-08-02, PR #32)
A mock rule can carry `impl: pkg.mod:func`; dryfire imports the callable and invokes it with the tool args.
**Loop seam (Option A, owner-approved):** domain resolver returns a pure `Passthrough` marker; the loop adds
one `await invoker.invoke(...)` branch (+14/−1) via a new async `ToolInvoker` port + `PassthroughInvoker`
adapter. Sync off-loop (non-serialising), async native; raise/timeout → error result; per-call 30 s timeout;
validate-time positioned error; passthrough cases excluded from cassette recording. `docs/mocks.md` + SPEC
§4.4/§4.4a. Reserved-but-unimplemented: `on_unmocked: passthrough`.

### DF-209 — JUnit XML sink (2026-08-02, PR #31)
SPIKE-005's Candidate A as an event-sink module (`junit_sink.py`): `render_junit` (`--reporter junit`) +
atomic `write_junit` (`--junit-out PATH`, parallel to `--json-out`). One `<failure>` per failing case (failed
assertions concatenated in the text body + one-line `message`); `<error>` for `provider_error`/`unmocked_tool`;
`→`/`✗` literal UTF-8. Golden byte-for-byte fixtures + JUnit XSD validation (new `xmlschema` dev dep).
Loop/scheduler/terminal untouched. SPEC §7 updated.


> Working in the codebase. Committed and tested.

### SPIKE-005 — JUnit XML mapping across CI consumers (2026-08-01, PR #30)
Settled the suite→case→assertion → testsuite→testcase mapping DF-209 implements (spike prototype since
pruned). **Verdict: Candidate A** — case = `<testcase>`, one `<failure>` per
failing case, failed assertions concatenated in the text body + a one-line `message` summary (= pytest's
shape, refined); `<error>` for `provider_error`/`unmocked_tool`. Load-bearing offline finding: newlines
survive in `<failure>` text but collapse to a space in the `message` attribute (XML 1.0 §3.3.3); `→`/`✗`
survive as literal UTF-8. Candidate C (N `<failure>` per testcase) silently drops assertions after the
first on Ant/Surefire parsers. The live-UI half (rendering/truncation) has a throwaway-repo capture kit in
`render_notes.md` (owner's hands, folds into DF-210).

### SPIKE-004 — Passthrough mock execution model (2026-08-01, PR #29)
Settled the execution model for `impl: pkg.mod:func` mocks (spike prototype since pruned; 17 tests) —
the verdict DF-211 implements. Resolve via `importlib`+`getattr` **at validate time** (bad
`impl:` = spec error before any API spend); **sync callables run in a thread**, async awaited natively;
raise → `ToolResult(is_error=True)`; **per-call 30 s timeout**; `func(args: dict)` convention; results
**not cacheable** (excluded from recording). Load-bearing finding: `asyncio.wait_for` bounds the *wait*
not the *work* — a wedged sync impl can't be killed, so the scheduler is bounded while the loop lives but
the process joins the abandoned thread at shutdown. **Flagged for DF-211:** the clean shape (async
`ToolInvoker` port + a `Passthrough` marker keeping the domain resolver pure) forces **one contained branch
in `application/loop.py`** — not the gateway "loop unchanged" rule (DF-201/204 only), so it needs the
owner's explicit sign-off.

### DF-208 — Extended assertions (`min_tool_calls`, `final_matches`, `final_json`) (2026-08-01, PR #28)
Three assertions (SPEC §6.2), one new file (`domain/assertions/extended.py`) + one registry line; loop
unchanged. `min_tool_calls` `{tool, count}` is the retry-recovery assertion. `final_matches` compiles its
regex **at validate time** (bad pattern = spec error, exit 2). `final_json` is **pydantic-native** (a
`required` + `fields` shape → `pydantic.create_model`) — no `jsonschema` dep, domain-pure, clean
unparseable-vs-shape errors. `final_matches` is **uncapped by design**: stdlib `re` holds the GIL, so an
in-process match timeout is impossible — a pathological pattern is the user's own regex (the no-sandbox
stance, same as [SPIKE-004] passthrough).

### DF-207 — Budget assertions (2026-08-01, PR #27)
`cost_under` (fails loudly + names the model on an unpriced model — advisory cost, SPEC §3.2) and
`latency_under_ms` (sums per-turn model latency; excludes mock/backoff). Added the OCP way (budget.py +
one registry line). **Enabling infra:** moved pricing into the scheduler (injected `price` callback +
new `Trace.model`) so assertions see cost **before** evaluation; `loop.py` unchanged.

### DF-206 — RetryingGateway + Clock port (2026-08-01, PR #26)
Transient-failure retries as a decorator over `ModelGateway`, `loop.py` unchanged — a retried call is
still one turn. New **Clock port** (+ `SystemClock`; a test `FrozenClock` asserts backoff in
microseconds). `is_retryable` on the port (classification in the adapter; Anthropic/OpenAI share a
duck-typed policy). Exponential backoff + jitter, `--max-retries`, honours `Retry-After`, exhausted →
`provider_error`. Composition order now `Caching(Retrying(Real))`.

### DF-201 — OpenAI gateway (2026-08-01, PR #25)
The second-provider proof of the hexagonal port: adding OpenAI changed **nothing** in `application/`.
Pure `to_wire`/`from_wire` + a thin lazy-SDK `OpenAIGateway`, mirroring Anthropic. SPIKE-001 facts:
separate `role: tool` messages, defensively-parsed JSON-string arguments (mutation-checked),
`OPENAI_ERROR_PREFIX` for is_error. Live test **passed against real gpt-4o-mini**.

### DF-205 — `prune` command (2026-08-01, PR #24)
`dryfire prune` deletes orphaned or stale cassettes (dry-run by default, `--yes` to delete; exit 0
either way). Classifies orphaned suite / orphaned case / stale schema_version; cleans emptied dirs.
**Safety rule (mutation-checked):** a cassette whose suite failed to parse is never pruned. Closed the
cassette workstream (DF-202→205). `_sanitise` promoted to public `sanitise`.

### DF-204 — CachingGateway decorator + four modes (2026-08-01, PR #23)
Cassette record/replay as a **decorator over `ModelGateway`** with **`application/loop.py` byte-for-byte
unchanged** — the architecture proof. Modes off/auto/record/replay (miss→`CassetteMiss`→exit 3, never a
live call). Cache-hit rides on `ModelResponse.cache_hit` (loop just stores the response; no `EventSink`
build); terminal shows `⚡N cached` only when present. Replay is keyless + airgapped (`_NoLiveGateway`
raises if a live call is attempted). `--cassette-mode` flag > project `cassettes.mode` > `off`. Acceptance
test replays a 2-turn suite fully offline; airgap + replay-miss mutation-checked.

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
  SPIKE-003 positioned spec errors — prototypes lifted into the package, then pruned

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

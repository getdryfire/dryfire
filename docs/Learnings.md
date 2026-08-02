# Project Learnings

Accumulated knowledge from development sessions. Read this before starting work — it
contains solutions and pitfalls discovered through real implementation, not theory.

---

## What Works

### Single quality gate via `make check`
`lint → typecheck → arch → test`, identical on host, in Docker (`make docker-check`), and
in CI. Every ticket closes only when this is green. Cheapest checks run first so failures
are fast.

### import-linter for third-party allowlists
Contract 3 (domain may import only pydantic + stdlib) needs
`include_external_packages = True` in `.importlinter` — without it, `forbidden` contracts
silently ignore non-project modules like `httpx` or `ruamel`.

### uv self-referential extras
`all = ["dryfire[anthropic,openai]"]` composes extras without duplicating version pins.
uv resolves it fine.

### Docker venv outside the bind mount
`UV_PROJECT_ENVIRONMENT=/opt/venv` in the image plus an anonymous volume over `/app/.venv`
in compose. Otherwise mounting the repo into the container shadows the Linux venv with the
host's macOS one and every binary breaks. (terms-pilot solves this with selective per-dir
mounts; a relocated venv is simpler for a single-package repo.)

---

## What Doesn't Work

### Zero-test pytest in CI
`pytest` exits **5** when no tests are collected, which fails the build. AC-001 said "zero
tests is acceptable" — it isn't, mechanically. Keep at least one smoke test.

### Typer `--version` without `invoke_without_command=True`
A callback-only Typer app with `invoke_without_command=False` rejects
`dryfire --version` with "Missing command" (exit 2). Eager options on the callback need
`invoke_without_command=True`.

### Plain `uv sync` for development
Dev tools live in the `dev` **extra** (per ticket AC-001's spec), not a PEP 735 dependency
group — so plain `uv sync` installs no pytest/ruff/mypy. Always `uv sync --all-extras`
(or `make setup` / `make sync`).

---

## Repo Gotchas

- Banned synonyms (ARCHITECTURE §3): don't say test/example for Case, log/result for
  Trace, step for Turn, client/service for Gateway. A CI check will eventually enforce
  this; write with the ubiquitous language now.
- Exit codes 0/1/2/3 are contractual (SPEC §7.1): 0 pass · 1 assertion failure · 2 spec/config
  error · 3 provider error. A spec error must be exit 2, never a crash/traceback.

---

## Domain modelling (AC-002)

### `mypy --strict` rejects bare `dict`/`list`
SPEC §3 writes fields as bare `dict`; strict mode needs type args. These hold parsed
JSON, so `dict[str, Any]` is the faithful annotation (`arguments`, `input_schema`,
`raw`, `content`). `Any` is fine under strict when explicit.

### A field named `model` does NOT need `protected_namespaces=()`
Pydantic's protected-namespace warning fires for fields starting with `model_`, not for a
field literally named `model`. Verified under pydantic 2.13.4: `class M(BaseModel): model:
str` emits no warning. AC-002 originally set `protected_namespaces=()` defensively on
`ModelParams`/`CompletionRequest`; it was a no-op and removed in AC-003. Only add it if a
field is genuinely named `model_<something>`.

### ModelGateway, not Provider
The port follows ARCHITECTURE §5.1 (`ModelGateway.complete(request: CompletionRequest)`,
no `cost()`), not SPEC §3.1's `Provider`. Cost is a separate `PricingCatalog` port at
AC-017. AC-007 (Anthropic adapter) implements this Gateway shape. Verify a stub conforms
with `uv run mypy --strict tests/unit/application/test_model_gateway.py` — `make typecheck`
only scopes to `dryfire/`, so the stub-vs-protocol check isn't in the standard gate.

## Spec schema (AC-003)

### `$ref` is resolved before pydantic, not by it
The spec models assume `$ref` tool entries are already inlined (AC-004 resolves them first);
a raw `$ref` reaching these models is a caller bug. So the "SPEC §4.3 example validates"
test uses the example with its `escalate_to_human` `$ref` expanded to the tool's JSON.

### `model_fields_set` for "exactly one of X/Y/Z"
`MockRule` needs exactly one of return/error/sequence. Detect via
`{"returns","error","sequence"} & self.model_fields_set`, not `is not None` — the latter
misfires on a legitimate `return: null` (null tool-result content). The aliased field
`returns` (YAML `return`) still appears under its field name in `model_fields_set`.

## Spec loader (AC-004)

### Pre-passes must run before pydantic
`$ref` resolution and env interpolation mutate the ruamel node tree *before*
`Suite.model_validate`, because `extra="forbid"` would otherwise reject a raw `$ref` key
and mask the real error. Order within pre-pass 1: refs first (so a `${VAR}` inside a
`$ref` target still gets interpolated), then env.

### Cascade suppression via poisoned loc prefixes
A failed `$ref` is replaced by an empty placeholder mapping; pydantic then emits
"missing name/input_schema" under that loc. Collect `{loc[:-1] for $ref errors}` and drop
any pydantic error whose loc starts with a poisoned prefix — one mistake, one error.

### Missing `${VAR}` substitutes "" but records an error
"Never an empty string" means never *silently* — so record a positioned `SpecError` and
substitute `""` only to keep the type valid so the pass can continue collecting.

### ruamel `.lc` gives token positions; missing keys have none
`locate()` walks the pydantic loc through CommentedMap/CommentedSeq; a `missing` error has
no token, so it degrades to the deepest resolved ancestor with `exact=False` (rendered
"(nearest enclosing node)"). ruamel.yaml ships type info — mypy --strict is clean, no stub
override needed.

### Golden-file test: normalize the path
`render()` embeds the suite path, which varies by CWD/host (e.g. `/app` in Docker). Replace
`str(fixture_path)` with the basename before comparing to the golden so the test is
location-independent.

## Config resolution (AC-005)

### The precedence chain needs case-level settings
The ticket's chain is override > case > suite > project > built-in, but AC-003's `Case`
had no settings fields (only `Suite` did) — so "case overrides suite" was untestable.
Extended `Case` with optional `model`/`max_turns`/`temperature`/`on_unmocked`. Additive and
safe: `extra="forbid"` still rejects unknown keys and existing valid suites are unaffected.

### Built-ins must cover provider + model, not just the numeric ones
The ticket enumerates `max_turns`/`temperature`/`on_unmocked`/`concurrency`, but "no None
fields remaining" + "a bare suite must be runnable" require `provider` and `model` built-ins
too. Used SPEC §4.2's canonical values (`anthropic`, `claude-sonnet-4-6`).

### ResolvedCase (domain) cannot carry spec MockRule
`domain/` may import only pydantic + stdlib (contract 3), so `ResolvedCase` can't hold the
adapter-layer `MockRule`/`ToolSpec`. It carries settings + identity + system/input/expect;
tools/mocks attach at the runner once AC-008 defines the mock domain model. Concurrency is
run-level, resolved by the scheduler (AC-012), not a `ResolvedCase` field.

### Pydantic frozen assignment raises `ValidationError` (not a plain exception)
`ConfigDict(frozen=True)` + attribute set → `pydantic.ValidationError` (`frozen_instance`).
Assert that specific type; ruff B017 forbids `pytest.raises(Exception)`.

### tmp_path discovery: compare with `.samefile`
macOS `tmp_path` lives under a `/var → /private/var` symlink, so a `discover_config` that
`.resolve()`s the start dir returns the `/private/var` form. Assert `found.samefile(expected)`
rather than `==` to stay symlink-agnostic.

## FakeGateway (AC-006)

### Terse script API: one helper reused two ways
`tool_call(name, args)` returns a call spec that works both as a standalone one-call turn in
`script([...])` and as an argument to `parallel(...)`. `text()`/`fails()` return whole-turn
entries. `FakeGateway.script([...])` is the classmethod constructor; `complete()` pops the
next entry per call. Keeps the surface small while covering text / single / parallel / failure.

### Deterministic tool-call ids
A per-instance counter yields `fake_call_0`, `fake_call_1`, … in call order across the whole
run. Two gateways with the same script produce identical ids — "unique within a run, stable
across runs" — which is what makes golden/cassette tests reproducible.

### Verifying protocol conformance under mypy
`make typecheck` only scopes to `dryfire/`, and nothing there binds a `FakeGateway` to a
`ModelGateway`-typed slot, so the conformance check lives in the test: a `_accepts(g:
ModelGateway)` call site plus `uv run mypy --strict tests/.../test_fake_gateway.py`. Same
pattern as AC-002's port stub.

## Mock resolver (AC-008)

### Two MockRule types is correct, not duplication
The spec `MockRule` (`adapters/driven/spec/models.py`) is a *parse model* — YAML `return`
alias, `extra="forbid"`, one-of validation. The domain `MockRule` (`domain/mocking/`) is a
*runtime value* — `when` + one concrete `Outcome` (Return/Error/Sequence). The domain
resolver can't import the adapter model (import contract 2/3), and the two serve different
jobs, so the split is right. The spec→domain mapper lives at the runner seam (AC-009).

### Sequence state lives in the resolver, not the rule
Rules are frozen values; the resolver holds `dict[(tool, rule_index) → next_pos]`. A fresh
resolver per case means concurrent cases (AC-012) never share sequence state. `min(pos, len-1)`
makes the last step repeat once exhausted.

### malformed_arguments can only match a catch-all
A `ToolCall` with `malformed_arguments` set skips every `when` rule (it has no parseable args
to subset-match) but still matches a `when=None` catch-all. Documented in `_matches`.

### When you implement ahead of the test, mutation-check it
Bundling `Sequence`/`merge_mocks` into the first module write meant those tests passed on
first run — proving nothing. Temporarily broke the sequence advance (`pos+1` → `pos`),
confirmed the test failed, restored. Cheap way to prove a test has teeth after an
out-of-order implementation.

## Assertion framework (AC-010)

### Keep registration conventions OUT of the Protocol
`Args` (each assertion's pydantic arg model) started in the `Assertion` protocol, which broke
`safe_evaluate` — its minimal test assertions only implement `evaluate`, so mypy flagged them
as "missing Args". The protocol should describe the *runtime interface* (`kind` + `evaluate`);
`Args` is a class-level registration convention accessed dynamically in `validate_args`
(`getattr(cls, "Args", None)`). After narrowing the protocol, toy classes satisfy it
structurally (no inheritance) and `mypy --strict` on the tests is clean — the actual proof of
"structural, not inheritance" (criterion 6). `make typecheck` only covers `dryfire/`, so
run mypy on the test files to verify conformance.

### Seed known-kind names to bridge a framework→implementation gap
AC-010 (framework) must keep AC-004's loader tests green, but the six real assertions are
AC-011. Fix: `registry._V01_KINDS` seeds the six *names* so `known_kinds()` recognises them
for spec validation, while `@register` adds real classes for `get`/`validate_args`. The loader
validates args only for *registered* kinds, so seeded-but-unregistered kinds are accepted
without arg-checking — AC-004 unaffected. AC-011 can drop the seed once all six register.

### Isolate the global registry in tests
`@register` mutates a module-global dict. A `registry_isolation` conftest fixture snapshots and
restores it (`.clear()`/`.update()` in place, since `registry.py` holds a by-reference alias)
so toy registrations in one test don't leak into another (or collide as duplicates).

## Structural assertions (AC-011)

### One shared subset matcher, not two
`tool_args` and the mock resolver's `when` are the same deep-subset match. Promoted
`resolver._matches_when` → public `matches_subset` and imported it in both, per the ticket's
"do not write a second one that can drift." A rename + one call-site update; AC-008 tests
stayed green.

### Failure rendering is byte-sensitive — generate then pin
`render_failure` must match SPEC §6 exactly (`✗`, `→`, and values aligned at column 14, with
continuation lines indented to match). Generated the output, eyeballed it against the spec,
then wrote the golden file — same characterize-then-pin flow as AC-004. `json.dumps` (not
`repr`) gives the double-quoted args the spec shows.

### Registering the six ripples outward — expect it
`registry` importing `structural` means the loader now arg-validates `calls_tool` etc., so
AC-004's fixture args had to be valid (they were: `calls_tool: lookup_order`, a bare string via
`RootModel[str | CountSpec]`). It also invalidated one AC-010 test that assumed `calls_tool`
was unregistered — updated it to a genuinely-unregistered kind. With the six always
registered, the `_V01_KINDS` seed became dead and was removed (`known_kinds()` is now purely
`frozenset(_REGISTRY)`).

### Scalar/union assertion args need RootModel
`calls_tool: lookup_order` (bare string) and `final_contains: [a, b]` (list) aren't dicts, so a
plain `BaseModel` can't validate them. `RootModel[str | CountSpec]` / `RootModel[str | list[str]]`
validate the raw scalar/union directly; dict-shaped args (`tool_args`) stay a `BaseModel` with
`extra="forbid"`.

## Anthropic adapter (AC-007)

### Real payloads differ from the spike's canned — always record live
The 2026 Anthropic response shape is richer than the spike guessed: `usage.cache_creation`
nested, `caller` on tool_use blocks, `stop_details`. More importantly the **behavior**
differs: a real single-tool-call response carries **no** text block (spike assumed one), and
error-then-retry returns `end_turn` prose rather than a tool retry. Criterion 8 ("fixtures from
real responses") exists precisely to catch this. Captured via a throwaway script that drives
the spike adapter's `to_wire` then dumps `client.messages.create(...).model_dump()`.

### Keep the SDK import lazy so the module imports without the extra
`to_wire`/`from_wire` are module-level functions importing only domain/app types; the
`anthropic` SDK is imported inside `AnthropicGateway.__init__` (→ actionable install-command
error if absent). So `import dryfire` and the offline unit tests need no SDK. Test the
missing-SDK path with `monkeypatch.setitem(sys.modules, "anthropic", None)`.

### Use AsyncAnthropic, not the sync client
`complete()` is async and the scheduler (AC-012) runs cases concurrently; a sync
`client.messages.create` would block the event loop and serialize them. `from_wire` takes
`latency_ms` as a param (measured around the call in `complete()`) so it stays pure/testable.

### Secrets: gitignore `.env` BEFORE the key is written
Added `.env` / `.env.*` (keep `.env.example`) to `.gitignore`, verified with
`git check-ignore .env`, then had the user create `.env`. Load it per-call with
`set -a; source .env; set +a` (shell state doesn't persist across tool calls) and never echo
the value.

## The agent loop (AC-009)

### Frozen Trace/Turn → build after resolving, not record-then-attach
SPEC §5's pseudocode records the Turn, then attaches tool results. Our `Turn` is frozen, so
`run_case` resolves the tool calls first and constructs the Turn once with its results. On an
unmocked-error break, the Turn carries the results resolved before the offending call.
Equivalent to the spec; no spec change needed.

### `request_messages` copies are cheap because Messages are frozen
The v0.2-cassette invariant ("each turn's `request_messages` is a copy taken before mutation")
is satisfied with a shallow `list(messages)` — the Message values never change, only the list
grows, so a fresh list per turn is fully isolated.

### The loop imports the port, never a concrete gateway
`application/loop.py` takes `provider: ModelGateway` and imports only that port (+ domain), so
import-linter stays green and tests drive `FakeGateway`. `run_case` never raises for a normal
outcome — provider exceptions are caught into `Trace.error` with `provider_error`.

### `tools` belongs on ResolvedCase; mocks don't
Closing AC-005's deferred thread: `tools` are domain `ToolDef`, so `ResolvedCase` can carry them
(populated in `resolve()` via ToolSpec→ToolDef). Mocks stay a passed-in `MockResolver` because
their rules map from the adapter's spec `MockRule` — that spec→domain mapping is composition/
AC-012, not the loop.

## Concurrent scheduler (AC-012)

### The scheduler evaluates assertions; it's the "run a case fully" use case
ARCHITECTURE §6.1 `CaseCompleted` carries `Trace` **and pass/fail**, and AC-013's reporter depends
on AC-011 assertion results with no ticket between them to run assertions. So `run_suites` builds
each `expect` entry via `registry.build(kind, entry[kind])` + `safe_evaluate` and sets
`passed = all(a.passed)`. Termination-driven failure (provider_error, max_turns_exceeded) and exit
codes are the reporter/CLI's job (AC-013/AC-015), kept out of the scheduler's `passed`.

### The spec→domain mock mapper can't live in the scheduler — layering forbids it
The scheduler is `application/` (ARCHITECTURE §12), which may import domain + ports only. The
adapter spec `MockRule` is off-limits, so `run_suites` takes **pre-planned cases** (`PlannedCase`
= `ResolvedCase` + already-mapped/merged domain mocks). The mapper + `merge_mocks` moved to AC-015
composition (Progress.md updated). Progress.md had pencilled the mapper into AC-012; the import
contract is dispositive.

### Worker-pool over a shared iterator bounds *task creation*, not just concurrency
`gather` over one-task-per-case parks N tasks on a semaphore — bounded by case count. Instead spawn
exactly `concurrency` worker tasks that pull from a shared `iter(range(n))`. `next()` has no `await`
between pulls, so in single-threaded asyncio no two workers ever get the same index — no lock
needed. This is what makes "50 cases at 4 without unbounded task creation" literally true (4 tasks,
not 50). Results written by index → spec order for free.

### Fail-fast = cancel siblings + `gather(return_exceptions=True)`
First non-passing case calls `.cancel()` on the other worker tasks (skipping
`asyncio.current_task()`), then returns. `gather(..., return_exceptions=True)` collects the
resulting `CancelledError`s instead of propagating. Cancelled workers never write their result →
`None` → dropped → fewer results than cases → `complete=False`. Critically, `_process_case` must
`except asyncio.CancelledError: raise` **before** its generic `except Exception`, or cancellation
gets swallowed into a bogus `CaseResult` and the run hangs. A 30s slow-case delay makes the test
prove cancellation: it passes in ~0s (cancelled), would hang 30s if fail-fast were a no-op.

### Concurrency-safe fakes are request-driven, not globally scripted
`FakeGateway.script([...])` pops entries from one shared list — under concurrency, which case gets
which entry is nondeterministic. For scheduler tests, write gateways that derive their response
from the *request* (message count → turn index; first user message → case id). Then each case's
behaviour is independent of interleaving. A `_DelayGateway` that `await asyncio.sleep`s a per-request
delay + records max in-flight + completion order covers bounded-concurrency and spec-order-vs-
completion-order in one helper.

### Determinism excludes `duration_ms` (Clock port still deferred)
`run_case` reads `time.monotonic()` directly (no Clock port yet — ARCHITECTURE lists it as new
work), so `Trace.duration_ms` is non-deterministic. The "two identical runs are equal" test compares
an `_essence()` projection (names, order, terminations, tool trajectories, assertion pass/fail),
not raw traces. The scheduler itself adds no other jitter — results are index-ordered, not
completion-ordered.

### Testing an "unexpected raise" for the isolation criterion
`run_case` catches every provider exception into `provider_error`, so a failing gateway does **not**
exercise scheduler-level isolation. A malformed `expect` entry (`{"__nope__": 1}`) makes
`registry.build` raise `KeyError` *inside* the scheduler (assertions are built per-case, not
upfront, precisely so a bad entry isolates rather than aborting the run) — the realistic injectable
raise for "one case raises, the other 9 complete."

## Pricing and cost (AC-017)

### AC-017 sequences BEFORE AC-013, not after
The EPIC-001 dependency graph routes AC-012/AC-011 → **AC-017** → AC-013 → AC-014 → AC-015; the
table lists AC-013's deps as "AC-011, AC-017". An earlier Progress.md "Up Next" had AC-013 first —
wrong. AC-017 depends only on AC-002 and gives AC-013's golden-file cost column real `Rates` to
draw on. Do AC-017 before AC-013.

### Hexagonal split: the ticket's flat `pricing.py` is three files
ARCHITECTURE §12 (line 510) maps `pricing.py` → `domain/pricing/calculator.py` (pure Usage+Rates→
Decimal|None) **+** `adapters/driven/pricing/bundled.py` (`BundledPricingCatalog`). Add the
`application/ports/pricing_catalog.py` port (`rates(provider, model) -> Rates | None`) so the
calculator stays pure domain and the catalog (which does I/O) is a driven adapter. `Rates`/`Cost`
live in the domain calculator; the port imports them (application → domain is allowed).

### Decimal from the YAML boundary, not just in arithmetic
Criterion 6 ("sum 1000 costs, no float drift") is about arithmetic — Decimal solves that. But a bare
`0.30` in YAML loads as a float and `Decimal(0.30)` carries the float's dust. Fix: **quote every
rate as a string** in `pricing.yaml` so pydantic parses `Decimal("0.30")` exactly. `Rates.cache_read`
is `Decimal | None` (Optional) even though the bundled file always sets it — the None path is the
"model without cache pricing" case (charge cache reads at the input rate, flag it on `Cost`).

### Exact match only — a near-miss must return None
SPEC §3.2 and the ticket are explicit: no prefix/fuzzy matching. `claude-sonnet-4-6-typo` → None,
not the closest real model. A silent wrong price is worse than an honest `—`. The catalog is a plain
`dict[str, Rates].get(f"{provider}:{model}")`.

### The CLI may import a driven adapter; domain/application may not
`--version` reads `BundledPricingCatalog().updated`. Contract 5 (composition-isolation) forbids
`dryfire.domain` and `dryfire.application` from importing `dryfire.adapters.driven` — the
**CLI (`adapters.driving`) is not in that source list**, so the import is legal (the contract note
even says "only composition.py and the CLI may import concrete driven adapters"). Keep the SDK-free
bundled loader's file read lazy (in `__init__`, not at import) so `import dryfire` stays cheap.

### Package data ships by default under hatchling
`data/pricing.yaml` is included in the wheel with no extra `force-include`/`artifacts` config —
`[tool.hatch.build.targets.wheel] packages = ["dryfire"]` pulls in non-`.py` files under the
package. Verified with `uv build --wheel` + `unzip -l`. Access it via
`importlib.resources.files("dryfire").joinpath("data/pricing.yaml")` (robust for editable *and*
wheel), not a `__file__`-relative path.

### Consult the claude-api skill for model prices — don't guess
The bundled table needed real Anthropic list prices. The `claude-api` skill's model table is the
source (Opus 4.8/4.7/4.6 $5/$25, Sonnet 5/4.6 $3/$15, Haiku 4.5 $1/$5). Cache convention from the
same skill: cache-read 0.1× input, cache-write 1.25× input (5-min TTL). v0.1 is Anthropic-only, so
only `anthropic:*` keys — and the builtin model `claude-sonnet-4-6` must be present so a bare suite
prices.

## Terminal reporter (AC-013)

### The §7.2 sample predates the v0.1 assertion convention — reproduce layout, not content
SPEC §7.2's failing block uses `min_tool_calls` (a **v0.2** assertion) and puts the *count* on the
`actual:` line with the trajectory as the continuation. AC-011's v0.1 `render_failure` does the
**reverse**: `actual:` holds the trajectory, the short reason is the continuation. Since the ticket
says "failure blocks come from `AssertionResult` verbatim; the reporter formats, it does not
compose," the golden reproduces §7.2's **header, both case lines, and summary byte-for-byte** and
renders the failure block via the real v0.1 machinery (a failing `calls_tool(count)`). Don't chase
byte-identity on the failure block — it can't hold with v0.1 assertions.

### Byte-pin the layout by measuring the spec, not guessing
`sed -n 'l'` + a tiny Python `str.find` pass gave exact columns: the case name is `ljust(36)` after
a 4-char `  <glyph> ` prefix (so metrics start at column 40), fields are separated by 3 spaces, and
the failure block is `render_failure` indented 6 spaces (trajectory lands at column 20). Generated
the report, eyeballed against §7.2, pinned the fixture — same characterize-then-pin flow as AC-004/
AC-011.

### Keep the renderer pure; make `color` a parameter, not ambient state
`render_report(run, *, color=False) -> str` emits zero ANSI when `color=False` — so the CI-log path
and the golden path are the same code, and "no ANSI off a TTY" is testable on the raw bytes
(`b"\x1b" not in ...`) without faking a terminal. The TTY/`NO_COLOR`/`--no-color` policy lives in a
separate `resolve_color(stream, *, no_color)` (checks the flag and `NO_COLOR` **before** the rich
`Console(file=stream).is_terminal` check, so both override a real TTY). That satisfies "uses rich"
for the policy while the layout stays hand-built for byte control.

### Truncation is display, not message content — truncate fields, keep `render_failure` as layout
"Long argument dicts truncate but the trajectory line never does." The trajectory is the
`AssertionResult.actual` field. So the reporter truncates only `expected`/`message` (via
`result.model_copy(update=...)`) and hands the copy to `render_failure` — layout stays in one place
(domain), the reporter owns the truncation decision, and `actual` is never touched.

### Mutation magnitude must exceed display resolution
A `+1 ms` mutation to the duration sum did **not** fail the golden/summary tests — `.1f` rounds it
away, and a 1 ms discrepancy genuinely doesn't matter at display resolution. Use a `+2000 ms`
mutation to prove teeth. The lesson: size the mutation to the observable output, not the internal
value.

### `mypy --strict` on a test file re-enables `disallow_untyped_defs`
`make typecheck` scopes to `dryfire/` (and the `tests.*` override relaxes untyped defs). Running
`mypy --strict tests/...` directly (the port-conformance habit) turns strict back on for that file,
so `monkeypatch` params need `pytest.MonkeyPatch` annotations and `sum()` over a `Trace | None`
comprehension needs an explicit `is not None` list first. Worth fixing — it's the same check CI
would want and it caught a genuinely-loose `sum(... float | None ...)`.

## JSON reporter (AC-014)

### Inject the timestamp; don't reach for a clock
The JSON needs an ISO-8601 `...Z` timestamp, and "two runs byte-identical except timestamps" is a
criterion — so the timestamp is the *only* non-determinism. With no Clock port yet, `render_run(run,
*, generated_at: datetime)` takes the time as a parameter: tests pass a fixed `datetime`, composition
(AC-015) passes `datetime.now(UTC)`. Keeps the reporter pure and the determinism test trivial. Format
with `.isoformat(timespec="seconds").replace("+00:00", "Z")` — `isoformat()` emits `+00:00`, not `Z`.

### Serialize before you touch the target — that's the atomicity guarantee
`write_run` renders the whole string first (so a serialization failure never touches the file), then
writes a temp file in the target's dir and `os.replace`s it (atomic rename). The load-bearing test
monkeypatches `os.replace` to raise and asserts the target is **absent** and the temp is cleaned up —
a naive `target.write_text(...)` fails it (mutation-verified). `allow_nan=False` on `json.dumps` is
the guard that turns any future non-finite float into a loud error instead of `NaN` in the artifact.

### The JSON must round-trip to a RunResult, not just parse
"Serialize → deserialize → re-render terminal identical" needs a real `deserialize_run(doc) ->
RunResult` (also the seam v0.3 `compare`/HTML will use). Domain models rebuild via
`Trace.model_validate` / `AssertionResult.model_validate`; the frozen `CaseResult`/`SuiteResult`/
`RunResult` dataclasses are reconstructed by hand. `model_dump(mode="json")` already carries
`Message.raw` and `malformed_arguments` (they're model fields) — no special handling needed.

### `mypy --strict` on a test with a stub-less dep needs a module override
`jsonschema` ships no type stubs, so `mypy --strict tests/...test_json_reporter.py` errors on the
import. `make typecheck` is scoped to `dryfire/` so it's unaffected, but to keep the test-file
conformance check clean add `[[tool.mypy.overrides]] module = "jsonschema.*"` with
`ignore_missing_imports = true`. Also: monkeypatching a module's imported `os`/`json` via
`monkeypatch.setattr(mod.os, ...)` trips mypy's `attr-defined` (not an explicit export) — use the
string-target form `monkeypatch.setattr("pkg.mod.os.replace", boom)` instead.

## CLI + composition (AC-015)

### composition.py is above the layers — it may import everything
The import-linter `layers` contract orders `adapters > application > domain`; `dryfire.composition`
is **not in any of the three layers**, so it's unconstrained and can import driven adapters + app +
domain (contract 5 only forbids `domain`/`application` sources). This is the intended composition root
(ARCHITECTURE §7). `cli.py` (a driving adapter) imports `composition`; no cycle, contracts stay 5/5.

### Config is checked before the network — that's what makes "spec error → 2" hold
The exit-code precedence (`2` spec/config before `3` provider) falls out of *ordering*: `_load` runs
first and returns exit 2 on any `SpecError` **before** `make_gateway`/the scheduler ever run. So a
broken suite with an unreachable provider is `2`, not `3` — and the mutation that disables the early
`if loaded.errors: return 2` is caught by two tests. Provider failures aren't raised; the scheduler
records them as `provider_error` terminations, which `_exit_code` maps to `3`.

### Inject the gateway *factory*, not a gateway, for CLI tests
The CLI can't take a gateway through argv, so `composition.make_gateway(provider)` is the single seam;
tests `monkeypatch.setattr(composition, "make_gateway", lambda p: fake)`. `validate` asserts zero
network by patching `make_gateway` to **raise if called** — it never builds one. Request-driven fakes
(response derived from `request`, not a global script) stay deterministic under the scheduler.

### `typer.Exit(code)` surfaces as `SystemExit`, not `None`
Under `typer.testing.CliRunner`, a handled command still sets `result.exception = SystemExit(code)`.
To assert an internal error was *handled* (not surfaced), check `not isinstance(result.exception,
RuntimeError)` — not `result.exception is None`. With `--debug`, the real exception (`RuntimeError`)
propagates and *is* `result.exception`.

### Typer needs calls in parameter defaults — mark them immutable for ruff
`def run(paths=typer.Argument(...), flag=typer.Option(...))` trips ruff B008 (function call in a
default). Typer's API requires exactly this, so add
`[tool.ruff.lint.flake8-bugbear] extend-immutable-calls = ["typer.Argument", "typer.Option"]` rather
than restructuring every command.

### Wiring surfaces domain-modelling gaps — widen honestly
Mapping real mocks exposed that `Return.value` / `ToolResult.content` were typed `str | dict` but a
`return: null` mock (AC-003 calls it "legitimate null tool-result content") needs `None`. Widened
both to `... | None` — a one-line correctness fix per model, backward-compatible, that also keeps
`_to_result` type-clean. The lesson: composition is where "each piece type-checks alone" meets "do
they fit together" — expect to true up a domain type or two, and do it in the model, not with a cast.

### Driving a fake provider from YAML needs a spec `script` + per-case gateways (AC-016)
The keyless example is a real `.eval.yaml` run through the CLI, but a suite only declares tools,
mocks, and expectations — nothing scripts the *model's* turns. So `provider: fake` gained a case-level
`script:` (tool_call / text / parallel / fails, mapped 1:1 to the existing `FakeGateway` helpers in
`adapters/driven/spec/scripts.py`). A scripted `FakeGateway` is **stateful** (script cursor + id
counter advance per `complete()`), so it can't be the scheduler's one shared gateway. Fix: an optional
`PlannedCase.gateway` that overrides a run-level default `provider` — mirrors how case mocks layer over
suite mocks. Composition builds a fresh fake per fake-case in `_plan`; real cases fall back to the
shared default. Cheaper than a `gateway_for` factory param (which would have churned ~16 scheduler test
call sites) and semantically the same. `provider` also became **suite-level** so a `fake` suite and an
`anthropic` suite coexist in one project.

### Put "skip on missing key" *inside* `make_gateway`, the seam tests already replace
The keyed example must be *skipped* (not failed) with no `ANTHROPIC_API_KEY`, but the existing CLI
tests run with no key and expect their anthropic cases to *run* (against an injected fake). Reconciled
by making real `make_gateway("anthropic")` raise `MissingCredentials` when the key is absent;
composition catches that and drops those cases with a note (exit stays 0). Tests that
`monkeypatch.setattr(composition, "make_gateway", …)` bypass the check entirely, so their cases still
run — the skip logic lives exactly where the test seam already is. `trace` (an explicit request)
surfaces the same condition as an error, not a silent skip. A non-`MissingCredentials` build failure
still propagates to `_internal_error` → exit 2, so the "internal error" test is unaffected.

### Ship package data via `importlib.resources`, and mind the `-W error` gate
The scaffold template (`dryfire/scaffold/template/**`) ships in the wheel the same way
`data/pricing.yaml` does — files under the package dir are included by hatchling with no extra config —
and is read with `files("dryfire").joinpath("scaffold/template")`, never a `__file__`-relative path,
so it works from a wheel too. Recurse a `Traversable` with `.iterdir()`/`.is_dir()`. Import it from
**`importlib.resources.abc`**, not `importlib.abc` — the latter emits a `DeprecationWarning` that the
suite's `-W error` turns into a failure. Detect all conflicts before writing so a refused `init` never
leaves a half-written project.

### Dogfood: a failing case is the success — verify per-case, not the aggregate exit code (AC-018)
The dogfood suites include cases that must FAIL; the harness is green when they fail *correctly*. The
non-obvious trap: asserting the fail-suite's **aggregate exit code is 1** does NOT catch a single
expected-fail case that quietly starts passing — the run still exits 1 as long as *any* case fails.
The mutation check caught exactly this (flip one fail-case to pass → harness stayed green). Fix: parse
the JSON report and assert **each** case's polarity (every pass-case `passed:true`, every fail-case
`passed:false`). Lesson for any "expected failure" harness: check the granular outcome you care about,
never a coarser signal that happens to correlate. Terminations are verified the same way — grep is
format-fragile, so parse `trace.termination` (and nested `tool_results[].is_error` for the `sequence`
recovery) from `--reporter json`. Provider_error lives in its own suite because exit 3 outranks
exit 1, and the harness runs `set -uo pipefail` (not `-e`) because it *expects* non-zero exits.

### Release: verify competitor claims on the live web, and mind uvx's ephemerality (AC-019)
A public README's comparison table is a factual claim about other projects — verify it against the
source before shipping, especially anything past the training cutoff. `COMPARISON.md`'s load-bearing
claims all checked out against promptfoo.dev / web search (Promptfoo does ship `trajectory:*`
assertions, but on *instrumented/traced* runs; OpenAI acquired Promptfoo March 2026; it has
red-teaming) — so the honest differentiator is "deterministic mocking + owns the loop + nothing to
instrument," not "we assert on trajectories." Two packaging gotchas: (1) `uvx dryfire init && dryfire
run` is wrong — `uvx` runs a tool ephemerally and does NOT put `dryfire` on PATH, so the second
command needs `uvx` too (or a real `pip install`); README/GIF use `uvx` throughout. (2) Verify the
built *wheel*, not just that `uv build` succeeded: `unzip -l` it to confirm package data ships
(`data/pricing.yaml`, `scaffold/template/**`) and install it into a fresh venv to run `init → run` —
the real proxy for "works from PyPI on a clean machine." Trusted Publishing (OIDC) needs
`id-token: write` + an `environment:` and no token, but the maintainer must register the pending
publisher on PyPI first. Also: `f"...into {Path('.')}. "` renders as "into .." — special-case the
current directory in user-facing paths.

### Cassettes as a decorator: keep the loop unchanged by riding on ModelResponse (DF-204)
The epic's #1 rule is `git diff application/loop.py` empty. Two decisions made that hold: (1) surfacing
cache-hits **rides on `ModelResponse.cache_hit` (default False)**, set by the CachingGateway — the loop
only *stores* the response it's handed, so it never learns caching exists. This beat building the
`EventSink` model, which would have emitted events from the loop (a loop change). Cost is one additive
trace-JSON field; the reporter shows `⚡N cached` **only when present** so existing goldens stay green.
(2) A `replay` **miss raises `CassetteMiss`**, which the loop *already* turns into `provider_error` →
exit 3 — the required behaviour with zero loop change. Two integration gotchas: **replay must bypass the
AC-016 credential-skip** (cassettes need no key, so replay wraps each real case over a `_NoLiveGateway`
that raises if a live call is attempted — the airgap — and never calls `make_gateway`); and the
fingerprint must be computed over the request **with `raw` stripped** (the provider's opaque passthrough
carries non-reproducible ids that would make every key unstable). Mutation-check the airgap: delete the
replay guard and the `CassetteMiss` test must fail (a miss falls through to a live call).

### Retries as a decorator + a Clock port; a runtime_checkable Protocol method ripples (DF-206)
Retries land like caching — a `RetryingGateway` decorator over `ModelGateway`, `loop.py` unchanged, so
**a retried call is still one turn** (the loop sees one `complete()`). Two design points: (1) route the
only wall-clock wait through a **Clock port** so a `FrozenClock` records the backoff *sequence* and the
tests run in microseconds — never let production `asyncio.sleep` into a unit test. (2) Retry
**classification** belongs in the provider adapter (`is_retryable` on the port; the decorator only asks),
so the decorator grows no vendor knowledge — Anthropic/OpenAI share one duck-typed policy
(`status_code` 429/5xx + connection/timeout by class name, no SDK import). **Gotcha:** adding a method to
a `@runtime_checkable` Protocol changes what `isinstance(x, ModelGateway)` accepts — every shipped
gateway (Fake, Anthropic, OpenAI, Caching) and every stub that asserts conformance must gain the method,
or its check silently starts failing. And make the decorator tolerate an inner *without* the method
(getattr-default → not retryable) so unrelated test doubles wrapped by composition don't blow up.
Composition order is fixed `Caching(Retrying(Real))`: cache hits skip retries; retries apply only live.

### A cost assertion needs cost *before* assertions run — move pricing into the scheduler (DF-207)
`cost_under` reads `trace.total_cost_usd`, but cost was attached **post-hoc** in `composition._price`,
*after* the scheduler evaluated assertions — so the assertion would always see `None`. Fix: `run_suites`
takes an injected `price(trace, case)` callback (composition builds it over the pricing catalog; the
scheduler stays adapter-free) and `_process_case` prices the trace **before** `_evaluate`. Pricing also
sets a new `Trace.model` field so the "pricing unavailable for model X" message can name it — and
because `model` defaults None and is set only by the pricing step (via `model_copy`), the loop still
never prices and `loop.py` stays byte-for-byte unchanged. General lesson: an assertion can only see
what's on the `Trace` when the scheduler evaluates it; if a new assertion needs a derived value, produce
it *before* evaluation, not in a post-hoc reporting pass. And keep the fail-loud rule for advisory data:
`cost_under` on an unpriced model **fails** (naming the model), because a green check that proves
nothing is worse than a red one.

### You cannot time-box a catastrophic regex in-process; pydantic beats jsonschema in a pure domain (DF-208)
Two findings from the extended assertions. (1) **Regex bounding is impossible in-process.** CPython's
`re` engine holds the GIL for the whole match and never yields, so a catastrophic pattern in a worker
thread starves the main thread — `thread.join(timeout)` never returns (I found this the hard way: the
test hung). `signal`-based timeouts fail for the same reason, and an input-length cap is useless because
backtracking is exponential in tiny inputs (40 chars already hangs). The only things that actually work
are a subprocess-with-kill (heavy, I/O in a "pure" assertion) or the third-party `regex` module (a dep).
We chose **neither**: compile at validate time (catch invalid patterns early), run uncapped, and
document that a pathological pattern is the user's own regex — the same no-sandbox stance the project
already took for passthrough mocks (SPIKE-004). Don't promise a bound you can't deliver. (2) **For
`final_json`, pydantic > jsonschema in domain.** Pydantic *emits* JSON Schema but can't *consume* one to
validate data — that's jsonschema's job, forbidden in a lean pure domain. Compiling a lightweight shape
(`required` + `fields:{name:type}`) into `pydantic.create_model` needs no new dependency, stays
domain-pure, and gives richer errors that cleanly separate "unparseable JSON" from "shape violation."
Reframe the feature to the tool you already have rather than adding a dependency for the literal name.

### A per-call timeout bounds the async *scheduler*, not the *thread* running a sync callable (SPIKE-004)
Passthrough runs user code; sync impls go through `asyncio.to_thread` so they don't freeze the loop, and
`asyncio.wait_for(..., timeout)` bounds them. But the bound is on the **await**, not the **work**: Python
has no thread-kill, so a wedged sync impl runs to completion. The consequence is two-sided and easy to
mismeasure: (1) *while the event loop lives*, `wait_for` returns control at the timeout and the other
concurrent cases proceed — the scheduler is genuinely bounded; (2) *at loop shutdown*, `asyncio.run` calls
`loop.shutdown_default_executor()`, which **joins** the abandoned thread, so the whole process pays the
sync impl's full runtime once at the end. My first timeout test measured a single `asyncio.run(invoke(...))`
and saw the *full sleep* (0.5 s, not the 0.1 s bound) — because the shutdown-join dominated, not because
the timeout failed. Fix: measure elapsed **inside** the coroutine (control-return), and prove the real
property — a fast neighbour completes on schedule while the hang is abandoned. Async impls have no such
asymmetry: `wait_for` cancels the coroutine cleanly, nothing to join. When you assert "bounded," be exact
about *which* boundary — event-loop progress vs. process wall-clock — they differ for threaded sync work.

### JUnit XML: newlines collapse in an attribute but survive in text; multiple `<failure>` is lossy (SPIKE-005)
Two findings that decide the JUnit mapping, both offline-provable (parser-independent per XML 1.0), so no
live CI was needed to settle them. (1) **Attribute-value normalization eats newlines.** XML 1.0 §3.3.3
replaces a literal newline in an *attribute* value with a space at parse time; *element text* is untouched.
So a multi-line trajectory/failure block put in `<failure message="...">` arrives space-mushed in every
consumer — it MUST go in the `<failure>` text body, with only a one-line summary in `message`. (pytest
actually gets this "wrong" — it crams a multi-line message in and relies on the body for fidelity; our sink
does better with a purpose-built summary.) (2) **Multiple `<failure>` per `<testcase>` is silently lossy.**
The Ant/Surefire schema permits at most one; Jenkins and pytest emit one; consumers calibrated on that drop
the extras. So "one `<failure>` per failed assertion" (candidate C) *looks* complete but drops every
assertion after the first on the strictest parsers — worse than concatenating them into one body (candidate
A). Verdict: **case = testcase, one concatenated `<failure>`** (= pytest's shape, refined). Corollary: when
a spike's question is "how does consumer X render this," first separate what's decided by the XML spec
(decidable offline, authoritative) from what's decided by the consumer's UI (needs live capture) — most of
the JUnit question was the former. `<error>` (not `<failure>`) for `provider_error`/`unmocked_tool`: the
case couldn't be *evaluated*, which consumers count and colour separately from a caught regression.

### "Freeze the loop" and "non-blocking concurrent passthrough" are mutually exclusive (DF-211)
Passthrough mocks run real user code as a tool result. The instinct was to keep `application/loop.py`
untouched (it was treated as EPIC-002's load-bearing invariant). But the loop resolves tools with a
**synchronous** call — `resolved = resolver.resolve(call)` — and the scheduler runs every case as an
asyncio task on **one shared event loop**. So to invoke a passthrough callable *without* freezing all the
other concurrent cases, the invocation must `await` (yield the loop) — and the only place that can happen
is the resolve seam, which means editing the loop. Keeping the loop sync forces blocking invocation, which
serialises every concurrent case (one blocking call stalls the single loop thread). The two goals cannot
both hold; there is no clever seam around it (a gateway/pre-execution hook can't help — the tool args only
exist mid-loop, and blocking inside a sync `resolve()` stalls the shared loop regardless of where the I/O
physically lives). Resolution: a **one-branch** loop change (`if isinstance(resolved, Passthrough):
resolved = await invoker.invoke(...)`), with the domain resolver staying pure by returning a `Passthrough`
marker and a new async `ToolInvoker` port doing the I/O. Lesson: before promising "this layer never
changes," check whether a required *concurrency* property forces a yield point there — sync-vs-async is a
structural constraint, not a detail you can decorate around. (This is distinct from the gateway
"loop unchanged" rule, which holds precisely because caching/retrying are async decorators over an already
-async `complete()` — no new yield point is introduced.)

### A composite action can install its own package from `github.action_path` — no PyPI needed (DF-210)
The dryfire GitHub Action must install dryfire, but the PyPI publish is deferred, so
`pip install dryfire==<v>` can't work yet. The unlock: a composite action's steps run with
`${{ github.action_path }}` pointing at the action's own checked-out repo (already pinned by the
consumer's `uses: owner/repo@ref`). Since that repo *is* the Python package, `pip install
"$ACTION_PATH"` installs dryfire from source, version-pinned to the action ref, with zero PyPI
dependency — so the Action is verifiable in a throwaway repo today. Keep a `version` input that,
when set, installs from PyPI instead, for after the publish. Two more CI-authoring notes worth
keeping: (1) an **example workflow committed under `.github/workflows/` will auto-run in your own
repo** — if it pins a not-yet-existing release tag (`owner/repo@v0.2.0`) it fails on every PR, so
gate it with `on: workflow_dispatch` (a documented example, not part of your real `ci.yml`), and
tell users to switch the trigger. (2) Pass every action input into `run:` via `env:`, never inline
`${{ inputs.x }}` in the script body — inputs are attacker-controllable in the general case, and the
env indirection is the standard injection-safe pattern. Design the action so JUnit is always written
(`--junit-out`, independent of `--reporter`) and the upload/report/enforce-exit steps use
`if: always()`, so a *failing* run still renders its report before the job goes red.

## Session Notes

### 2026-07-30 — AC-001 + toolchain
- Scaffolded the project (see `docs/Progress.md`), adopted Makefile/docs practices from
  `terms-pilot`, added Docker as a reproducible toolchain + local CI matrix only.
- Rejected for dryfire: service containers, SOPS/age secrets (no team, no server, the
  only secret is `ANTHROPIC_API_KEY` for live tests), production Dockerfile (ships to
  PyPI), migrations/alembic (no database — tripwire in ARCHITECTURE §11).

### 2026-08-02 — EPIC-003 kickoff / SPIKE-006 (async assertion seam)
- **Model C won, and the codebase already proves it.** The judged-assertion seam is not a new
  invention — `composition._make_price` → `scheduler._process_case` (`trace = price(trace, case)`
  between `run_case` and `_evaluate`) is the exact template. The judge enrichment is the same
  callback, `await`ed and gateway-backed. Assertions stay pure/sync; `evaluate(trace)` is
  unchanged; `loop.py` is not in the call graph at all (so it is NOT a DF-211-style loop
  exception — the enrichment sits outside the loop).
- **Two-file rule, resolved up-front:** `llm_judge` is the first assertion needing data the loop
  doesn't compute, so the *feature* lands a one-time seam (verdict/rubric types + `Trace` field +
  `JudgeEnricher` + scheduler/composition wiring) on top of the two-file assertion. Precedent is
  DF-207 (`cost_under` first had to build the `price` seam). State it in the DF-303 PR as covered
  by SPIKE-006, don't "confess" it.
- **Judge failure = exit 3 (provider error), never exit 1.** A broken judge is infrastructure, not
  an agent regression; conflating them sends the user to debug the wrong thing. Unparseable judge
  output is a judge *error*, never a score of 0. No new exit code — 0/1/2/3 already has the bucket.
- **Judge concurrency is a single shared semaphore** closed over by the enricher (built in
  composition, like `_make_price` closes over the catalog) → bounds judge calls globally,
  independent of case concurrency. Flat `gather`, never a nested pool.
- **`Trace` gains additive optional fields** (`judge_verdicts={}`, later `judge_usage/cost`) →
  structural-only traces serialise byte-identically. Bump `SCHEMA_VERSION` 1→2 as a *capability
  signal* only (reader stays tolerant of 1); it is not a format break.
- **Gotcha:** the epic's spike dir names start with a digit (`006_async_assertions`) → not a valid
  Python package name, so `from .seam import ...` fails under pytest. Import via
  `sys.path.insert(0, str(Path(__file__).parent))` + `from seam import ...`. Same fix awaits
  SPIKE-007's `007_repeat/`. Spikes aren't collected by `make test` (`testpaths=["tests"]`) but
  ARE linted by `ruff check .`, so keep spike code ruff-clean.

### 2026-08-02 — DF-301 (judge domain model)
- **Two unrelated `SCHEMA_VERSION` constants — don't conflate.** `json_sink.SCHEMA_VERSION` (the
  `--json-out` artifact shape) and `fingerprint.SCHEMA_VERSION` (the cassette hash payload) are
  independent. DF-301 bumps only the artifact one (1→2 for `judge_verdicts`); the cassette version
  must NOT move or every v0.2 cassette invalidates. Bumping the artifact version has a fixed ripple:
  `tests/unit/adapters/test_json_reporter.py` (pins `== N`) + `tests/fixtures/run_schema.json`
  (`schema_version.const` + title). Grep both before bumping.
- **The artifact round-trip is free for additive Trace fields.** `json_sink` dumps
  `trace.model_dump(mode="json")` and rebuilds via `Trace.model_validate` (`deserialize_run`), so a
  new optional `Trace` field round-trips with zero sink code — only the version const changes. The
  `run_schema.json` `trace` def has no `additionalProperties:false`, so it already tolerated the new
  field; I added an explicit `judge_verdicts`/`model` shape for documentation, not necessity.
- **Rubric hash = reuse, not reinvent.** `Rubric.hash()` is `sha256(canonical_json(payload))` reusing
  `domain/fingerprint.py`'s canonicaliser — sorted keys (stable across dict key order) but NFC-only on
  strings (whitespace preserved → sensitive to reformatting). Writing a second hasher here would be
  the classic judge-drift bug the ticket exists to prevent.
- **Scope call:** kept `JudgeVerdict` to DF-301's 7 provenance fields; the `error` state (judge failure
  ≠ score 0, per SPIKE-006 Q3) lands in DF-302 when the enricher can actually produce one — no point
  adding a field no code path sets yet.

### 2026-08-02 — DF-302 (judge evaluator)
- **The verdict `error` field lands where the error can happen.** DF-301 kept `JudgeVerdict` to 7
  provenance fields; DF-302 added `error: str | None` + `from_score`/`from_error` factories, because
  this is the ticket where a judge can actually fail. `error is None` ⇔ genuine score; a provider
  exception or unparseable response → `from_error` (score 0.0, passed False, error set). Never let a
  judge malfunction masquerade as a real 0 — it would silently fail good cases.
- **`float(json_value)` under mypy --strict:** a parser typed `dict[str, object]` breaks
  `float(data["score"])` (object isn't SupportsFloat). Type parsed-JSON as `dict[str, Any]` (repo
  style — `extended.py` does the same); the runtime `except (…, TypeError, ValueError)` still catches a
  non-numeric score → judge error.
- **Real judges wrap JSON in ```json fences despite instructions.** `_extract_json` strips a leading
  fence + finds the outermost `{…}`, so fenced or prose-wrapped output still parses; only genuinely
  absent JSON raises → recorded as a judge error, not a false score.
- **Concurrency observed by the test double, not the production object.** ARCHITECTURE bans test-only
  methods on production classes, so the semaphore lives in `JudgeEvaluator` while the *fake gateway*
  counts its own in-flight calls and asserts `max_in_flight == bound`. Same pattern will fit DF-305's
  `repeat` concurrency test.
- **`asyncio.Semaphore()` created outside the loop is fine in 3.12** — it binds lazily on first
  `await`, so building the evaluator in composition (before `asyncio.run`) and using it inside works,
  mirroring how `_make_price` is built before the run.

### 2026-08-02 — DF-303 (llm_judge assertion + enrichment wiring)
- **Content-addressed verdict keys, not positional.** `Trace.judge_verdicts` is keyed by
  `judge_key(model, rubric_hash)`. Both the pure assertion and the application `collect_judge_requests`
  compute it identically from the same inputs, so they can never disagree — and no positional index has
  to be threaded into a pure assertion. Bonus: two identical judged assertions dedupe to one judge call.
  Model is part of the key because the same rubric graded by two models is two non-comparable judgements.
- **Key consistency depends on `trace.model`.** The assertion resolves its model as
  `args.model or trace.model`; `collect` uses `args.model or case.model`. They match because the judge
  enrichment sets `trace.model = case.model` in its `model_copy` (and `price` sets it too). If a verdict
  key ever misses, the assertion fails LOUDLY ("judge did not run"), never silently passes.
- **The scheduler seam is genuinely one line.** `_process_case` gained `if judge is not None: trace =
  await judge(trace, case, gateway)` between `price(...)` and `_evaluate(...)` — the DF-207 shape,
  now async. `loop.py` untouched. `judge=None` (structural-only) is the exact v0.2 path; composition
  only builds the callback when `_suites_use_judge(runnable)`.
- **Judge reuses the CASE's gateway** (passed through the seam), so judge calls are cassette-backed and
  retried for free — no separate judge-gateway construction in composition. Limitation to document later:
  a cross-provider judge model (case anthropic, judge openai) isn't supported yet; the default (judge =
  case model, same provider) and same-provider overrides work.
- **Offline e2e without monkeypatching `make_gateway`:** a `provider: fake` case whose `script:` lists
  the agent turn(s) THEN the judge's JSON — the judge consumes the next script entry from the same fake
  gateway. Remember `provider` is SUITE-level, `script`/`model` are case-level (bit me first try).

### 2026-08-02 — DF-304 (separate judge cost accounting)
- **cost_under/latency_under_ms are blind to judge cost BY CONSTRUCTION, not by a filter.** Judge
  calls happen in the enrichment stage, outside `run_case`, so they never become `trace.turns` and
  never enter `trace.total_usage`/`duration_ms`. `cost_under` reads `total_cost_usd`, `latency_under_ms`
  sums `turn.response.latency_ms` — both already exclude judging. DF-304 just adds the separate channel
  and the regression test that pins it (case cost 0.001, judge cost 1.0, limit 0.01 → cost_under passes).
- **Judge cost is priced per verdict by its OWN judge model**, then summed — because different judged
  assertions can name different judge models. Advisory like case cost (None when nothing prices), never
  a fabricated $0.0000.
- **Ruff B008 bites frozen-model defaults in function signatures.** `usage: Usage = Usage(...)` as a
  *parameter* default trips "no function call in argument defaults" even though Usage is immutable. Fix:
  a module-level `_ZERO_USAGE = Usage(...)` sentinel used as the default (a name, not a call). Class-body
  field defaults (`usage: Usage = _ZERO_USAGE`) are fine either way.
- **`asyncio.run` + a `Callable[..., Awaitable[T]]` fails mypy --strict** ("expected Coroutine, got
  Awaitable"). Driving a `JudgeTrace` callback in a test needs a tiny `async def go(): return await cb(...)`
  wrapper so `asyncio.run(go())` gets a real Coroutine. (An `async def` method like `evaluate` is already
  a Coroutine, so DF-302's tests didn't hit this.)
- **Didn't touch loop.py to reuse its `_sum_usage`.** Added a public `sum_usage` in `message.py` for
  callers above the loop; the loop keeps its private one. The tiny duplication is cheaper than a diff to
  the frozen loop.

### 2026-08-02 — SPIKE-007 (repeat keying + pass-rate stats)
- **Repetition index goes in the STORAGE KEY, not the hash.** `storage_key(fp, 0) == fp`,
  `storage_key(fp, i) == f"{fp}#{i}"`. Because `fingerprint()` is untouched, all 19 SPIKE-002
  stability/sensitivity tests pass by construction and `repeat: 1` is byte-identical to v0.2. Putting
  the index in the hash would either invalidate every cassette (always include) or add a special-case
  branch inside the security-critical hasher (include-only-when>0) — both worse.
- **The feared failure is a one-liner to demonstrate:** key every repetition by the bare fingerprint and
  replay serves the last response N times → every pass rate is a comforting N/N lie. DF-306's must-have
  test is `repeat: 5` replay yielding 5 DISTINCT responses, asserted individually (not by count).
- **Partial cassettes need NO new policy** — with a per-index key, a missing repetition is just a
  cassette miss, so DF-204's mode table applies per key: auto backfills live, **replay errors (exit 3)**
  rather than fabricating a rate from fewer recordings. That is the SPEC §9 hand-wave made precise.
- **Wilson interval, not naive normal:** stays in [0,1] and is honest at the boundary (5/5 → [0.57,1.0],
  not [1.0,1.0]). Even N=20 at 80% is ±0.17; N=3 can't even express 0.8. Recommended min N=5, shown only
  for disagreeing cases (0<k<N) so the merge-gate line stays clean. No dependency — it's arithmetic.
- **`repeat`×`compare` decided ONCE here** (allowed+warned via DF-307's cost prompt), so DF-305 and
  DF-307 defer rather than each inventing a rule — closes the drift risk I flagged after DF-303.

### 2026-08-02 — DF-305 (repeat: N execution + pass rates)
- **Repetitions are units in the ONE worker pool, not a nested pool.** The scheduler expands each case
  into `repeat` entries in the flat `units` list; the existing worker set pulls them, so the global
  concurrency bound spans all repetitions of all cases. `repeat: 1` → one unit → v0.2 shape exactly.
  Aggregation folds a case's N unit-results back into one CaseResult; `_aggregate` returns the sole
  result UNCHANGED when repeat==1, so the common case takes no repeat code path in its output.
- **Per-case slot bookkeeping is race-free because there's no await between the `await _process_case`
  and the slot write/aggregate-check.** asyncio is cooperative — a worker step after its await runs to
  completion before any other coroutine, so `rep_filled[pos] += 1` and the "all done?" check are atomic.
- **CaseResult stayed additive:** `repetitions`/`require_pass_rate` optional (None for repeat:1), with
  `passes`/`total`/`pass_rate` as computed properties. Every reporter/sink works unchanged for repeat:1;
  json_sink only emits repetition keys when present (repeat:1 artifact byte-identical). run_schema's
  `case` def is `additionalProperties:false`, so the new keys HAD to be added there explicitly.
- **Disagreement is the finding, rendered distinctly:** a `~` glyph (not ✓/✗) for `0<k<N`, plus the
  Wilson 95% CI shown ONLY for disagreeing cases (uniform 5/5 or 0/5 don't need it), plus a
  `repeat<5: wide interval` warning below the recommended minimum — warn, never refuse (SPIKE-007 Q4).
- **Known minor gap:** the run summary's total cost uses the representative rep's cost per repeated case
  (undercounts the N reps). Advisory cost only; fold a proper sum into a later ticket if it matters.
- `repeat`/`require_pass_rate` are overridable at case/suite/defaults via the same `_pick` chain as every
  other setting; pydantic `Field(ge=1)` / `Field(ge=0,le=1)` give positioned spec errors for free.

### 2026-08-02 — DF-306 (repetition-aware cassette keys)
- **The repetition index must be CONSTANT across all turns of one repetition**, or a multi-turn case's
  turns key under different indices and replay mispairs. A per-fingerprint occurrence counter fails this
  under concurrency (reps interleave). Solution: one `CachingGateway` per repetition with a fixed
  `repeat_index`; composition builds them via a `gateway_factory(i)` seam, the scheduler calls it with the
  deterministic repeat index (which is also the aggregation slot). Each per-rep gateway has its own turn
  counter → turns 0,1,2 within a rep; shared `inner` real gateway (stateless, safe).
- **The store and prune needed ZERO changes.** `storage_key` puts the index in the key (`fp` / `fp#i`),
  `#` is filesystem- and glob-safe, and `fp` is 16 hex so a bare-`fp` glob (`*-fp.json`) never matches a
  suffixed `*-fp#1.json`. prune is directory-based (`<suite>/<case>/<file>`), so repetition cassettes in a
  valid case dir are kept and orphaned ones removed automatically — just add tests, not code.
- **The must-have test asserts responses INDIVIDUALLY, not by count** — `["r4"]*5` also has length 5. The
  e2e (`composition.run` record→replay) is the real proof: 5 distinct cassette files, `forbidden.calls == 0`
  on replay.
- **Committed v0.2 cassette fixture:** compute the fingerprint for a fixed request once (via `_hash_args` +
  `fingerprint`), hand-write the JSON at `tests/fixtures/cassettes_v0_2/<suite>/<case>/00-<fp>.json` with
  cassette `schema_version: 1`, then a `repeat_index=0` replay must serve it. Store `get` is `rglob`, so
  the fixture's suite/case dir names don't need to match the gateway's.
- **`_wrap_cases` moved from setting `.gateway` to `.gateway_factory`** — updated the one passthrough test
  that asserted the old shape (`isinstance(planned.gateway, CachingGateway)` → `planned.gateway_factory(0)`).
- Repo convention: async gateways are driven with `asyncio.run(...)` in sync tests, NOT `@pytest.mark.asyncio`
  (pytest-asyncio isn't a dep).

### 2026-08-02 — DF-307 (compare execution)
- **compare is orchestration OVER run_suites, not a second runner.** The pure use case
  `run_compare(axis, labels, run_one)` takes an injected `run_one(label)` coroutine and folds RunResults
  into columns; composition's `run_one` reuses the SAME plan → wrap → run_suites path `run` uses (a small
  `_compare_run_one` helper). `git diff` shows no new execution path — run_suites is untouched.
- **A failing model is a failed column, two ways:** if `run_one` RAISES (planning error) → `run_compare`
  catches it into a column with `error` set (application-level, tested with a fake). If the model is just
  bad (API rejects it) → its cases get `provider_error` and the column completes but the compare exit code
  is 3. Either way the other columns finish — never an aborted run.
- **Cost estimate = run count, not a guessed dollar figure.** Tokens are unknowable pre-run, so the honest
  estimate is `labels × Σ(case repeat)` (precise); the confirmation gate is built on it. Above the
  threshold (and not free `replay`) without `--yes` → refuse with exit 2 in a non-TTY, so CI can't wander
  into a huge bill. `--yes` bypasses.
- **`--prompts` reuses a new `system` override in `resolve`** (explicit `"system" in ov` check, not `_pick`,
  because a system prompt may legitimately be None). `--models` and `--prompts` together are refused (v0.3).
- **Gotcha: two `test_compare.py` files (unit + integration) collide** under pytest's default import mode
  (no `__init__.py` in tests) — duplicate module name. Renamed the integration one to `test_compare_e2e.py`.
  Keep test basenames unique across the tree.

### 2026-08-02 — DF-308 (compare matrix output)
- **Disagreement must be distinct by CHARACTER, not just colour** (AC): a disagreement row (models
  disagree, `0 < passes < columns`) is prefixed with `~` and its cells stay `✓`/`✗`, so it survives a
  non-TTY CI log and a grep. Colour is layered on top only when `color=True`. Pad glyphs to column width
  using the UNcoloured length — ANSI escapes have zero display width, so padding after colouring misaligns.
- **Wide-matrix strategy (documented choice):** truncate long model names to keep columns aligned, and cap
  at 8 columns with a `… N more — use --json-out` note. Transposition (cases-as-columns) was rejected —
  suites usually have many cases, which reads worse wide. 6 models fit; >8 truncates.
- **A "failed model" renders two ways:** a raised column (`run is None`) → `FAILED` summary + `·` cells; a
  bad model whose cases error (`provider_error`) → the column completes with `✗` cells and 0% pass. The
  renderer keys off `col.run is None` vs the per-case `passed`, so both are handled without special cases.
- **Golden-file gotcha:** generate the fixture from the exact test input, eyeball it, commit it, then assert
  byte-equality. Same `parents[2]` fixture-path rule as other adapter tests (`tests/unit/adapters/` → up 2 to
  `tests/`). And keep test basenames unique tree-wide (the DF-307 `test_compare.py` clash).

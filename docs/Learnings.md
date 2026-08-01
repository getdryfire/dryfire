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
`all = ["agentcheck[anthropic,openai]"]` composes extras without duplicating version pins.
uv resolves it fine.

### Docker venv outside the bind mount
`UV_PROJECT_ENVIRONMENT=/opt/venv` in the image plus an anonymous volume over `/app/.venv`
in compose. Otherwise mounting the repo into the container shadows the Linux venv with the
host's macOS one and every binary breaks. (terms-pilot solves this with selective per-dir
mounts; a relocated venv is simpler for a single-package repo.)

### Frozen spikes stay frozen
`spikes/` is ruff-excluded (`extend-exclude`). They are verified reference implementations
(19 passing fingerprint tests); reformatting or "fixing" them risks drift from what the
spikes actually proved.

---

## What Doesn't Work

### Zero-test pytest in CI
`pytest` exits **5** when no tests are collected, which fails the build. AC-001 said "zero
tests is acceptable" — it isn't, mechanically. Keep at least one smoke test.

### Typer `--version` without `invoke_without_command=True`
A callback-only Typer app with `invoke_without_command=False` rejects
`agentcheck --version` with "Missing command" (exit 2). Eager options on the callback need
`invoke_without_command=True`.

### Plain `uv sync` for development
Dev tools live in the `dev` **extra** (per ticket AC-001's spec), not a PEP 735 dependency
group — so plain `uv sync` installs no pytest/ruff/mypy. Always `uv sync --all-extras`
(or `make setup` / `make sync`).

---

## Repo Gotchas

- `FINDINGS_2.md` is SPIKE-**003** and `FINDINGS_3.md` is SPIKE-**002** — the filenames
  don't match the spike numbers.
- Banned synonyms (ARCHITECTURE §3): don't say test/example for Case, log/result for
  Trace, step for Turn, client/service for Gateway. A CI check will eventually enforce
  this; write with the ubiquitous language now.
- Exit codes 0/1/2/3 are contractual (SPEC §7.1). `spikes/render.py` already honors
  exit 2 for spec errors — `make spike-errors` masks it with `|| true` deliberately.

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
only scopes to `agentcheck/`, so the stub-vs-protocol check isn't in the standard gate.

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
`make typecheck` only scopes to `agentcheck/`, and nothing there binds a `FakeGateway` to a
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
"structural, not inheritance" (criterion 6). `make typecheck` only covers `agentcheck/`, so
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
error if absent). So `import agentcheck` and the offline unit tests need no SDK. Test the
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
`agentcheck.domain` and `agentcheck.application` from importing `agentcheck.adapters.driven` — the
**CLI (`adapters.driving`) is not in that source list**, so the import is legal (the contract note
even says "only composition.py and the CLI may import concrete driven adapters"). Keep the SDK-free
bundled loader's file read lazy (in `__init__`, not at import) so `import agentcheck` stays cheap.

### Package data ships by default under hatchling
`data/pricing.yaml` is included in the wheel with no extra `force-include`/`artifacts` config —
`[tool.hatch.build.targets.wheel] packages = ["agentcheck"]` pulls in non-`.py` files under the
package. Verified with `uv build --wheel` + `unzip -l`. Access it via
`importlib.resources.files("agentcheck").joinpath("data/pricing.yaml")` (robust for editable *and*
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
`make typecheck` scopes to `agentcheck/` (and the `tests.*` override relaxes untyped defs). Running
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
import. `make typecheck` is scoped to `agentcheck/` so it's unaffected, but to keep the test-file
conformance check clean add `[[tool.mypy.overrides]] module = "jsonschema.*"` with
`ignore_missing_imports = true`. Also: monkeypatching a module's imported `os`/`json` via
`monkeypatch.setattr(mod.os, ...)` trips mypy's `attr-defined` (not an explicit export) — use the
string-target form `monkeypatch.setattr("pkg.mod.os.replace", boom)` instead.

## CLI + composition (AC-015)

### composition.py is above the layers — it may import everything
The import-linter `layers` contract orders `adapters > application > domain`; `agentcheck.composition`
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

## Session Notes

### 2026-07-30 — AC-001 + toolchain
- Scaffolded the project (see `docs/Progress.md`), adopted Makefile/docs practices from
  `terms-pilot`, added Docker as a reproducible toolchain + local CI matrix only.
- Rejected for agentcheck: service containers, SOPS/age secrets (no team, no server, the
  only secret is `ANTHROPIC_API_KEY` for live tests), production Dockerfile (ships to
  PyPI), migrations/alembic (no database — tripwire in ARCHITECTURE §11).

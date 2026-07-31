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

## Session Notes

### 2026-07-30 — AC-001 + toolchain
- Scaffolded the project (see `docs/Progress.md`), adopted Makefile/docs practices from
  `terms-pilot`, added Docker as a reproducible toolchain + local CI matrix only.
- Rejected for agentcheck: service containers, SOPS/age secrets (no team, no server, the
  only secret is `ANTHROPIC_API_KEY` for live tests), production Dockerfile (ships to
  PyPI), migrations/alembic (no database — tripwire in ARCHITECTURE §11).

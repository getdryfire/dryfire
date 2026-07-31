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

## Session Notes

### 2026-07-30 — AC-001 + toolchain
- Scaffolded the project (see `docs/Progress.md`), adopted Makefile/docs practices from
  `terms-pilot`, added Docker as a reproducible toolchain + local CI matrix only.
- Rejected for agentcheck: service containers, SOPS/age secrets (no team, no server, the
  only secret is `ANTHROPIC_API_KEY` for live tests), production Dockerfile (ships to
  PyPI), migrations/alembic (no database — tripwire in ARCHITECTURE §11).

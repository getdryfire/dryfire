# agentcheck

Git-native regression testing for LLM agent tool loops. Assert on the
**trajectory** — the ordered sequence of tool calls — not the final text.

> **Status: pre-release.** v0.1 is in active development; the CLI currently only
> scaffolds (`--help` / `--version`). The instructions below set up the
> **development environment**. See [Project status](#project-status) for what
> exists today.

Agents don't fail by producing the wrong string. They fail by calling the wrong
tool, with the wrong arguments, in the wrong order, skipping an escalation, or
looping forever. agentcheck runs YAML-defined agent suites through the full
tool-calling loop with deterministic mocked tools and asserts on the trace.

Design commitments (see `SPEC.md` §1.4 — these are binding):

- **No server, no database, no account.** Everything is files on disk.
- **Everything is git-diffable.** Specs are YAML, traces are JSON.
- **Exit codes are the API.** The primary consumer is CI.
- **Framework-agnostic.** Talks to provider SDKs directly; never depends on an agent framework.

## What it will look like (target v0.1 — not implemented yet)

```yaml
# evals/refund_agent.eval.yaml
name: refund_agent
system: |
  You are a support agent. Never issue a refund over $500
  without escalating to a human first.
tools:
  - name: lookup_order
    input_schema: {type: object, properties: {order_id: {type: string}}}
  - name: issue_refund
    input_schema: {type: object, properties: {order_id: {type: string}, amount: {type: number}}}
  - name: escalate_to_human
    input_schema: {type: object}
mocks:
  lookup_order:
    - when: {order_id: "A-991"}
      return: {total: 780.00, status: delivered}
  escalate_to_human:
    - return: {ticket_id: "T-55", status: queued}
cases:
  - name: escalates_refund_over_limit
    input: "I want a refund for order A-991, it arrived broken."
    expect:
      - calls_tool: lookup_order
      - calls_tool: escalate_to_human
      - not_calls_tool: issue_refund
      - call_order: [lookup_order, escalate_to_human]
```

```bash
agentcheck run          # exit 0 = pass, 1 = assertion failure, 2 = spec error, 3 = provider error
```

---

## Development setup

### Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.12+ | comes via uv (below) — no pyenv needed |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.10 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` or `brew install uv` |
| GNU make | any | preinstalled on macOS/Linux |
| Docker Desktop | optional | only for `make docker-*` targets |

No API key is required for anything below — the entire test suite runs offline
by design (EPIC-001 success criterion 2).

### Option A — on the host (recommended for daily work)

```bash
git clone <repo-url> agentcheck && cd agentcheck

make setup     # uv sync --all-extras: creates .venv/, installs runtime + dev deps
make check     # full quality gate: lint + typecheck + architecture + tests
```

`make setup` matters: dev tools (pytest, ruff, mypy, import-linter) live in the
`dev` *extra*, so a plain `uv sync` will not install them.

Verify the CLI entry point:

```bash
uv run agentcheck --help
uv run agentcheck --version
```

### Option B — in Docker (clean Linux environment, no host Python needed)

```bash
git clone <repo-url> agentcheck && cd agentcheck

make docker-build       # build the dev image (Python 3.12 + uv, deps layer-cached)
make docker-check       # run the full quality gate inside the container
make docker-shell       # interactive bash inside the container
make docker-check-313   # run the gate on Python 3.13 — the CI matrix, locally
```

The source tree is bind-mounted into the container, so edits on the host are
visible immediately. There are deliberately **no service containers** (no
postgres/redis) and no production image — agentcheck is a zero-infra CLI that
ships to PyPI.

> The container's virtualenv lives at `/opt/venv` (`UV_PROJECT_ENVIRONMENT`),
> not `/app/.venv`, so the bind mount can't shadow it with your host venv.

---

## Running things

`make help` lists every target, categorized. The ones you'll use constantly:

| Command | What it does |
|---|---|
| `make check` | **The gate.** lint + typecheck + arch + test. Every ticket must pass it. |
| `make test` | Offline test suite (`tests/`) |
| `uv run pytest tests/unit/test_about.py -k name` | Single test |
| `make lint` / `make lint-fix` / `make format` | Ruff |
| `make typecheck` | mypy `--strict` on `agentcheck/` |
| `make arch` | import-linter — the five architecture contracts in `.importlinter` |
| `make test-live` | `@pytest.mark.live` tests; needs `ANTHROPIC_API_KEY` (pre-release only) |
| `make add pkg=X` / `make add-dev pkg=X` | Add a runtime / dev dependency via uv |
| `make build` | Build sdist + wheel into `dist/` |
| `make clean` / `make docker-clean` | Remove caches / project containers+images |

### Spike reference code

Three architectural spikes were run before implementation; their code is frozen
in `spikes/` (excluded from lint) and still runnable:

```bash
make spike-tests    # SPIKE-002: cassette fingerprint stability/sensitivity (19 tests)
make spike-probe    # SPIKE-001: provider adapter probe, offline canned payloads
make spike-errors   # SPIKE-003: positioned YAML spec errors demo (exits 2 by design)
```

Results and the amendments they forced are in `SPIKE-REPORT.md`.

---

## Project status

Shipped so far (details in `docs/Progress.md`):

- **AC-001 scaffold** — layered package (`domain/` → `application/` → `adapters/`),
  toolchain, CI matrix (3.12/3.13, no secrets), typer CLI stub
- **Architecture enforcement** — five import-linter contracts, mypy `--strict`,
  ruff ban on `unittest.mock` outside `tests/contracts/`
- **Makefile + Docker toolchain**

Next up: AC-002 (provider-neutral domain types), then the ticket sequence in
`EPIC-001.md` §5 through the v0.1 release (Anthropic provider, six structural
assertions, `init`/`validate`/`run`/`trace`, PyPI).

## Repository map

| Path | What it is |
|---|---|
| `SPEC.md` | Product spec — domain model, YAML format, agent loop, assertions, CLI, exit codes |
| `ARCHITECTURE.md` | How the code must be shaped (hexagonal; supersedes SPEC §8 layout) |
| `EPIC-001.md` + `TICKETS-*.md` | v0.1 plan and implementation tickets |
| `SPIKE-REPORT.md`, `FINDINGS_*.md` | Spike results and post-spike amendments |
| `docs/Progress.md` | Living tracker: in flight / up next / shipped / on ice |
| `docs/Learnings.md` | Accumulated pitfalls and patterns — read before contributing |
| `agentcheck/` | The package: `domain/` (pure), `application/` (ports + use cases), `adapters/` |
| `spikes/` | Frozen spike reference implementations |
| `CLAUDE.md` | Working agreement for AI-assisted sessions |

## Contributing / workflow

1. Pick the next ticket from `TICKETS-AC-*.md` (order per `EPIC-001.md` §5).
2. TDD, outside-in: the ticket's acceptance-criteria table is your red step
   (`ARCHITECTURE.md` §9).
3. Test doubles only at port boundaries — never mock a domain object
   (`unittest.mock` is lint-banned outside `tests/contracts/`).
4. `make check` must be green before the ticket closes. CI runs the same gate
   on 3.12 and 3.13 with no secrets configured.

## License

MIT — see [LICENSE](LICENSE).

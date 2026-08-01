# Contributing to dryfire

Thanks for your interest. dryfire is small, opinionated, and local-first; these notes keep
it that way.

## Setup

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.12+.

```sh
make setup        # uv sync --all-extras (dev tools live in the `dev` extra)
make help         # every target, categorized
```

## The gate

One command must pass before anything merges:

```sh
make check        # lint + typecheck + arch + test
```

That is: `ruff` (lint), `mypy --strict`, `import-linter` (architecture contracts), and the
offline `pytest` suite. Also useful:

```sh
make dogfood      # dryfire runs its own eval suite against the fake provider
make docker-check # the full gate in a clean Linux container (matches CI)
```

CI runs `checks` (Python 3.12 and 3.13) and a separate `dogfood` job. All three must be green.

## Ground rules

- **Test-driven.** Write the failing test first, watch it fail, then make it pass. No
  production code without a failing test.
- **Everything runs offline.** The full suite needs no network and no API key — determinism
  is a requirement, and a flaky test means a missing seam. Live-provider tests are marked
  `@pytest.mark.live` and run manually before a release.
- **Architecture is enforced, not suggested.** Dependencies point inward
  (`domain` ← `application` ← `adapters`, wired only in `composition.py`); `import-linter`
  fails the build otherwise. See [`ARCHITECTURE.md`](ARCHITECTURE.md).
- **Adding an assertion** = one new file in `domain/assertions/` + one registry entry. No
  `if kind == …` chains.
- **Test doubles only at port boundaries** (`FakeGateway`, …); never mock a domain object,
  construct it.
- **Scope discipline.** v0.1 is Anthropic-only; OpenAI, cassettes, JUnit, retries,
  `llm_judge`, `compare`, and friends are explicitly deferred (see `EPIC-001.md`). If a
  change seems to need one, open an issue first.

## Pull requests

Fill in `.github/pull_request_template.md` honestly — it mirrors the rules above. Keep the
gate green, keep public contracts (exit codes, YAML format, trace JSON) stable or flag the
break, and update `docs/Progress.md` when work ships.

## License

By contributing you agree your contributions are licensed under the MIT License.

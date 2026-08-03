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
offline `pytest` suite with a coverage floor (currently 92% — a ratchet, raise it when
coverage rises, never lower it). Also useful:

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
- **Scope discipline.** `llm_judge`, `compare`, an HTML report, `repeat`, export, streaming,
  and any server/database are deferred to v0.3+ (see CLAUDE.md "Scope discipline"). If a
  change seems to need one, open an issue first.

## Pull requests

`main` is protected: you can't push to it directly. Open a PR from a branch or fork; it
merges once the required checks (`checks (3.12)`, `checks (3.13)`, `dogfood`) are green, the
branch is up to date, review conversations are resolved, and a code owner (@csmatar) approves.
Merges are **squash-only**, so a PR lands as one commit on `main`.

Fill in `.github/pull_request_template.md` honestly — it mirrors the rules above. Keep the
gate green, keep public contracts (exit codes, YAML format, trace JSON) stable or flag the
break, and update `docs/Progress.md` when work ships.

## Your commit identity & email privacy

Squash-merge **preserves you as the commit author** on `main` — that's how you get credit,
and it's intended. Because this repo is public, any email in your commits becomes public
too. If you'd rather keep yours private, use GitHub's noreply address before committing:

- GitHub → **Settings → Emails** → enable **"Keep my email addresses private"** (and
  **"Block command line pushes that expose my email"**). GitHub gives you an
  `ID+username@users.noreply.github.com` address.
- Point git at it: `git config user.email "ID+username@users.noreply.github.com"`

You keep full attribution; only your real email stays private.

## License

By contributing you agree your contributions are licensed under the MIT License.

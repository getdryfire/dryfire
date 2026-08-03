.DEFAULT_GOAL := help
SHELL := /bin/bash

# ────────────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────────────
COMPOSE     := docker compose
DEV_SERVICE := dev

# ────────────────────────────────────────────────────────────────────────────
# Help
# ────────────────────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "; printf "\ndryfire — available targets\n\n"} \
		/^## / {section = substr($$0, 4); printf "\n\033[1m%s\033[0m\n", section; next} \
		/^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo

## Setup
.PHONY: setup
setup: ## One-time: install all deps including dev tools (uv sync --all-extras)
	uv sync --all-extras
	@echo "✓ Setup complete. Next: make check"

## Quality gate
.PHONY: check
check: lint typecheck arch test ## Full gate — every ticket must pass this before it closes

# Coverage floor — a ratchet, not a target. Raise it when coverage rises; never lower it.
COV_MIN ?= 92

.PHONY: test
test: ## Run the offline test suite with coverage gate (no network, no API key)
	uv run pytest --cov=dryfire --cov-report=term-missing --cov-fail-under=$(COV_MIN)

.PHONY: test-live
test-live: ## Run live provider tests (needs ANTHROPIC_API_KEY; run before release)
	uv run pytest -m live

.PHONY: lint
lint: ## Ruff lint (also bans unittest.mock outside tests/contracts/)
	uv run ruff check .

.PHONY: lint-fix
lint-fix: ## Ruff lint with auto-fix
	uv run ruff check --fix .

.PHONY: format
format: ## Ruff format
	uv run ruff format .

.PHONY: typecheck
typecheck: ## Mypy --strict on dryfire/ (config in pyproject.toml)
	uv run mypy

.PHONY: arch
arch: ## Enforce the five architecture contracts (.importlinter)
	uv run lint-imports

## Dependencies
.PHONY: add
add: ## Add a runtime dep (usage: make add pkg=httpx)
	@test -n "$(pkg)" || (echo "Usage: make add pkg=<package>" && exit 1)
	uv add $(pkg)

.PHONY: add-dev
add-dev: ## Add a dev tool to the dev extra (usage: make add-dev pkg=pytest-cov)
	@test -n "$(pkg)" || (echo "Usage: make add-dev pkg=<package>" && exit 1)
	uv add --optional dev $(pkg)

.PHONY: remove
remove: ## Remove a dep (usage: make remove pkg=httpx)
	@test -n "$(pkg)" || (echo "Usage: make remove pkg=<package>" && exit 1)
	uv remove $(pkg)

.PHONY: lock
lock: ## Regenerate uv.lock
	uv lock

.PHONY: sync
sync: ## Sync .venv from lockfile (all extras)
	uv sync --all-extras

## Docker
.PHONY: docker-build
docker-build: ## Build the dev image (Python 3.12)
	$(COMPOSE) build $(DEV_SERVICE)

.PHONY: docker-check
docker-check: ## Run the full gate inside the container (clean Linux env)
	$(COMPOSE) run --rm $(DEV_SERVICE) make check

.PHONY: docker-test
docker-test: ## Run the offline test suite inside the container
	$(COMPOSE) run --rm $(DEV_SERVICE) make test

.PHONY: docker-shell
docker-shell: ## Open a bash shell inside the container
	$(COMPOSE) run --rm $(DEV_SERVICE) bash

.PHONY: docker-check-313
docker-check-313: ## Full gate on Python 3.13 (run the CI matrix locally)
	$(COMPOSE) --profile matrix run --rm dev-313 make check

.PHONY: dogfood
dogfood: ## AC-018: dryfire runs its own eval suite (offline, no API key)
	./scripts/run_dogfood.sh

.PHONY: smoke
smoke: ## AC-016: time install -> init -> run, assert under the 60s target
	./scripts/measure_cold_start.sh

.PHONY: docker-smoke
docker-smoke: ## Measure cold start in a clean Linux container (the fair number)
	$(COMPOSE) run --rm $(DEV_SERVICE) ./scripts/measure_cold_start.sh

.PHONY: docker-clean
docker-clean: ## Remove this project's containers and images
	$(COMPOSE) --profile matrix down --rmi local --remove-orphans

## Docs

.PHONY: docs
docs: ## Build the MkDocs site to site/ (strict — warnings are errors)
	uv run mkdocs build --strict

.PHONY: docs-serve
docs-serve: ## Preview the docs site locally at http://127.0.0.1:8000
	uv run mkdocs serve

## Build & clean
.PHONY: build
build: ## Build sdist + wheel into dist/
	uv build

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true

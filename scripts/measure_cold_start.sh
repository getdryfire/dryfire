#!/usr/bin/env bash
# AC-016 — measure the cold-start adoption target (SPEC §1.6).
#
# Times a from-scratch install → `agentcheck init` → `agentcheck run` in an
# isolated venv, with NO API key, and asserts the total wall-clock is under the
# budget (default 60s). This is a measurement, not a judgement — the number it
# prints goes in the PR. Run it in a clean container for a fair number:
#
#     make docker-smoke        # clean Linux, matches CI
#     make smoke               # locally (uses your uv cache — optimistic)
#
# Exit codes: 0 under budget and green · 1 over budget or the run failed.
set -euo pipefail

BUDGET="${COLD_START_BUDGET_SECONDS:-60}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

# No key: the scaffolded example must go green without one.
unset ANTHROPIC_API_KEY || true

echo "==> measuring cold start (budget ${BUDGET}s), repo: $REPO"
start=$(date +%s)

# 1. install into a fresh environment
uv venv "$WORK/venv" >/dev/null
VENV_BIN="$WORK/venv/bin"
uv pip install --quiet --python "$VENV_BIN/python" "$REPO"

# 2. scaffold + 3. run, from an empty project directory
mkdir "$WORK/proj"
cd "$WORK/proj"
"$VENV_BIN/agentcheck" init
"$VENV_BIN/agentcheck" run

end=$(date +%s)
elapsed=$((end - start))

echo ""
echo "==> cold start: ${elapsed}s (budget ${BUDGET}s)"
if [ "$elapsed" -ge "$BUDGET" ]; then
  echo "FAIL: exceeded the ${BUDGET}s adoption target." >&2
  exit 1
fi
echo "OK: under the ${BUDGET}s adoption target."

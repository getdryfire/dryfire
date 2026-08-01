#!/usr/bin/env bash
# AC-018 — dogfood: agentcheck runs its own eval suite against FakeProvider.
#
# Proves the tool works by using it, entirely offline (no API key, no network).
# The trick with a test runner is that a *failing* case is a success: the suites
# in evals/self/ include cases that must FAIL, and this harness is green only
# when the expected-pass suite passes AND the expected-fail suite fails. It also
# checks that all four termination reasons were actually exercised.
#
# Exit 0 = the tool behaved as advertised. Exit 1 = a dogfood regression.
#
# Not `set -e`: we invoke `agentcheck run` expecting non-zero exit codes and
# check them deliberately.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="$REPO/evals/self"
AC=(uv run --project "$REPO" agentcheck)

JSON_DIR="$(mktemp -d)"
trap 'rm -rf "$JSON_DIR"' EXIT
unset ANTHROPIC_API_KEY || true

fails=0

# run_bucket <expected_exit> <label> <suite.yaml>
# Captures the JSON report (needed for termination coverage) and asserts exit.
run_bucket() {
  local expected="$1" label="$2" suite="$3"
  "${AC[@]}" run "$suite" --reporter json >"$JSON_DIR/$label.json" 2>"$JSON_DIR/$label.err"
  local got=$?
  if [ "$got" -ne "$expected" ]; then
    echo "✗ $label: expected exit $expected, got $got"
    cat "$JSON_DIR/$label.err" >&2
    fails=1
  else
    echo "✓ $label: exit $got as expected"
  fi
}

echo "== running dogfood suites (offline, no API key) =="
run_bucket 0 pass  "$SELF/pass.eval.yaml"            # every case must pass
run_bucket 1 fail  "$SELF/fail.eval.yaml"            # every case must fail
run_bucket 3 error "$SELF/provider_error.eval.yaml"  # provider_error → exit 3

echo "== verifying per-case outcomes and coverage from the traces =="
# The aggregate exit code is not enough: the fail suite exits 1 even if only one
# of its cases fails, so a single expected-fail case that quietly starts passing
# would slip through. Parse the JSON and assert EACH case's polarity: every
# pass-suite case must pass, every fail-suite case must fail. Also confirm all
# four termination reasons and a sequence error-then-success were exercised.
python3 - "$JSON_DIR/pass.json" "$JSON_DIR/fail.json" "$JSON_DIR/error.json" <<'PY' || fails=1
import json, sys

pass_json, fail_json, error_json = sys.argv[1:4]
REQUIRED = {"end_turn", "max_turns_exceeded", "unmocked_tool", "provider_error"}
ok = True


def cases(path):
    with open(path) as fh:
        doc = json.load(fh)
    return [c for s in doc["suites"] for c in s["cases"]]


# Per-case polarity: every expected-pass case passes, every expected-fail fails.
for case in cases(pass_json):
    if not case["passed"]:
        print(f"✗ expected-pass case failed: {case['case_name']}")
        ok = False
for case in cases(fail_json):
    if case["passed"]:
        print(f"✗ expected-fail case PASSED (assertion stopped catching): {case['case_name']}")
        ok = False
if ok:
    print("✓ every pass-case passed and every fail-case failed")

# Termination + sequence coverage across all three suites.
seen, saw_error_result = set(), False
for path in (pass_json, fail_json, error_json):
    for case in cases(path):
        trace = case.get("trace")
        if not trace:
            continue
        seen.add(trace["termination"])
        for turn in trace["turns"]:
            if any(r["is_error"] for r in turn["tool_results"]):
                saw_error_result = True

for term in sorted(REQUIRED):
    if term in seen:
        print(f"✓ termination exercised: {term}")
    else:
        print(f"✗ termination NOT exercised: {term}")
        ok = False
if saw_error_result:
    print("✓ sequence error-then-success exercised")
else:
    print("✗ sequence error-recovery NOT exercised")
    ok = False

sys.exit(0 if ok else 1)
PY

if [ "$fails" -ne 0 ]; then
  echo "DOGFOOD FAILED — agentcheck did not behave as advertised." >&2
  exit 1
fi
echo "DOGFOOD OK — agentcheck passed its own eval suite."

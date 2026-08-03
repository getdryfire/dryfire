# Benchmark — structural-only suites are unchanged in v0.3

v0.3 adds judging, flakiness, and comparison. The binding promise of the epic was that
**none of it touches the default path**: a suite with no `llm_judge` and no `repeat` must
run at v0.2 speed and cost. This is the load-bearing property that keeps dryfire a
deterministic, free, never-flaky merge gate.

## Why there is no regression (architectural)

A structural-only suite takes **exactly the v0.2 code path**:

- **No judge stage.** Composition wires the judge enrichment callback *only* when a case
  actually uses `llm_judge`. A structural-only run passes `judge=None`, so the scheduler's
  judge branch is never entered and no judge cost is accounted.
- **No repetition expansion.** With `repeat: 1` (the default), the scheduler produces one
  unit per case and the aggregation returns the single result **unchanged** — byte-identical
  to v0.2. No pass-rate machinery runs.
- **No judge cost channel.** `judge_usage`/`judge_cost` stay at their zero/None defaults and
  never appear in the output; a structural-only trace serialises identically to v0.2.

There is, quite literally, no new code in the path.

## Empirical (reproducible)

```
$ uv run python scripts/benchmark_structural.py 50
cases          50
passed         50
exit code      0
wall clock     ~240 ms  (~4.8 ms/case)
judge activity 0 cases  (must be 0 — structural-only fast path)
total cost     0.0  (offline → 0)
```

The script (`scripts/benchmark_structural.py`) runs a 50-case `provider: fake`
structural-only suite and **asserts** the fast-path guarantees: exit 0, zero cases touched
the judge channel, and zero cost. The wall-clock is dominated by process/loop overhead, not
by anything v0.3 added — judging and repetition contribute exactly nothing when unused.

(Numbers are machine-dependent; the invariants — `judge activity 0`, `total cost 0` — are
not.)

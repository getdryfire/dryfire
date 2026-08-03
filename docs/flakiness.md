# Flakiness (`repeat: N`)

Agent behaviour is stochastic even at `temperature: 0` — provider-side nondeterminism is
real. A case that passes once may fail one time in five, and a single green run can't see
that. `repeat: N` runs a case N times and reports a **pass rate**, `k/N`.

```yaml
cases:
  - name: escalates_when_over_limit
    input: refund me $9000
    repeat: 5                  # run it five times
    require_pass_rate: 0.8     # pass the build if ≥ 4/5 pass (default 1.0 — all N)
    expect:
      - calls_tool: escalate_to_human
```

The result is a **rate, never a bare pass/fail**. `require_pass_rate` decides whether the
build passes: default `1.0` (all N must pass); relax it to tolerate known flakiness.

## Reading the terminal output

```
  ~ escalates_when_over_limit   4/5   95% CI 0.38–0.96   1 turns   5 tok   —   0.0s
  ✓ always_solid               5/5   ...
  ✓ short_check                3/3   repeat<5: wide interval   ...
```

- A **disagreeing** case (`0 < k < N`) is marked with `~` — flakiness *is the finding*, and
  it's the most interesting row: a case that passes 4/5 tells you more than one that passes
  5/5 or 0/5.
- The **Wilson 95% confidence interval** is shown for disagreeing cases only. It is the
  honest companion to `k/N`: a bare `4/5` looks like 80%, but with only five runs the true
  rate could be anywhere from 38% to 96%.

## What a pass rate actually means — read this before you trust `3/5`

A `k/N` from a handful of runs is a **weak** measurement. The confidence interval is wide:

| N  | observed | 95% interval  | width |
|----|----------|---------------|-------|
| 3  | 2/3      | 0.21–0.94     | 0.73  |
| 5  | 4/5      | 0.38–0.96     | 0.59  |
| 10 | 8/10     | 0.49–0.94     | 0.45  |
| 20 | 16/20    | 0.58–0.92     | 0.34  |

Even **N = 20 carries ±0.17**. N = 3 can't even express 80%. So:

- **The recommended minimum is `repeat: 5`.** Below it, dryfire prints a
  `repeat<5: wide interval` warning — it **warns, it never refuses** (measuring at N = 3 is
  doing *something*, just not much).
- Use `repeat` to *detect* flakiness (is this case flaky at all?), not to measure a rate to
  two decimal places. If you need a precise rate, you need a lot more runs than a CI budget
  usually allows.

## Cassettes and `repeat`

`repeat` measures nondeterminism, so it can't be replayed from a single recording. Each
repetition records and replays under its **own** cassette key, so a `repeat: 5` case stores
five distinct responses — never one response served five times (which would make every rate
a comforting `5/5` lie). In `replay` mode a repetition with no recording is a **cassette
miss (exit 3)**, not a fabricated result: you cannot honestly report a 5-run rate from 3
recordings. `repeat: 1` keys byte-for-byte as before, so existing cassettes stay valid.

# dryfire in CI

dryfire is built for your merge gate: **the exit code is the API**, and the default CI mode
is free, offline, and deterministic. Drop the Action into a workflow and a trajectory
regression turns the check red before it ships.

## The one block

```yaml
jobs:
  dryfire:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: getdryfire/dryfire@v0.2.0
        with:
          suites: "evals/**/*.eval.yaml"
```

Add `permissions: checks: write` at the workflow level so the JUnit result renders as a PR
check (without it the run still uploads the report artifact and still gates the job on the
exit code). The full working file is [`.github/workflows/example-usage.yml`](../.github/workflows/example-usage.yml).

## Exit codes are the contract

| Code | Meaning | Job result |
|---|---|---|
| `0` | all cases passed | ✅ pass |
| `1` | one or more assertion failures | ❌ fail |
| `2` | spec / config error (bad YAML, unknown assertion, unresolvable `impl:`) | ❌ fail |
| `3` | provider error (a live model call failed) | ❌ fail |

The Action fails the job on any non-zero code and prints the code in the log. These codes are
stable across versions — script against them.

## Replay is the default, and it's the point

`cassette-mode: replay` (the default) serves every model turn from a recorded **cassette**, so
CI makes **no API calls**: no key, no cost, no flakiness, identical every run. `provider: fake`
suites need no key either. This is the headline: a real agent-trajectory gate that runs for
free on every push.

To record cassettes (once, locally, with a key), run `dryfire run --cassette-mode record` and
commit the `.dryfire/cassettes/` directory. See [`cassettes.md`](cassettes.md) for what
invalidates a cassette. **Passthrough (`impl:`) cases are never recorded** — a real callable
can have side effects — so they run live and are unsuitable for a keyless replay gate.

## JUnit output

The Action always writes `dryfire-junit.xml` (via `--junit-out`, independent of `reporter`),
uploads it as the `dryfire-junit` artifact, and surfaces it as a check. A failing
`not_calls_tool` shows the case name and the full ordered trajectory in the check — the moment
that matters in review. You can also produce it directly:

```sh
dryfire run "evals/**/*.eval.yaml" --junit-out results.xml     # + terminal log
dryfire run "evals/**/*.eval.yaml" --reporter junit            # JUnit to stdout instead
```

`--reporter` chooses the stdout format (`terminal` | `json` | `junit`); `--json-out` and
`--junit-out` are independent file sinks that compose with it and with each other.

## Action inputs

| Input | Default | Notes |
|---|---|---|
| `suites` | `""` | Space-separated globs. Empty = the project default in `dryfire.yaml`. |
| `cassette-mode` | `replay` | `auto` \| `record` \| `replay` \| `off`. |
| `reporter` | `terminal` | Stdout format. JUnit XML is written to a file regardless. |
| `fail-fast` | `false` | Stop on the first failing case. |
| `version` | `""` | Install `dryfire==<version>` from PyPI. Empty installs the pinned action's own source (works before the PyPI publish). |

Outputs: `exit-code` and `junit-file`.

## Why composite (not Docker)

The Action is a **composite** action — it sets up Python and `pip install`s dryfire — so it
starts in seconds. A Docker action would pull an image on every run and feel slow; this must
feel instant.

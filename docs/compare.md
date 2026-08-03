# Comparing models (`dryfire compare`)

`compare` runs **one suite across N models** (or N prompt variants) and prints a matrix —
the answer to *"is the cheaper model good enough?"*, which is the question every team
running agents in production is asking.

```bash
dryfire compare --models claude-opus-4-8,claude-sonnet-5,claude-haiku-4-5 evals/*.eval.yaml
```

The matrix — models as columns, cases as rows:

```
compare by model — 3 models × 5 cases

  case                opus       haiku      sonnet
  ──────────────────  ─────────  ─────────  ─────────
  greets              ✓          ✓          ✓
~ refunds_gracefully  ✓          ✗          ✓
  escalates           ✗          ✗          ✗
~ handles_edge        ✓          ✗          ✗
  closes_ticket       ✓          ✓          ✓
  ──────────────────  ─────────  ─────────  ─────────
  pass rate           80%        40%        60%
  cost                $0.0500    $0.0100    $0.0490
  mean latency        850ms      300ms      820ms
```

**The disagreement is the finding.** A row marked `~` is a case that passes on one model and
fails on another — that is the whole reason to run `compare`, and it's a real character (not
just colour) so it survives a CI log and a `grep`. A wall of uniform checkmarks teaches
nothing; the `~` rows are where the model choice actually matters.

## Axes

- `--models a,b,c` — the same suite, one column per model.
- `--prompts p1.txt,p2.txt` — the same suite, one column per system-prompt variant.
- The two axes are **one at a time** in v0.3; combining them is refused with a clear message.

## Cost before you spend

Comparing four models across fifty cases is expensive, and nobody should discover that from
a bill. `compare` prints a **run estimate before it executes** — `N models × M case-runs =
K runs` — and above a threshold it **refuses without `--yes`** (so a CI job can't wander into
a large bill). Under `--cassette-mode=replay` the run is free, so the gate is skipped. Cost
per model is shown prominently in the matrix, because the usual question is whether the cheap
model is good enough.

`repeat` composes with `compare`: a repeated case across four models is `4 × N` runs, which
the same cost estimate surfaces — allowed, but you'll see the multiplier before you commit.

## HTML output

`--html-out matrix.html` writes the matrix as a **self-contained HTML file** (no CDN, no
build step, opens offline). A matrix of models × cases renders far better as an HTML table
than in a terminal — and it's the single most shareable artifact dryfire produces. See also
`dryfire report run.json --html-out report.html` to turn any recorded run into an offline
HTML report with expandable per-case detail.

## A note on cost estimation

The estimate is a **run count**, not a guessed dollar figure — token usage is unknowable
before a run, so dryfire reports the precise number of case-executions (cost scales with it)
rather than pretending to a dollar precision it doesn't have.

# LLM-as-judge (`llm_judge`)

Most dryfire assertions are **structural** — they read the ordered tool calls and pass
or fail deterministically, for free, the same way every time. `llm_judge` is different:
it asks a model to grade the agent's behaviour against a rubric. Use it for the things a
structural check cannot express — *"did the agent apologise before refunding?"*,
*"was the explanation actually correct?"*

```yaml
cases:
  - name: refund_is_handled_gracefully
    input: I was double-charged and I'm furious.
    expect:
      - calls_tool: issue_refund                    # structural — deterministic, free
      - llm_judge:
          rubric: |
            Score 1.0 if the agent both apologised for the trouble AND confirmed the
            refund. Score 0.0 if it did neither. Partial credit otherwise.
          threshold: 0.7        # optional; defaults to 0.7
          model: claude-opus-4-8  # optional; defaults to the case's model
```

`rubric` is required and must be non-empty — an empty or missing rubric is a **spec
error at validate time** (exit 2), before any run and before any spend.

## ⚠️ Read this before you gate a merge on a judge

A judged assertion breaks the three properties the rest of dryfire guarantees. Be
deliberate about it:

- **It costs money.** Every `llm_judge` is an extra model call. A 50-case suite with one
  judge each is 50 extra calls per run. Judge cost is reported **separately** and never
  folded into the case cost, so it can't silently break `cost_under` — but it is real.
- **It varies between runs.** A judge is a model; two runs of the same case can disagree.
  A judged assertion is not deterministic the way `calls_tool` is.
- **It is not merge-gate-safe on its own.** A flaky judge failing your CI on a good agent
  is worse than no judge at all. **Gate a merge on a judged assertion only with a
  recorded cassette** (`--cassette-mode=replay`), which pins the judge's response so the
  run is deterministic and free again. Judge calls go through the same gateway as the
  agent, so they are cassette-backed automatically — record once, replay in CI.

The headline use of dryfire stays **deterministic structural testing in CI**. Judging is
an additive capability for behaviour structure can't capture — reach for it deliberately,
not by default.

## How it works (and why the numbers stay comparable)

The judge call is `temperature=0` always — a judge is an instrument, not a writer. The
model is asked for a JSON `{score, reasoning}`; the response is parsed defensively, so an
unparseable answer or a provider error is recorded as a **judge error** (a distinct
result, routed to exit 3), never a silent score of 0 that would fail a good case.

Every verdict carries its **provenance**: the judge model version and a **rubric hash**.
That hash changes whenever the rubric text (whitespace included), threshold, or examples
change. This is deliberate — a score produced under one rubric is **not comparable** to a
score produced under a different one, and the hash is what lets you tell. Reformatting a
rubric changes the hash because it may change the judgement.

A failure message carries the score, the threshold, the judge's reasoning, and the rubric
hash — enough to tell whether the agent was wrong or the rubric was.

## Judge cost is a separate channel

Judge calls cost money, and that cost is reported **separately** from the case cost — never
folded in. This is deliberate: if judging inflated a case's cost, `cost_under` would start
failing for reasons that have nothing to do with the agent under test, and you'd debug the
wrong thing. The terminal shows a `judge:` line only when a judge actually ran; a
structural-only run shows nothing.

## Judge drift — the failure mode most tools ignore

This is the most important page in these docs, because it describes the way LLM-as-judge
quietly lies to you over time.

A team charts "agent quality" over six months. The line moves. But two things drift
underneath a naive judge, and both move the line for reasons that have **nothing to do with
the agent**:

1. **The judge model changes.** `claude-opus-4-8` today is not byte-for-byte the model it
   resolves to next quarter. A model update shifts scores a few points across the board.
2. **The rubric changes.** Someone reworded the rubric, added an example, or even just
   reformatted the whitespace. The judge now grades a slightly different thing.

dryfire makes both **visible instead of silent**:

- **Every verdict pins `judge_model_version`** — the exact version the provider served, not
  just the alias you asked for. Two scores are only comparable if this matches. Pin your
  judge `model:` explicitly (don't rely on a floating alias) if you chart quality over time.
- **Every verdict carries a `rubric_hash`** — a stable hash of the rubric text (whitespace
  included), its threshold, and any examples. **A score produced under one rubric hash is
  not comparable to a score produced under a different one.** Reformatting a rubric changes
  the hash *because it may change the judgement* — that is correct, not a bug. Treat a
  changed rubric hash as a **new measurement**, not a continuation of the old series.

The rule: **a score without its judge-model version and rubric hash is not a measurement.**
dryfire refuses to construct a verdict without both.

## Recommended workflow

- **Pin the judge model** (`model: claude-opus-4-8-<dated-snapshot>`), don't float an alias.
- **Record cassettes** for anything that gates CI (`--cassette-mode=replay`) — that makes the
  judged run deterministic and free again, so it *is* merge-gate-safe.
- **Treat a changed rubric hash as a reset** of your quality series, not a dip or a spike.
- Keep the judge for behaviour structure can't express; keep the merge gate structural.

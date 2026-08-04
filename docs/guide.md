# Getting started

dryfire is a **unit test for an LLM agent's tool-calling behaviour**. You write cases in
YAML; dryfire runs the tool-calling loop with your tools **mocked deterministically**, and
asserts on the ordered **trajectory** — which tools the agent called, in what order, with
what arguments — not the final prose. It's local-first, needs no account or server, and the
**exit code is the API**, so it drops straight into CI.

This guide takes you from nothing to a green suite, then to a red one, then into CI. For the
formal grammar see [SPEC.md](https://github.com/getdryfire/dryfire/blob/main/SPEC.md); for
each capability in depth, follow the links at the end.

---

## Install

```sh
pip install dryfire            # or: uv add dryfire
```

Python 3.12+. Importing dryfire never pulls a provider SDK, and the offline example below
needs **no API key**. Add a provider only when you run against a real model:

```sh
pip install 'dryfire[anthropic]'   # Claude; 'dryfire[openai]' also covers Grok/Kimi/GLM/DeepSeek/OpenRouter
# Gemini needs no extra. Full list: see Providers.
```

---

## Your first suite in 60 seconds

Scaffold a runnable, keyless example and run it:

```sh
dryfire init
dryfire run
```

```
  ✓ reports_the_weather                 2 turns   0 tok   —   0.0s

1 cases   1 passed   0 failed   —   0.0s
```

That run made **no network calls**: the example uses a scripted fake model, so it's free,
offline, and identical every time. Exit code `0` means every assertion passed.

---

## Anatomy of a suite

A suite is one `*.eval.yaml` file. Here's a complete, annotated one — a refund agent that
must escalate large refunds instead of paying them:

```yaml
name: refund_agent           # the suite name (shown in output, used in cassette paths)
provider: anthropic          # which model backend; 'fake' for a scripted, keyless demo
model: claude-sonnet-4-6     # optional default model (override per case or with --model)
system: |                    # the system prompt under test
  You are a support agent. Refund orders UNDER $500 with issue_refund.
  For $500 or over you MUST call escalate_to_human instead — never refund it yourself.

tools:                       # the tool schema the model sees (name + JSON schema)
  - name: lookup_order
    description: Look up an order's total by id.
    input_schema: {type: object, properties: {order_id: {type: string}}}
  - name: issue_refund
    input_schema: {type: object, properties: {order_id: {type: string}, amount: {type: number}}}
  - name: escalate_to_human
    input_schema: {type: object, properties: {order_id: {type: string}}}

mocks:                       # deterministic tool results — no real side effects
  lookup_order:
    - when: {order_id: "B-2"}       # match on a deep subset of the parsed arguments
      return: {order_id: "B-2", total: 9000}
    - return: {total: 100}          # catch-all
  issue_refund:
    - return: {ok: true}
  escalate_to_human:
    - return: {ticket: "T-1"}

cases:                       # each case is one scenario
  - name: large_refund_escalates
    input: "Please refund order B-2."     # the user message that starts the loop
    expect:                               # assertions on the resulting trajectory
      - calls_tool: escalate_to_human
      - not_calls_tool: issue_refund
```

The **loop** dryfire runs: it sends `input` + the tools to the model, executes each tool call
the model makes against your **mocks** (never the real tool), feeds the results back, and
repeats until the model stops — recording every turn as a **trace**. Your assertions then run
against that trace.

Mocking is what makes trajectory tests cheap and reproducible. Rules match **in order,
first match wins**; each rule carries exactly one outcome (`return`, `error`, `sequence`, or
`impl:` passthrough). Full details: [Mocks](mocks.md).

---

## Assertions

Every assertion reads the whole trace and passes or fails deterministically. The core set:

| Assertion | Passes when |
|---|---|
| `calls_tool: X` | the agent called tool `X` |
| `not_calls_tool: X` | the agent never called `X` — the safety net |
| `tool_args: {tool: X, match: {...}}` | `X` was called with arguments matching (deep subset) |
| `call_order: [A, B]` | `A` then `B` appear in that order (as a subsequence) |
| `max_turns: N` | the loop finished within `N` turns |
| `final_contains: "..."` | the final text contains the substring |
| `min_tool_calls: {tool: X, count: N}` | `X` was called at least `N` times (retry recovery) |
| `final_matches: "regex"` | the final text matches a regex (compiled at load time) |
| `final_json: {required: [...], fields: {...}}` | the final text is JSON matching a shape |
| `cost_under: 0.05` | advisory cost is under a USD limit (an unpriced model fails loudly) |
| `latency_under_ms: 2000` | summed per-turn model latency is under a limit |

A failing assertion always prints the **ordered trajectory** that broke it, so you see exactly
what the agent did. Adding a new assertion is one file plus one registry line — no
`if kind == …` chains.

---

## Running

```sh
dryfire run evals/**/*.eval.yaml     # run some suites (globs are expanded for you)
dryfire run --filter refund          # only cases whose name contains "refund"
dryfire run --tag smoke              # only suites carrying a tag
dryfire run --model claude-opus-4-1  # override the model for the whole run
dryfire run --json-out run.json      # also write the full traces as JSON (for CI / the HTML report)
dryfire run --reporter junit         # terminal | json | junit
```

### Exit codes are the contract

| Code | Meaning |
|---|---|
| `0` | all cases passed |
| `1` | an assertion failed |
| `2` | a spec / config error (bad YAML, unknown assertion) — reported with line, column, and a caret |
| `3` | a provider / network error (or a cassette miss in replay) |

Drop `dryfire run` into any CI step and read the code — a red trajectory turns the job red and
names the offending tool call.

---

## Debugging a case

When a case fails and you want to see every turn:

```sh
dryfire trace refund_agent::large_refund_escalates evals/refunds.eval.yaml
```

It runs that one case and prints the full request/response/tool-result of each turn — the
fastest way to see *why* the agent did what it did.

---

## Deterministic runs in CI

Running against a real model costs money, adds latency, and can vary. **Cassettes** fix that:
record each model response once, then replay it forever — free, offline, deterministic.

```sh
dryfire run --cassette-mode=record   # once: record real responses to .dryfire/cassettes/
dryfire run --cassette-mode=replay   # in CI: serve from cassettes, never call the model
```

Commit the cassettes; CI replays them with **no API key**. A cassette is invalidated
automatically when anything that reaches the model changes (prompt, tools, model id). See
[Cassettes](cassettes.md) and, for the GitHub Action + JUnit setup, [CI](ci.md).

The one-liner for `.github/workflows/dryfire.yml`:

```yaml
- uses: getdryfire/dryfire@v0.3.0
  with:
    suites: "evals/**/*.eval.yaml"   # replay mode by default — free, offline, no key
```

---

## Going further (v0.3)

These are opt-in additions for behaviour a structural check can't express. The merge gate
stays structural, free, and deterministic; reach for these deliberately.

- **[LLM-as-judge](judging.md)** — `llm_judge` grades the trace against a rubric. It costs
  money and varies between runs, so cassette it before gating a merge. Every verdict pins the
  judge-model version and a rubric hash so scores stay comparable over time.
- **[Flakiness](flakiness.md)** — `repeat: N` runs a case N times and reports a `k/N` pass
  rate with a confidence interval, to catch nondeterminism a single run hides.
- **[Compare](compare.md)** — `dryfire compare --models a,b,c` runs one suite across models
  and prints a matrix (pass rate, cost, latency) — *is the cheaper model good enough?*
- **HTML report** — `dryfire report run.json --html-out report.html` turns a JSON artifact
  into a self-contained, offline HTML page with expandable per-case detail.

---

## Where next

- [SPEC.md](https://github.com/getdryfire/dryfire/blob/main/SPEC.md) — the formal reference:
  domain model, the full YAML grammar, the agent loop, every assertion, exit codes.
- [Mocks](mocks.md) · [Cassettes](cassettes.md) · [CI](ci.md) — the core capabilities in depth.
- [How dryfire compares](https://github.com/getdryfire/dryfire/blob/main/COMPARISON.md) to
  Promptfoo and DeepEval.

# evals

Trajectory tests for your agent. Each `*.eval.yaml` file is a **suite** of
**cases**; each case runs the full tool-calling loop with deterministic mocked
tools and asserts on the **ordered tool calls**, not the final text.

## Run them

```sh
dryfire run            # every suite listed in ../dryfire.yaml
dryfire run evals/hello.eval.yaml   # just one
dryfire validate       # parse + check specs, no model calls
dryfire trace hello_weather::reports_the_weather   # one case, turn by turn
```

Exit codes are the API: `0` all passed · `1` an assertion failed · `2` a spec or
config error · `3` a provider/network error.

## The two examples

- **`hello.eval.yaml`** — keyless. The model's turns are scripted
  (`provider: fake`), so it runs offline with no API key. Start here.
- **`refund_agent.eval.yaml`** — real. It calls Anthropic and needs
  `ANTHROPIC_API_KEY`; without the key `dryfire run` skips it (not a failure).

## Writing your own

Copy `hello.eval.yaml` and edit the `tools`, `mocks`, `script`, and `expect`
blocks. When you point a suite at a real provider, drop `script` and let the
model decide what to call — your `expect` block stays the same.

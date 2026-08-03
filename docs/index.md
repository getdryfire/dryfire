# dryfire

**Git-native regression testing for LLM agent tool loops.** Assert on the ordered *trajectory*
— which tools your agent called, in what order, with what arguments — not the final prose.

dryfire runs the tool-calling loop itself with your tools **mocked deterministically**, so every
run is free, offline, and identical. It's local-first — no account, no server, no database — and
the **exit code is the API**, so it drops straight into CI.

```sh
pip install dryfire
dryfire init      # scaffold a keyless example
dryfire run       # green, offline, no API key
```

```
  ✓ reports_the_weather                 2 turns   0 tok   —   0.0s

1 cases   1 passed   0 failed   —   0.0s
```

## Where to start

- **[Get started](guide.md)** — from zero to a green suite to CI, with an annotated example. **Start here.**
- **Core:** [Mocks](mocks.md) · [Cassettes](cassettes.md) · [CI](ci.md)
- **v0.3 — judgment & comparison:** [LLM-as-judge](judging.md) · [Flakiness](flakiness.md) · [Compare](compare.md)
- **Reference:** [SPEC](https://github.com/getdryfire/dryfire/blob/main/SPEC.md) ·
  [Architecture](https://github.com/getdryfire/dryfire/blob/main/ARCHITECTURE.md) ·
  [How it compares](https://github.com/getdryfire/dryfire/blob/main/COMPARISON.md)

## What it is not

dryfire is a pre-deployment unit test, and deliberately not more: not production observability,
not a hosted dashboard or account product, not dataset/labeling management, not an agent
framework. It stays a zero-infra local CLI.

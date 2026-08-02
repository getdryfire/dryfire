# dryfire — features and positioning

**Supersedes SPEC.md §1.4.** That table was written before verifying Promptfoo's current
feature set and claimed trajectory assertions as a gap. That claim is false — Promptfoo
ships a `trajectory:*` assertion family. Replace §1.4 with this document's content.

**AC-019 requires this comparison to be fair.** The "where X is better" sections are not
optional politeness — an unfair table gets the project dismissed by exactly the audience
whose opinion carries.

**Last verified: 2026-08-02**, against [promptfoo.dev](https://www.promptfoo.dev) and
[deepeval.com](https://deepeval.com). Both move fast (Promptfoo's roadmap is now OpenAI's);
re-verify every row on each release and correct — never quietly drop — any row that has gone
stale.

---

## Feature matrix by version

| Capability | v0.1 | v0.2 | v0.3 | v0.4 |
|---|:---:|:---:|:---:|:---:|
| **Execution** | | | | |
| Runs the tool-calling loop itself (no agent required) | ✅ | | | |
| Parallel tool calls in one turn | ✅ | | | |
| Concurrent case execution | ✅ | | | |
| Retries with backoff | | ✅ | | |
| **Tool mocking** | | | | |
| Declarative mocks, deep subset matching on args | ✅ | | | |
| Error injection | ✅ | | | |
| Sequences — error then success, for retry testing | ✅ | | | |
| Case-level mock overrides | ✅ | | | |
| Passthrough to real Python callables | | ✅ | | |
| **Trajectory assertions** | | | | |
| `calls_tool` / `not_calls_tool` | ✅ | | | |
| `tool_args` (deep subset) | ✅ | | | |
| `call_order` (subsequence) | ✅ | | | |
| `max_turns` | ✅ | | | |
| `final_contains` | ✅ | | | |
| `min_tool_calls`, regex, JSON-schema | | ✅ | | |
| `cost_under`, `latency_under_ms` | | ✅ | | |
| `llm_judge` (rubric-graded) | | | ✅ | |
| **Determinism** | | | | |
| Offline test suite, no API key needed | ✅ | | | |
| Cassette record/replay | | ✅ | | |
| `repeat: N` → pass-rate flakiness measurement | | | ✅ | |
| **Providers** | | | | |
| Anthropic | ✅ | | | |
| OpenAI | | ✅ | | |
| **Output** | | | | |
| Terminal reporter, trajectory shown on every failure | ✅ | | | |
| JSON run artifact (`--json-out`) | ✅ | | | |
| Positioned spec errors (line, col, caret, did-you-mean) | ✅ | | | |
| Contractual exit codes 0/1/2/3 | ✅ | | | |
| JUnit XML + GitHub Action | | ✅ | | |
| `compare` — model / prompt matrix | | | ✅ | |
| Self-contained HTML report | | | ✅ | |
| **Portability** | | | | |
| Cost reporting (advisory; `—` when model unknown) | ✅ | | | |
| Export to Python / TypeScript / Ruby | | | | ✅ |

---

## vs Promptfoo

| | dryfire | Promptfoo |
|---|---|---|
| License | MIT | MIT |
| Ownership | Independent | OpenAI (acquired March 2026) |
| Runtime | Python (`uv` / `pip`) | Node (`npm`) |
| Config in repo as YAML | ✅ | ✅ |
| CI-shaped, exit-code driven | ✅ | ✅ |
| Local-first, no account | ✅ | ✅ |
| **Trajectory assertions** | ✅ first-class | ✅ `trajectory:*` family |
| **How the trace is obtained** | Runs the loop itself, owns the trace | Ingests OTLP traces from your instrumented agent |
| **Instrumentation required** | None | OTLP tracing setup |
| **Declarative tool mocking** | ✅ subset match, errors, sequences | ❌ real tools, or a custom provider |
| **What is under test** | A prompt + tool-schema design, before an agent exists | Your built agent, wrapped in a custom provider |
| Deterministic offline replay | ✅ v0.2 cassettes | Response caching |
| Model comparison matrix | v0.3 | ✅ mature |
| LLM-as-judge | v0.3 | ✅ mature |
| **Red teaming / security scanning** | ❌ not planned | ✅ OWASP LLM Top 10, NIST AI RMF, MITRE ATLAS |
| Provider coverage | 2 (at v0.2) | Dozens |
| Production monitoring | ❌ | ❌ |
| Paid tier | None | Team $50/mo, Enterprise custom |
| Maturity | Pre-v0.1 | Mature, large ecosystem |

### Where Promptfoo is better

State this plainly in the README. It is true, and saying it earns the right to be believed
about everything else.

- Mature project, large ecosystem, dozens of providers, far larger assertion library.
- Model comparison and LLM-as-judge are mature there and unbuilt here until v0.3.
- Red teaming is an entire product dryfire will never have.
- Backed by real resources post-acquisition.

**If you are testing a built agent end to end, or you need security red-teaming, use
Promptfoo.**

### Where dryfire is different

- **Deterministic tool mocking.** Subset matching, error injection, and sequences. Without
  fake tools, trajectory tests hit real systems, carry side effects, and do not reproduce.
  This is the row doing most of the work.
- **Nothing to instrument.** dryfire drives the loop, so it owns the trace natively —
  no OTLP collector, no span normalisation, no tracing config.
- **Tests a design, not an app.** You can assert on tool-selection behaviour from a
  prompt-and-schema spec before any agent exists. Unit test, not integration test.
- **Python-native.** No Node in CI for Python shops.

### Positioning line

> dryfire is a unit test for tool-selection behaviour — deterministic, mocked,
> reproducible, with nothing to instrument. Promptfoo is an integration test for an agent
> you have already built.

The differentiator is not "we assert on trajectories." It is "we make trajectory
assertions cheap enough to run on every commit."

---

## vs DeepEval

The closest comparison — DeepEval is also Python-native, pytest-shaped, and evaluates agent
trajectories and tool calls. The difference is **determinism and instrumentation**.

| | dryfire | DeepEval |
|---|---|---|
| License | MIT | Apache-2.0 |
| Runtime | Python (`uv` / `pip`) | Python (`pip`) |
| Pytest-style, CI-shaped | ✅ (exit codes) | ✅ (`assert_test`, `deepeval test run`) |
| Local-first, no account | ✅ | ✅ (Confident AI platform optional) |
| **Trajectory / tool-call evaluation** | ✅ structural assertions | ✅ agent metrics (tool correctness, plan adherence, task completion) |
| **How the trace is obtained** | Runs the loop itself, owns the trace | Instrument your agent (`@observe` / integration); it emits traces |
| **Instrumentation required** | None | Yes — spans per LLM/tool/retriever |
| **Deterministic tool mocking** | ✅ subset match, errors, sequences | ❌ evaluates the agent's real runs |
| **Assertions need a judge model + key** | ❌ structural checks are exact and keyless | ✅ mostly — agent/quality metrics are LLM-as-judge |
| Metric library | small, structural | 50+ (LLM-judge, RAG, safety, conversational, multimodal) |
| What is under test | a prompt + tool-schema design, before an agent exists | your built, instrumented agent |
| Red teaming / security | ❌ not planned | via metrics, not a dedicated product |

### Where DeepEval is better

- **A vastly larger metric library** — 50+ metrics including mature LLM-as-judge, RAG,
  conversational, safety, and multimodal evaluation. dryfire has a handful of structural
  assertions and won't grow a judge until v0.3.
- **Evaluates the real, built agent** end to end, across reasoning/action/execution layers.
- Framework integrations and an optional observability platform (Confident AI).

**If you're scoring the quality of a built agent's outputs with judge-based metrics — plan
quality, answer relevance, faithfulness — use DeepEval.**

### Where dryfire is different

- **Deterministic, and no judge required.** dryfire's structural trajectory assertions are
  exact and need no model or API key; DeepEval's agent metrics are largely LLM-as-judge, so
  they need a judge model and don't reproduce bit-for-bit. dryfire trades breadth for a gate
  that is free and identical on every run.
- **Nothing to instrument.** dryfire drives the loop and owns the trace; DeepEval evaluates
  traces your instrumented agent emits.
- **Tests a design before the agent exists** — mock the tools, assert the tool-selection
  behaviour from a prompt-and-schema spec, with no agent to build or instrument first.

> DeepEval scores how good your built agent's answers are, with a rich judge-based metric
> library. dryfire is a deterministic, keyless gate on tool-selection behaviour you can run on
> every commit before the agent exists.

---

## vs Langfuse

A cleaner separation — these are complementary, not competing.

| | dryfire | Langfuse |
|---|---|---|
| Phase | Pre-deployment | Production |
| Shape | CLI, no server | Server + database + web UI |
| Input | Cases you wrote deliberately | Traces from live traffic |
| Requires instrumentation | No | Yes, SDK |
| Primary job | Stop a regression from shipping | Show what happened after it shipped |
| Team features | None | Dashboards, prompt management, datasets |

Langfuse tells you what your agent did. dryfire stops it from doing the wrong thing in
the first place. A team could reasonably run both.

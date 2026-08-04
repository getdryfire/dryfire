# Providers

dryfire drives the tool-calling loop against a model **provider**, chosen with `provider:` in a
suite (or `defaults:` in `dryfire.yaml`). The same suite, mocks, and assertions run against any of
them — only `provider:` and `model:` change.

Importing dryfire never pulls a provider SDK, and the offline example (`provider: fake`) needs no
key. Add a provider only when you run against a real model.

## Support matrix

| `provider:` | Model family | Wire family | Install | API key env var | Bundled pricing |
|---|---|---|---|---|---|
| `anthropic` | Claude | Anthropic Messages (native) | `dryfire[anthropic]` | `ANTHROPIC_API_KEY` | ✅ |
| `openai` | GPT | OpenAI Chat Completions (native) | `dryfire[openai]` | `OPENAI_API_KEY` | — |
| `gemini` | Gemini | Gemini `generateContent` (native) | none (built-in) | `GEMINI_API_KEY` | — |
| `xai` | Grok | OpenAI-compatible | `dryfire[openai]` | `XAI_API_KEY` | — |
| `moonshot` | Kimi | OpenAI-compatible | `dryfire[openai]` | `MOONSHOT_API_KEY` | — |
| `zhipu` | GLM | OpenAI-compatible | `dryfire[openai]` | `ZHIPUAI_API_KEY` | — |
| `deepseek` | DeepSeek | OpenAI-compatible | `dryfire[openai]` | `DEEPSEEK_API_KEY` | — |
| `openrouter` | many (aggregator) | OpenAI-compatible | `dryfire[openai]` | `OPENROUTER_API_KEY` | — |
| _your name_ | any OpenAI-compatible endpoint | OpenAI-compatible | `dryfire[openai]` | _your choice_ | — |
| `fake` | — (scripted turns) | — | none | none | n/a |

Notes:

- **Wire family** is how the request is translated, not who serves it. The five OpenAI-compatible
  providers reuse one adapter — they differ only in base URL and key — so `dryfire[openai]` is all
  they need. `gemini` speaks its own native API over HTTP and needs **no extra**. `dryfire[all]`
  installs the Anthropic and OpenAI SDKs together.
- **A missing key is a skip, not a failure.** `run` skips any real-provider case whose key is absent
  (and says so); `trace` treats it as an error, since tracing one case is an explicit request.
- **`openrouter`** reaches many frontier and open-weight models behind a single key — handy for
  trying models you don't have direct keys for. Model names are namespaced, e.g.
  `x-ai/grok-2-1212`, `deepseek/deepseek-chat`, `google/gemini-2.0-flash-001`.

## Pointing a suite at a provider

```yaml
# a real-provider suite
suite: refund-behaviour
provider: gemini
model: gemini-flash-latest        # xai/moonshot/zhipu/deepseek use that vendor's model ids
system: "You are a support agent. Use the tools. Be brief."
tools:
  - name: issue_refund
    input_schema: { type: object, properties: { order_id: { type: string } } }
cases:
  - name: refunds-a-late-order
    input: "Order A-991 arrived a week late. Refund it."
    expect:
      - calls_tool: issue_refund
```

Run it with the key in the environment:

```sh
export GEMINI_API_KEY=…      # or ANTHROPIC_API_KEY / OPENAI_API_KEY / XAI_API_KEY / …
dryfire run suites/refund.eval.yaml
```

Prefer to record once and replay free in CI? See [Cassettes](cassettes.md).

## Custom OpenAI-compatible providers

Any endpoint that speaks the OpenAI Chat Completions format — a self-hosted vLLM or Ollama server,
another aggregator, a private gateway — works without waiting for a built-in row. Define it once
under `providers:` in `dryfire.yaml`, then reference it by name anywhere `provider:` is accepted:

```yaml
# dryfire.yaml
version: 1
providers:
  my-llm:
    base_url: https://my-endpoint.example/v1   # the Chat Completions base URL
    api_key_env: MY_LLM_API_KEY                 # env var holding the key (a missing key skips, as usual)
```

```yaml
# a suite
provider: my-llm
model: my-org/my-finetune
```

The wire family is always OpenAI's, so tool calls, arguments, and finish reasons are translated
exactly as for the built-in compatible providers. A custom name can't shadow a built-in
(`anthropic`/`openai`/`gemini` always win), and custom endpoints have no bundled pricing — supply a
`pricing_file` if you want cost.

## Cost is advisory

dryfire ships bundled pricing only for Anthropic today; every other provider reports **no cost**
(`—`) rather than a guessed number — an unknown `provider:model` never fabricates a price. To get
cost for another provider, supply your own rates via `pricing_file` in `dryfire.yaml` (keyed
`provider:model`, USD per million tokens). The `cost_under` assertion simply doesn't fire when a
model is unpriced.

## Using a provider with its own key vs. via OpenRouter

The OpenAI-compatible providers are exercised in CI through OpenRouter, which normalizes every
response back into OpenAI shape. A provider called **directly, with its own key**, hits its native
endpoint, where subtle wire differences could surface that the OpenAI-shaped tests don't yet cover.
Direct-key support for `xai` / `moonshot` / `zhipu` / `deepseek` is therefore *OpenAI-assumed* until
real native payloads are captured
([issue #81](https://github.com/getdryfire/dryfire/issues/81)). `gemini` is native and
direct-key by construction, so it is unaffected.

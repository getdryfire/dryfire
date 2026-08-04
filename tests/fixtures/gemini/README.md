# Gemini fixtures — real `generateContent` payloads (spike #76, seed for #77)

Captured **live** against `models/gemini-flash-latest` (Google Generative Language API,
`v1beta`) during the #76 spike — not hand-written, not routed through OpenRouter. They are the
ground truth the native adapter (#77) is built and tested against.

| file | what it pins |
|------|--------------|
| `single_tool_call.json` | one `functionCall` part → `name` + `args` + **`id`** (current API *does* return ids), plus a `thoughtSignature` on the part. `finishReason: STOP` **even for a tool call**. |
| `parallel_tool_calls.json` | two `functionCall` parts in one `model` turn, each with its own `id`, order preserved. `finishReason: STOP`. |
| `text_only.json` | plain text answer, `finishReason: STOP`, `role: model`, a `thoughtSignature` accompanies even a text part. |
| `max_tokens.json` | truncated output → `finishReason: MAX_TOKENS` (a thinking model spends output budget on thoughts; `thoughtsTokenCount` in `usageMetadata`). |
| `final_after_tool.json` | the model's text answer *after* a `functionResponse` was returned. |

## Load-bearing facts these encode (see docs/Learnings.md)

- **`finishReason` never signals tool use** — Gemini returns `STOP` for a tool-call turn. The
  adapter must infer `tool_use` from the presence of `functionCall` parts, not the finish reason.
- **`thoughtSignature` must be echoed verbatim** on the model turn or the next tool turn is a
  `400` ("Function call is missing a thought_signature … required for tools to work correctly").
  This maps onto dryfire's existing `Message.raw` passthrough — the same seam Anthropic uses.
- **`functionResponse.id` is optional** (name/order matching works) but the API now provides an
  `id` on `functionCall`, so the adapter threads it like the other providers.
- Usage lives in `usageMetadata`: `promptTokenCount` / `candidatesTokenCount` /
  `totalTokenCount` / `thoughtsTokenCount` (+ `cachedContentTokenCount` when a cache is used).

Opaque `thoughtSignature` blobs are session artifacts, not secrets — safe to commit as fixtures.

# SPIKE-001 — FINDINGS

**Question:** does the provider-neutral model in SPEC §3 hold for both Anthropic and
OpenAI, or does it leak?

**Answer: it holds, with four required amendments.** Two of them are load-bearing and one
of them (`Message.raw`) would have been discovered painfully during v0.2.

---

## ⚠️ Status of this document

| Part | Status |
|---|---|
| Structural round-trip (does the neutral model express both wire formats?) | **Verified offline.** `probe.py --dry-run` against recorded-shape payloads. 26/26 checks pass on both providers. |
| Behavioural confirmation (do live responses match the recorded shapes?) | **NOT RUN.** No API keys available in the authoring environment. |

**Before AC-002 is closed, run both live:**

```bash
export ANTHROPIC_API_KEY=...  && python probe.py --provider anthropic
export OPENAI_API_KEY=...     && python probe.py --provider openai
```

Every canned payload in `probe.py::CANNED` must be replaced with the real response and the
checks must still pass. The structural conclusions below are stable regardless — they
follow from the documented request/response schemas, not from any particular completion.
What the live run confirms is that the *shapes* are right and that scenario (b) actually
elicits parallel calls.

---

## Answers to the spike's questions

### 1. Does one `stop_reason` enum cover both vendors without loss?

Almost. Mapping as implemented:

| Neutral | Anthropic | OpenAI | Lossless? |
|---|---|---|---|
| `end_turn` | `end_turn`, `pause_turn` | `stop` | ⚠️ `pause_turn` collapsed |
| `tool_use` | `tool_use` | `tool_calls`, `function_call` | ✅ |
| `max_tokens` | `max_tokens` | `length` | ✅ |
| `stop_sequence` | `stop_sequence` | — | ⚠️ OpenAI has no equivalent |
| `refusal` | `refusal` | `content_filter` | ❌ **not equivalent** |
| `error` | (fallback) | (fallback) | ✅ |

**Two genuine losses:**

- **`refusal` vs `content_filter` are different events.** Anthropic's `refusal` is the model
  declining; OpenAI's `content_filter` is a separate moderation layer intervening. Folding
  them loses the distinction. Accepted for v0.1 (neither terminates a tool loop
  differently) but the raw payload is retained on `ModelResponse.raw`, so a future
  `terminated_by_policy` assertion can recover it.
- **`stop_sequence` has no OpenAI analogue.** Harmless — `stop_sequences` is a param we
  hash but do not otherwise use.

**Unknown values must map to `error`, never raise.** A vendor adding a stop reason should
degrade a case, not crash a run.

### 2. Are tool-call arguments always parseable to `dict`?

**No — and this is a real divergence.**

- **Anthropic** returns `input` as an already-parsed object. Always a dict.
- **OpenAI** returns `function.arguments` as a **JSON string**, which can be truncated or
  malformed — most commonly when generation hits `max_tokens` mid-argument.

Verified:

```
input:    arguments = '{"order_id": "A-99'      (truncated)
output:   ToolCall.arguments = {}
          ToolCall.malformed_arguments = '{"order_id": "A-99'
```

**Failure policy: never raise, never silently coerce.** `ToolCall` gains a
`malformed_arguments: str | None` field. On a parse failure, `arguments` is `{}` and the
raw string is preserved.

This is not cosmetic. A `tool_args` assertion against a malformed call must **fail with a
message that says the arguments were malformed**, not report a confusing empty-dict
mismatch. Cases: non-JSON, valid JSON that isn't an object (e.g. `"[1,2]"`), and empty
string all route to the same policy.

### 3. Can tool results use one neutral shape?

**Yes, but only because the neutral shape is attached to a `Message` rather than being one.**
The vendors structure results incompatibly:

- **Anthropic:** results are `tool_result` **blocks inside a `user` message**. N parallel
  results ⇒ **one** message with N blocks.
- **OpenAI:** results are **separate messages** with `role: "tool"`. N parallel results ⇒
  **N** messages.

`Message.tool_results: list[ToolResult]` maps to both: the Anthropic adapter emits one
message with N blocks, the OpenAI adapter emits N messages. Verified in both directions.

**One lossy direction, confirmed by execution:**

```
anthropic wire: {"type":"tool_result","tool_use_id":"c1","content":"gateway timeout","is_error":true}
openai    wire: {"role":"tool","tool_call_id":"c1","content":"ERROR: gateway timeout"}
```

**OpenAI has no `is_error` flag.** The neutral `is_error=True` must be encoded into the
content text. Consequences that must be documented, not hidden:

1. The `ERROR: ` prefix is prompt content the model sees. Error-recovery behaviour will
   therefore differ between providers for the *same* spec — which is a legitimate finding
   for users to observe, not a bug to paper over.
2. The prefix must be a named constant, not a literal, so it is greppable and overridable.

### 4. Does either vendor require the assistant turn echoed back verbatim?

**Yes — Anthropic.** It validates that `tool_use` ids in a replayed assistant turn match
what it issued, and rejects reconstructions that drop or reorder blocks.

**This forces a new field: `Message.raw: dict | None`** — a provider-opaque passthrough,
populated by `from_wire` and replayed verbatim by `to_wire` when present, with block
reconstruction as the fallback. Without it, every multi-turn Anthropic case breaks at
turn 2.

**Interaction with SPIKE-002 (important):** ids must be preserved **verbatim on the wire
path** while being **normalised on the fingerprint path**. Two representations, one source
of truth. Neither spike is correct without the other; whoever implements AC-007 must read
both verdicts.

### 5. Are tool-call ids stable and always present?

Present and unique within a response for both vendors, in documented formats (`toolu_…`,
`call_…`). **Not stable across requests** — a fresh id is minted every time, which is the
entire reason SPIKE-002 needs id normalisation.

Adapters must treat ids as **opaque**: never parse, never assume a prefix, never
regenerate. Correlation is by exact string match only.

### 6. What must be excluded from a request fingerprint?

Delivered to SPIKE-002 and already incorporated there. In brief: exclude auth, headers,
user-agent, request ids, timestamps, retry counters, and adapter version; normalise
tool-call ids. Note the vendor-specific id key names — Anthropic uses `tool_use_id` on the
result side where OpenAI uses `tool_call_id` — which SPIKE-002's test caught.

---

## Verdict

**The types in SPEC §3 hold as written, with four amendments.** No change to the `Provider`
protocol; both adapters were expressible as pure `to_wire` / `from_wire` with no loop, no
retry, and no assertion knowledge. The abstraction is sound.

### Required amendments to SPEC §3

```python
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict
    malformed_arguments: str | None = None   # NEW — see Q2

class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str | list[dict] | None = None
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    raw: dict | None = None                  # NEW — see Q4
```

1. **`ToolCall.malformed_arguments`** — OpenAI can emit unparseable argument strings.
2. **`Message.raw`** — Anthropic requires verbatim echo of assistant tool-call turns.
3. **`StopReason` mapping table** — add §3.3 with the table from Q1, including the explicit
   note that `refusal`/`content_filter` are not equivalent and that unknown values map to
   `error` rather than raising.
4. **`ToolResult.is_error` is lossy for OpenAI** — document in §3.1 that the adapter encodes
   it into content via a named constant, and that error-recovery behaviour is therefore
   provider-dependent for an identical spec.

### Required amendments to §3.1 (Provider protocol contract)

- An adapter must treat tool-call ids as opaque strings.
- An adapter that introduces a new tool-call id key name must add it to SPIKE-002's
  `_CALL_ID_KEYS`.
- An adapter must never raise on an unrecognised stop reason.

### New acceptance criteria for AC-002 / AC-007

- [ ] `probe.py` run **live** against both providers; canned payloads replaced with real
      responses; all checks still pass.
- [ ] A malformed-arguments fixture produces `arguments={}` plus populated
      `malformed_arguments`, and never raises.
- [ ] A `tool_args` assertion against a malformed call fails with a message naming
      malformed arguments as the cause (blocks AC-011).
- [ ] An Anthropic multi-turn case replays the assistant turn from `Message.raw` and is
      accepted by the API.
- [ ] Unknown stop reasons map to `error` (unit test with a synthetic value).

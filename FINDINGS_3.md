# SPIKE-002 — FINDINGS

**Question:** what is a request fingerprint that is stable under irrelevant change and
sensitive to relevant change?

**Answer:** SHA-256 over canonical JSON of a *reduced* request, with **provider-generated
tool-call ids normalised away**. That last clause is the whole spike — without it,
cassettes work for turn 1 and never hit again for the rest of the loop, which for an
agent-testing tool means they don't work at all.

`pytest test_stability.py` → **19 passed**. Fingerprint verified identical across
processes under `PYTHONHASHSEED=random`.

---

## The critical finding: tool-call ids

Turn 2 of every agent loop echoes the assistant's tool calls — and their ids — back to the
provider. Those ids (`toolu_01ABCdefGHI`, `call_9xKq…`) are generated per request and are
**not reproducible**. Hash them raw and:

- turn 1 of a case: cassette hits
- turn 2+ of every case: cassette **always misses**

The feature would appear to work in the demo (single tool call) and silently fail for the
multi-turn trajectories that are this product's entire reason to exist.

**Fix:** before hashing, rewrite every tool-call id to a positional placeholder
(`call_0`, `call_1`, …) assigned in first-appearance order across the message list. This
is deterministic and preserves the call↔result correspondence, so two structurally
identical conversations hash identically regardless of what ids the provider minted.

### Sub-finding: the id key names are vendor-specific

The initial implementation remapped `id`, `call_id`, `tool_call_id` — and the test failed,
because Anthropic references a call from the result side as **`tool_use_id`**, not
`tool_call_id`. Final key set:

| Provider | Call side | Result side |
|---|---|---|
| Anthropic | `id` on `tool_use` blocks | `tool_use_id` on `tool_result` blocks |
| OpenAI | `id` on `tool_calls[]` | `tool_call_id` on tool-role messages |

`_CALL_ID_KEYS` is therefore a **vendor-coupled constant**. Every new provider adapter must
audit it, and that obligation belongs in the provider-adapter checklist, not in a comment
someone will miss. **This is a direct dependency on SPIKE-001 Q4/Q5** — if a provider
requires its tool-call message echoed back verbatim including its id, normalisation must
happen *only* on the hash path and never on the wire path.

---

## Answers to the spike's questions

### 1. Final field list

**Hashed** — everything that reaches the model:

| Field | Rationale |
|---|---|
| `schema_version` | forces wholesale invalidation on format change |
| `provider`, `model` | different weights ⇒ different response |
| `system` | prompt text, whitespace-significant |
| `messages` (ids normalised) | the conversation |
| tool `name` | model selects on it |
| tool `description` | **prompt text the model reads** — see below |
| tool `input_schema` | shapes generated arguments |
| `temperature`, `top_p`, `max_tokens`, `stop_sequences` | sampling behaviour |

**Excluded** — never reaches the model:
API keys, auth headers, user-agent, request ids, timestamps, retry counts, adapter/library
version, suite `name`/`description`/`tags`, case `name`, and any position metadata from the
YAML loader.

> ### ⚠️ This overturns one of the spike's own acceptance criteria
>
> EPIC-001 stated the fingerprint should be identical across "presence/absence of
> `description` on a tool." **That is wrong and I have implemented the opposite.** A tool
> description is prompt text — it is precisely how you steer tool selection. Excluding it
> means editing a description, re-running, seeing green, and shipping a regression. That is
> the false-stable failure mode, which is strictly worse than spurious invalidation.
>
> **Amend the AC-xxx cassette ticket accordingly.** Rule going forward: when stability and
> sensitivity conflict, sensitivity wins.

### 2. Is tool order in the hash?

**Yes.** Tools are transmitted as an ordered list and position can influence selection. We
cannot prove neutrality, and the asymmetry decides it: the cost of including order is one
unnecessary re-record after a cosmetic YAML reshuffle; the cost of excluding it is a
silently stale replay. Cheap versus dangerous.

### 3. On-disk layout

```
.agentcheck/cassettes/
  refund_agent/                                  # suite name
    escalates_refund_over_limit/                 # case name
      00-f0b4fbe056178ff6.json                   # turn index + fingerprint
      01-9c2ae41d7b3e08aa.json
```

Turn index prefix makes the directory read in loop order; the fingerprint makes it
content-addressed. A reviewer seeing this diff knows immediately which case changed and at
which turn — the stated requirement.

Cassette body:

```json
{
  "schema_version": 1,
  "fingerprint": "f0b4fbe056178ff6",
  "suite": "refund_agent",
  "case": "escalates_refund_over_limit",
  "turn": 0,
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "recorded_at": "2026-07-30T14:22:10Z",
  "request_digest": { "…": "reduced request, pretty-printed for review" },
  "response": { "…": "raw provider payload" }
}
```

`recorded_at` and the pretty-printed digest are for humans only and are **not** hashed.
Storing the reduced request alongside the response is what makes a stale cassette
debuggable instead of an opaque hex filename.

**Trade-off accepted:** path-based naming means renaming a suite or case orphans its
cassettes. Readability in git diffs is worth more than rename-resilience; add an
`agentcheck prune` command to delete orphans.

### 4. Cassette schema migration

`schema_version` is inside the hash input, so bumping it invalidates every cassette
globally by construction — no migration code, ever. Policy on mismatch or missing file:

| Mode | Behaviour |
|---|---|
| `auto` | re-record silently |
| `record` | re-record |
| `replay` | **exit code 3**, naming the missing fingerprint and its case. Never fall through to a live call. |
| `off` | ignore cassettes entirely |

`replay` never making a live call is the property that makes CI runs cost-bounded and
airgap-safe.

### 5. Does v0.1 need a field it currently lacks?

No new field — but it **validates one already in SPEC §3**: `Turn.request_messages`. The
fingerprint is computed per request, and requests are only reconstructable if each turn
retains what was actually sent. Without that field, cassettes could not be built in v0.2
without a v0.1 rewrite. Keep it, and add a v0.1 test asserting it is populated per turn.

Constraints on v0.1 that follow:

1. Tool-call ids must be preserved **verbatim** on the wire path. Normalisation exists
   only inside fingerprinting. Two representations, one source of truth.
2. Tool `description` must be retained through spec loading (not discarded as
   documentation).
3. Message content must be JSON-serialisable with no non-finite floats
   (`allow_nan=False`).

---

## Verdict

Adopt `fingerprint.py` as written. Lift `canonical_json`, `normalise_call_ids`,
`_CALL_ID_KEYS`, and `hashable_request` verbatim into `agentcheck/cassettes/fingerprint.py`
at v0.2; port `test_stability.py` unchanged as its regression suite.

**Amendments required to SPEC.md:**

1. **§9 (v0.2)** — replace the fingerprint field list with §1 of this document. The current
   text says the hash covers `{provider, model, system, messages, tools, temperature,
   top_p, max_tokens}`; make explicit that "tools" means name + description + input_schema
   **in order**, and that messages are id-normalised.
2. **§9 (v0.2)** — add the `schema_version`-in-hash rule and the four-mode table.
3. **§3** — annotate `Turn.request_messages` as load-bearing for v0.2 cassettes so nobody
   removes it as redundant.
4. **§3.1** — add to the `Provider` protocol contract: "an adapter that introduces a new
   tool-call id key name must add it to `_CALL_ID_KEYS`."

**Amendment required to EPIC-001:** the "presence/absence of tool `description`" stability
criterion is deleted and replaced with a sensitivity criterion.

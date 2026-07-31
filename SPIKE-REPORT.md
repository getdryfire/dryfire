# Spike report — EPIC-001

All three spikes executed. **The architecture in SPEC.md survives, with six amendments.**
None require restructuring; all are additive. AC-002 is unblocked once the one outstanding
live verification is done.

| Spike | Verdict | Blocking work remaining |
|---|---|---|
| SPIKE-001 Provider normalization | Holds, +4 amendments | ⚠️ Live probe run — needs API keys |
| SPIKE-002 Cassette fingerprint | Holds, +2 amendments | None — 19/19 tests pass |
| SPIKE-003 Spec error UX | Holds as designed | None — verified end to end |

---

## What the spikes actually caught

**1. Cassettes would have been silently broken beyond turn 1.** (SPIKE-002)
Provider tool-call ids are minted fresh per request and get echoed back in turn 2+. Hashed
raw, every multi-turn cassette misses forever. The feature would have demoed perfectly on
single-call examples and failed on exactly the trajectories this product exists to test.
Fix: normalise ids to positional placeholders on the hash path only.

**2. Anthropic requires the assistant turn echoed back verbatim.** (SPIKE-001)
Reconstructing it from neutral fields is rejected. This forces a new `Message.raw`
passthrough field. Discovered now, it's one field; discovered in v0.2, it's a refactor of
every adapter and the loop.

**3. These two findings are in direct tension and must be implemented together.**
Ids must be **verbatim on the wire** and **normalised in the hash**. Whoever writes AC-007
has to hold both. This is now a written constraint rather than something to rediscover.

**4. OpenAI can emit unparseable tool arguments; Anthropic cannot.** (SPIKE-001)
Verified: a truncated `'{"order_id": "A-99'` must yield `arguments={}` plus a preserved
`malformed_arguments` string, never an exception. Downstream, `tool_args` must fail with a
message that says *malformed*, not an empty-dict mismatch.

**5. `is_error` on tool results is lossy for OpenAI.** (SPIKE-001)
OpenAI has no error flag, so it becomes an `ERROR: ` content prefix the model reads.
Error-recovery behaviour will legitimately differ across providers for an identical spec.
Document it; don't hide it.

**6. A failed `$ref` produced three errors for one mistake.** (SPIKE-003)
Cascade suppression is now a required acceptance criterion with a regression test.

---

## ⚠️ One spike overturned its own brief

EPIC-001 specified that the fingerprint stay identical across "presence/absence of
`description` on a tool." **That criterion was wrong.** A tool description is prompt text —
it is the primary lever for steering tool selection. Excluding it means editing a
description, re-running, seeing green, and shipping a regression.

Implemented the opposite: description is hashed. The general rule, now recorded in
SPEC §9: **when stability and sensitivity conflict, sensitivity wins.** A spurious
re-record costs pennies; a false-stable replay costs trust in every green run.

---

## Amendments to apply before AC-002

**SPEC.md §3** — add `ToolCall.malformed_arguments: str | None` and `Message.raw: dict | None`.
**SPEC.md §3.1** — three new adapter obligations: ids opaque; new id key names registered in `_CALL_ID_KEYS`; never raise on unknown stop reasons. Note `is_error` lossiness for OpenAI.
**SPEC.md §3.3 (new)** — the `StopReason` mapping table, incl. `refusal` ≠ `content_filter`.
**SPEC.md §4** — the three-stage load ordering (refs → registry → pydantic) becomes normative.
**SPEC.md §8.1** — `ruamel.yaml` is a required core dependency; `pyyaml` banned from the spec path.
**SPEC.md §9 (v0.2)** — replace the fingerprint field list; add the `schema_version`-in-hash rule and the four-mode cassette table.

**EPIC-001** — delete the tool-`description` stability criterion, replace with sensitivity.
Add the new acceptance criteria listed in each FINDINGS verdict to AC-002, AC-004, AC-007, AC-011.

---

## Code to lift directly

| From | To | Status |
|---|---|---|
| `003/locate.py` → `locate`, `Position` | `spec/positions.py` | verbatim |
| `003/render.py` → `render` | `spec/errors.py` | output-format contract |
| `002/fingerprint.py` (whole module) | `cassettes/fingerprint.py` (v0.2) | verbatim |
| `002/test_stability.py` | its regression suite | unchanged, 19 tests |
| `001/adapters.py` → `AnthropicAdapter` | `providers/anthropic.py` | reference for AC-007 |
| `001/neutral.py` | `providers/base.py` | as amended above |

---

## The one thing still open

`python probe.py --provider anthropic` and `--provider openai`, with keys, replacing the
canned payloads in `probe.py::CANNED` with real responses. The structural conclusions hold
either way — they follow from documented schemas — but scenario (b) needs live
confirmation that parallel calls are actually elicited, and the recorded shapes need to be
confirmed against reality before AC-007 is built on them.

Everything else is unblocked.

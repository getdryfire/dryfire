# Cassettes — record once, replay free

A **cassette** is a recorded model response. Record your suite against a real provider once,
commit the cassettes, and every CI run afterward **replays** them: no API key, no cost, no
network, and byte-identical results every time. This is what makes a real agent-trajectory
suite cheap enough to run on every push.

Cassettes record only the **model turns**. Tool results still come from your deterministic
mocks (`return`/`error`/`sequence`), recomputed each run — so a cassette is small and captures
exactly the non-deterministic part: what the model said.

## Modes

Set with `--cassette-mode` (or `cassettes.mode` in `dryfire.yaml`):

| Mode | Behaviour |
|---|---|
| `replay` | Serve every turn from a cassette. **No API key, no network.** A missing recording is a `provider_error` (exit 3) telling you to record it. The CI default. |
| `record` | Call the real provider and write a cassette for every turn (overwriting). Do this once, locally, with a key. |
| `auto` | Replay when a cassette exists, record when it doesn't. Handy while writing new cases. |
| `off` | Ignore cassettes entirely; always call the provider. |

Typical flow:

```sh
dryfire run "evals/**/*.eval.yaml" --cassette-mode record   # once, local, with a key
git add .dryfire/cassettes && git commit -m "record cassettes"
# CI (and everyone else) now runs:
dryfire run "evals/**/*.eval.yaml" --cassette-mode replay    # free, offline, deterministic
```

## What keys a cassette — and what invalidates it

Each turn is looked up by a **fingerprint**: a hash of everything that determines what the
model would say. Change any of it and the fingerprint changes, so the old cassette no longer
matches and you must re-record. The fingerprint covers:

- the **model** id and **parameters** (e.g. temperature),
- the **system** prompt,
- the **messages** so far (the conversation, including prior tool results fed back), and
- the **tools** offered — each tool's **name, description, and input schema**, *and their order*.

Two deliberate subtleties keep replay stable without going stale:

- **Tool-call ids are normalised.** On the wire a provider emits opaque ids like
  `call_abc123`; on the fingerprint path these become positional placeholders (`call_0`,
  `call_1`, …), so a fresh random id from the provider doesn't bust your cache.
- **`Message.raw` is excluded.** The provider's opaque passthrough is full of
  non-reproducible ids and timestamps; hashing it would invalidate every cassette on every
  run, so it is stripped from the key.

### Why a tool's *description* is part of the key (the surprising one)

Editing a tool's `description` — even a typo fix, changing nothing about the schema —
**invalidates the cassette** and forces a re-record. This surprises people, so it's worth
saying plainly: **the tool description is part of the prompt.** The model chooses which tool
to call largely *from the descriptions*, so a description change can genuinely change the
trajectory. If replay kept serving the old recording, your test would pass against a response
the model would no longer give — a green that lies.

The rule when stability and sensitivity conflict is **sensitivity wins**: dryfire would rather
make you re-record than silently replay a stale answer. Tool **order** is hashed for the same
reason — order can affect selection. So when a description tweak triggers a re-record, that's
the design working, not a bug.

A **schema-version bump** in dryfire also invalidates cassettes on purpose, when the recording
format itself changes.

## Passthrough cases are never recorded

A case that uses a passthrough mock (`impl:`) runs real code whose output can have side effects
or vary run to run, so recording it would make replay a lie. Those cases are **excluded from
recording** with a visible note, and they run live — which means a passthrough case is not
suitable for a keyless replay gate. See [`docs/mocks.md`](mocks.md).

## Housekeeping

`dryfire prune` reports and (with `--yes`) deletes cassettes that no longer correspond to any
case — orphaned by a renamed suite or case, or left behind by a schema-version change — so the
`.dryfire/cassettes/` directory doesn't accumulate cruft.

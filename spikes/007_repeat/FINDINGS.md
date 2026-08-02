# SPIKE-007 — Repetition, cassette keying, and pass-rate meaning

**Type:** prototype spike · **Depends on:** none · **Status:** complete
**Date:** 2026-08-02

## Verdict

Two decisions, both prototyped and tested (`keying.py`, `stats.py`, 34 passing tests):

1. **Keying: the repetition index lives in the storage key (filename), never in the
   hash.** `fingerprint()` is used exactly as DF-202 shipped it — the scheme does not
   touch it. The cassette store discriminates repetitions by suffixing the key:
   `storage_key(fp, 0) == fp` (byte-identical, so `repeat: 1` and every v0.2 cassette
   stay valid) and `storage_key(fp, i) == f"{fp}#{i}"` for `i ≥ 1`. A `repeat: 5` case
   stores five responses under `fp, fp#1, fp#2, fp#3, fp#4`.

2. **Reporting: `k/N` is always shown; the Wilson 95% interval rides alongside it only
   for a *disagreeing* case (`0 < k < N`).** The tool warns below a recommended
   **N = 5** and never refuses.

The keying decision is the load-bearing one, and its whole point is to prevent the
epic's most-feared failure: if repetitions were keyed by the bare fingerprint, every
one would overwrite the last, replay would serve one response N times, and every pass
rate would read a comforting `N/N` while measuring nothing.
`test_without_the_index_all_repetitions_would_collide` demonstrates the lie;
`test_five_distinct_responses_record_and_replay_in_order` demonstrates the fix.

## Why the index goes in the key, not the hash

Putting `repeat_index` into `hashable_request` forces a bad choice:

- Include it always → `repeat: 1` changes the hash → **every existing cassette is
  invalidated**. Fails the byte-identity requirement outright.
- Include it only when `> 0` → a special-case branch **inside the security-critical
  hasher**, precisely where SPIKE-002 warns that any subtlety risks a false-stable key.

Keeping the hash pure and discriminating repetitions one layer up avoids both. The
decisive property: because `fingerprint()` is literally unmodified, **all 19 SPIKE-002
stability + sensitivity tests pass by construction** — `test_keying.py` re-runs them
against the modified scheme and they are green, and the real suite
(`tests/unit/domain/test_fingerprint.py`, 21 tests) needs no change at all.

## Answers to the required questions

**Q1 — The keying scheme (pseudocode). Where does the index live?**
In the **storage key** (the filename / store lookup key), not the hash input and not
the file body:

```
fp = fingerprint(**hashable_request)          # UNCHANGED from DF-202
key(i) = fp                if i == 0          # repeat:1 and all v0.2 cassettes
         fp + "#" + str(i) if i >= 1          # one slot per repetition
```

The `CachingGateway` for repetition `i` computes `store.get(key(i))` / `store.put(...)`.
`#` cannot appear in a 16-hex fingerprint, so `parse_storage_key` recovers `(fp, i)`
unambiguously — which is how `prune` (DF-205/DF-306) recognises repetition cassettes as
belonging to one logical request.

**Q2 — Does replay preserve response order, and does order matter for the rate?**
Replay *does* preserve order as a side effect (repetition `i` deterministically reads
`key(i)`), but **order does not matter for the pass rate** — `k/N` is a count of passes,
a set cardinality, which is commutative. Order preservation is not the goal; **distinct
per-index responses** are. The requirement the scheme actually enforces is that
repetition `i` replays *its own* recording rather than a shared one, so the N runs stay
genuinely independent. If order were shuffled the rate would be identical; if the
responses collided the rate would be a lie.

**Q3 — Smallest N that means anything (interval widths at observed ~80%).**
95% Wilson intervals (from `stats.py`):

| N  | k  | p̂    | 95% interval   | width |
|----|----|------|----------------|-------|
| 3  | 2  | 0.67 | [0.21, 0.94]   | 0.73  |  ← 3 runs can't even express 0.8
| 3  | 3  | 1.00 | [0.44, 1.00]   | 0.56  |
| 5  | 4  | 0.80 | [0.38, 0.96]   | 0.59  |
| 10 | 8  | 0.80 | [0.49, 0.94]   | 0.45  |
| 20 | 16 | 0.80 | [0.58, 0.92]   | 0.34  |

The honest reading: **N = 3 is not a measurement** (it can't even represent 80%, and
its interval spans two-thirds of the range). N = 5 is the smallest N worth reporting,
and even N = 20 carries ±0.17. **Recommended minimum N = 5, with the interval shown so
nobody mistakes `4/5` for a real 0.8.** Wilson (not the naive normal interval) because
it stays inside [0, 1] and is honest at the boundaries: `5/5 → [0.57, 1.00]`, not
`[1.0, 1.0]`.

**Q4 — Show the interval in the terminal, or is it noise for the merge gate?**
Show `k/N` and the pass/fail-vs-`require_pass_rate` verdict on the main line, always.
Show the **Wilson interval only for a disagreeing case (`0 < k < N`)** — the one place
the uncertainty is decision-relevant. A `5/5` or `0/5` case does not need an interval
cluttering a CI log, but a `3/5` absolutely does, because that is exactly the number a
human is tempted to over-read. This keeps the merge-gate output clean while putting the
honesty where it counts. (DF-305 renders it; the disagreeing case is already the one the
epic says to surface prominently.)

**Q5 — Does `repeat` interact with `compare`?**
`repeat: N` across M models is `M × N` runs. **Allowed, but warned — never silently
multiplied.** The multiplier is surfaced through DF-307's pre-execution cost estimate +
confirmation prompt (the same guard that already protects a bare `compare`), so a user
sees "4 models × 5 repeats × 50 cases = 1000 runs, est. \$X" before spending. This is
the single source of truth for the interaction: **SPIKE-007 says allowed+warned via the
cost prompt; DF-305 and DF-307 both defer here** rather than each inventing a rule.

## Partial cassettes (3 recorded, 5 requested) — policy per mode

Nothing new is needed: with a per-index key, a missing repetition is just a cassette
miss, so the existing DF-204 mode table applies per key
(`test_partial_cassette_policy_per_mode`):

| mode   | repetitions 0–2 (recorded) | repetitions 3–4 (missing) |
|--------|----------------------------|---------------------------|
| off    | live (cassettes bypassed)  | live                      |
| record | live + overwrite           | live + record             |
| auto   | serve from cassette        | **live call + record** (backfill the gaps) |
| replay | serve from cassette        | **cassette miss → error (exit 3)** |

The important row is **replay**: it **refuses to fabricate** the missing repetitions.
You cannot honestly report a 5-run pass rate from 3 recordings, so a partial replay
fails loudly rather than quietly measuring `3/3` and calling it `1.0`. This is exactly
the SPEC §9 hand-wave ("N cassette variants or cassette-mode=off") made precise: replay
needs all N, auto backfills, record re-records, off doesn't care.

## Acceptance criteria

- [x] A repetition-aware key storing N distinct responses per logical request, `repeat: 1` unchanged.
- [x] All 19 SPIKE-002 tests pass against the modified scheme (re-run in `test_keying.py`; the real 21-test suite is untouched because `fingerprint()` is untouched).
- [x] Replaying a `repeat: 5` case reproduces the same 5 responses in order.
- [x] A `repeat: 5` case with 3 cassettes behaves per a documented policy in each of the four modes.
- [x] A Wilson confidence interval for `k/N`, no dependency (`stats.py`).

## Handoff to DF-305 / DF-306

- **DF-306** implements `storage_key`/`parse_storage_key` on the real `FileCassetteStore`
  and threads `repeat_index` into the per-repetition `CachingGateway`. Commit a v0.2
  cassette as a fixture and prove it still replays (index 0 → bare fingerprint). The
  must-have test is `repeat: 5` replay yielding **5 distinct responses**, asserted
  individually — the collision test here shows why.
- **DF-305** runs the N repetitions under the existing scheduler semaphore (not a nested
  pool), reports `k/N` with `require_pass_rate` (default 1.0), warns below N = 5, and
  renders the Wilson interval for disagreeing cases only.
- **`repeat` × `compare`** is allowed+warned via DF-307's cost prompt — do not re-decide
  it in DF-305 or DF-307.

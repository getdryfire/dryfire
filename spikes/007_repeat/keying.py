"""SPIKE-007 reference seam — repetition-aware cassette keying.

The verdict, in one line: **the repetition index lives in the storage key (the
filename layer), never in the hash.** `fingerprint()` is used byte-for-byte as
DF-202 shipped it — this module does not touch it — so every SPIKE-002 stability and
sensitivity property holds by construction, and `repeat: 1` produces a key identical
to v0.2.

Why not put the index in the hash input? Because then either (a) `repeat: 1` changes
the hash (invalidating every existing cassette), or (b) you conditionally omit the
index at 0, which is a special case inside the security-critical hasher — exactly where
you least want one. Keeping the hash pure and discriminating repetitions one layer up
is strictly cleaner and keeps the 19-test SPIKE-002 contract untouched.

    logical request ── fingerprint() ──▶ fp (16 hex, UNCHANGED from v0.2)
    repetition i     ── storage_key ───▶ fp            (i == 0, byte-identical)
                                         fp + "#" + i  (i >= 1, distinct per i)

So a `repeat: 5` case stores five responses under fp, fp#1, fp#2, fp#3, fp#4 — five
distinct recordings, one per repetition — and replay of repetition i reads exactly its
own recording. The failure this prevents is the important one: without the index every
repetition would read fp and replay the SAME response N times, making every pass rate a
comforting N/N lie while looking perfectly healthy.
"""

from __future__ import annotations

from dryfire.domain.fingerprint import fingerprint  # re-used verbatim, NOT modified

__all__ = ["fingerprint", "storage_key"]

REPEAT_SEP = "#"


def storage_key(fp: str, repeat_index: int) -> str:
    """The cassette storage key for repetition `repeat_index` of a logical request
    whose (unchanged) fingerprint is `fp`.

    - `repeat_index == 0` → `fp` verbatim, so a `repeat: 1` case (and every v0.2 case)
      keys byte-for-byte as before and existing cassettes stay valid.
    - `repeat_index >= 1` → `fp#<index>`, a distinct key per repetition.

    The separator `#` cannot occur in `fp` (16 lowercase hex chars), so the mapping is
    unambiguous and reversible."""
    if repeat_index < 0:
        raise ValueError(f"repeat_index must be >= 0, got {repeat_index}")
    return fp if repeat_index == 0 else f"{fp}{REPEAT_SEP}{repeat_index}"


def parse_storage_key(key: str) -> tuple[str, int]:
    """Inverse of `storage_key`: (fingerprint, repeat_index). Lets `prune` (DF-205)
    recognise repetition cassettes as belonging to the same logical request."""
    fp, sep, idx = key.partition(REPEAT_SEP)
    return (fp, int(idx)) if sep else (fp, 0)

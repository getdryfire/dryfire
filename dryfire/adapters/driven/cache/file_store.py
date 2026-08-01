"""File-backed ResponseCache — the cassette store (DF-203, SPIKE-002 §3).

Layout: ``.dryfire/cassettes/<suite>/<case>/<NN>-<fingerprint>.json`` — the turn
index prefix makes the directory read in loop order, the fingerprint makes it
content-addressed, and both together let a reviewer see from a git diff exactly
which case changed at which turn. Reads, however, are keyed by fingerprint alone
(the layout is for humans; correctness never depends on it).

Writes are atomic (serialize fully in memory, temp file + ``os.replace``): these
files get committed to git, so a killed run must never leave a truncated cassette.
The body is stable-key, pretty JSON so a re-record with only a changed response
produces a small diff.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dryfire.application.ports.response_cache import CassetteRecord
from dryfire.domain.fingerprint import SCHEMA_VERSION
from dryfire.domain.model.message import ModelResponse

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_RESERVED = frozenset({"", ".", ".."})


def _sanitise(name: str) -> str:
    """A filesystem-safe directory name that never collapses two distinct names
    into one. Already-safe names pass through verbatim (the common case, keeping
    paths readable); any name that must be rewritten gets a short hash of the
    original appended, so distinct originals stay distinct on disk."""
    safe = _UNSAFE.sub("_", name)
    if safe == name and name not in _RESERVED:
        return name
    suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{safe or '_'}-{suffix}"


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class FileCassetteStore:
    """A ResponseCache persisting cassettes under `root` (`.dryfire/cassettes`)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def get(self, fingerprint: str) -> ModelResponse | None:
        # Keyed by fingerprint alone: the filename ends in `-<fingerprint>.json`,
        # so a path-independent glob finds it wherever the human layout put it.
        for path in sorted(self._root.rglob(f"*-{fingerprint}.json")):
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if body.get("schema_version") != SCHEMA_VERSION:
                continue  # stale format → a miss, never an error
            if body.get("fingerprint") != fingerprint:
                continue  # defensive: filename/content disagree
            return ModelResponse.model_validate(body["response"])
        return None

    def put(self, record: CassetteRecord, *, recorded_at: datetime) -> None:
        directory = self._root / _sanitise(record.suite) / _sanitise(record.case)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{record.turn:02d}-{record.fingerprint}.json"
        payload = self._serialise(record, recorded_at)

        # Fully serialised above, so a failure never touches the target; write to
        # a temp file in the same directory, then atomically rename over it.
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory,
            prefix=f"{target.name}.", suffix=".tmp", delete=False,
        )
        try:
            handle.write(payload)
            handle.flush()
            handle.close()
            os.replace(handle.name, target)
        except BaseException:
            handle.close()
            with contextlib.suppress(OSError):
                os.unlink(handle.name)
            raise

    @staticmethod
    def _serialise(record: CassetteRecord, recorded_at: datetime) -> str:
        body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "fingerprint": record.fingerprint,
            "suite": record.suite,
            "case": record.case,
            "turn": record.turn,
            "provider": record.provider,
            "model": record.model,
            # For humans only — not part of the fingerprint.
            "recorded_at": _iso_z(recorded_at),
            "request_digest": record.request_digest,
            "response": record.response.model_dump(mode="json"),
        }
        return json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)

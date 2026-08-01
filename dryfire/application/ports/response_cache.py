"""The ResponseCache driven port and its record DTO (ARCHITECTURE §2, DF-203).

A cache stores one provider response per request fingerprint (DF-202) and returns
it on a later identical request. **Reads are keyed by fingerprint alone** — any
on-disk layout is a human convenience the port does not expose, and correctness
never depends on it.

The caching *decorator* and its four modes (auto/record/replay/off) live above
this port (DF-204); the store only persists and retrieves. `recorded_at` is
injected by the caller (there is no Clock port until DF-206), mirroring how the
reporters take an injected timestamp.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from dryfire.domain.model.message import ModelResponse


class CassetteRecord(BaseModel):
    """Everything a stored cassette needs. `fingerprint` (DF-202) and
    `request_digest` (the reduced, human-readable request) are computed by the
    caller; the store persists them alongside the raw `response`."""

    model_config = ConfigDict(frozen=True)

    fingerprint: str
    suite: str
    case: str
    turn: int
    provider: str
    model: str
    request_digest: dict[str, Any]
    response: ModelResponse


@runtime_checkable
class ResponseCache(Protocol):
    """Persist and retrieve provider responses by request fingerprint."""

    def get(self, fingerprint: str) -> ModelResponse | None:
        """The stored response for this fingerprint, or None on a miss. A cassette
        whose `schema_version` differs from the current one is a miss, not an error."""
        ...

    def put(self, record: CassetteRecord, *, recorded_at: datetime) -> None:
        """Store `record`. Overwriting an existing fingerprint is last-write-wins."""
        ...

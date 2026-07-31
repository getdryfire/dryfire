"""Provider-neutral tool types (SPEC §3).

Frozen value objects — a tool call is a record of something the model asked for,
not a mutable entity (ARCHITECTURE §4.1).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolDef(BaseModel):
    """A tool offered to the model. `input_schema` is JSON Schema."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """A tool invocation emitted by the model.

    `id` is the provider's call id — OPAQUE; never parsed or regenerated
    (SPIKE-001). When the provider emits unparseable arguments, `arguments` is
    ``{}`` and the raw string is preserved in `malformed_arguments` rather than
    raising (SPEC §3.3).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]
    malformed_arguments: str | None = None


class ToolResult(BaseModel):
    """The result handed back for a tool call. `is_error` is lossy for OpenAI
    (SPIKE-001), but neutral here."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    content: str | dict[str, Any]
    is_error: bool = False

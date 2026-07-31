"""The ModelGateway driven port and its request DTOs (ARCHITECTURE §5.1).

An adapter translates `CompletionRequest` into a vendor payload and the vendor
response back into `ModelResponse`. It holds no loop, retry, or assertion logic
(SPEC §3.1). Pricing is a separate port (PricingCatalog, AC-017), so `cost()`
does not live here.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from agentcheck.domain.model.message import Message, ModelResponse
from agentcheck.domain.model.tooling import ToolDef


class ModelParams(BaseModel):
    """Provider-neutral generation parameters. All optional; defaults are
    resolved from project config at AC-005, not baked in here."""

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop_sequences: list[str] = []


class CompletionRequest(BaseModel):
    """Everything one model call needs, provider-neutral. This is the unit the
    v0.2 cassette fingerprint is computed over."""

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    model: str
    system: str | None
    messages: list[Message]
    tools: list[ToolDef]
    params: ModelParams


@runtime_checkable
class ModelGateway(Protocol):
    """Port to an external model provider. Named Gateway internally to keep the
    port distinct from the user-facing `provider:` name (ARCHITECTURE §3)."""

    name: str

    async def complete(self, request: CompletionRequest) -> ModelResponse: ...

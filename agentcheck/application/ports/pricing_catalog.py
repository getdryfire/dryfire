"""The `PricingCatalog` driven port (ARCHITECTURE §5.1).

Given a `provider:model`, return its `Rates` or None. The bundled table
(`adapters/driven/pricing/bundled.py`) is the v0.1 implementation; a user
`pricing_file` override is another. Matching is exact — a near-miss returns None,
never a fuzzy price (SPEC §3.2).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentcheck.domain.pricing.calculator import Rates


@runtime_checkable
class PricingCatalog(Protocol):
    def rates(self, provider: str, model: str) -> Rates | None: ...

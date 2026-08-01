"""`BundledPricingCatalog` — the shipped pricing table + user override (AC-017).

Loads `dryfire/data/pricing.yaml` (keyed `provider:model`) into domain `Rates`.
A user `pricing_file` **replaces** matching keys and **merges** the rest. Lookup is
exact string match: a near-miss returns None, never a fuzzy price (SPEC §3.2).

`ruamel.yaml` is used only to parse a trivially-structured data file here — this is
not the spec-loading path, so no positioned-error round-trip is needed. Values are
read as strings and converted to `Decimal` to avoid float drift.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from dryfire.domain.pricing.calculator import Rates

_META_KEY = "_meta"


def _load(text: str) -> dict[str, Any]:
    data = YAML(typ="safe").load(text)
    return data if isinstance(data, dict) else {}


def _bundled_text() -> str:
    return files("dryfire").joinpath("data/pricing.yaml").read_text(encoding="utf-8")


def _parse_rates(table: dict[str, Any]) -> dict[str, Rates]:
    rates: dict[str, Rates] = {}
    for key, value in table.items():
        if key == _META_KEY:
            continue
        rates[key] = Rates.model_validate(value)
    return rates


class BundledPricingCatalog:
    """Exact-match `provider:model` → `Rates`, with optional user override."""

    def __init__(self, pricing_file: Path | None = None) -> None:
        bundled = _load(_bundled_text())
        meta = bundled.get(_META_KEY, {})
        self._updated: str | None = meta.get("updated") if isinstance(meta, dict) else None

        rates = _parse_rates(bundled)
        if pricing_file is not None:
            # Override replaces matching keys, merges the rest (SPEC §3.2). The
            # bundled `_meta.updated` still drives --version staleness.
            rates.update(_parse_rates(_load(Path(pricing_file).read_text(encoding="utf-8"))))
        self._rates = rates

    def rates(self, provider: str, model: str) -> Rates | None:
        return self._rates.get(f"{provider}:{model}")

    @property
    def updated(self) -> str | None:
        """The bundled table's `_meta.updated` date — surfaced in --version so a
        user can see how stale the prices are."""
        return self._updated

    def keys(self) -> list[str]:
        """Every `provider:model` key in the resolved table (bundled + override).
        Used by the schema guard and future diagnostics."""
        return list(self._rates)

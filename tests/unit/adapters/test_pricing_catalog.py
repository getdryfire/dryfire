"""AC-017 — the bundled pricing catalog (SPEC §3.2). Exact-match lookup over
`data/pricing.yaml`, with a user `pricing_file` override that replaces matching
keys and merges the rest. A near-miss returns None, never a fuzzy price."""

from decimal import Decimal
from pathlib import Path

from dryfire.adapters.driven.pricing.bundled import BundledPricingCatalog
from dryfire.application.ports.pricing_catalog import PricingCatalog
from dryfire.domain.pricing.calculator import Rates


def _accepts(catalog: PricingCatalog) -> PricingCatalog:
    return catalog  # conformance check: BundledPricingCatalog satisfies the port


def test_known_model_returns_its_rates() -> None:
    catalog = _accepts(BundledPricingCatalog())
    rates = catalog.rates("anthropic", "claude-sonnet-4-6")
    assert rates == Rates(
        input=Decimal("3.00"),
        output=Decimal("15.00"),
        cache_read=Decimal("0.30"),
        cache_write=Decimal("3.75"),
    )


def test_unknown_model_returns_none() -> None:
    assert BundledPricingCatalog().rates("anthropic", "gpt-9") is None


def test_near_miss_is_not_fuzzy_matched() -> None:
    # A typo'd model must not silently price against the closest real one.
    assert BundledPricingCatalog().rates("anthropic", "claude-sonnet-4-6-typo") is None


def test_user_file_overrides_one_entry_and_merges_the_rest(tmp_path: Path) -> None:
    override = tmp_path / "pricing.yaml"
    override.write_text(
        '"anthropic:claude-sonnet-4-6":\n'
        '  input: "9.99"\n'
        '  output: "19.99"\n'
        '  cache_read: "0.99"\n'
        '  cache_write: "1.99"\n'
    )
    catalog = BundledPricingCatalog(pricing_file=override)

    # Overridden entry uses the user's numbers…
    assert catalog.rates("anthropic", "claude-sonnet-4-6") == Rates(
        input=Decimal("9.99"),
        output=Decimal("19.99"),
        cache_read=Decimal("0.99"),
        cache_write=Decimal("1.99"),
    )
    # …while a bundled entry the file didn't mention is left intact.
    assert catalog.rates("anthropic", "claude-haiku-4-5") == Rates(
        input=Decimal("1.00"),
        output=Decimal("5.00"),
        cache_read=Decimal("0.10"),
        cache_write=Decimal("1.25"),
    )


def test_updated_date_is_exposed_for_version_output() -> None:
    # AC-017: --version surfaces how stale the bundled prices are.
    assert BundledPricingCatalog().updated == "2026-07-31"


def test_bundled_file_has_all_four_keys_for_every_entry() -> None:
    # Schema guard over the shipped file: no half-specified rate slips through.
    catalog = BundledPricingCatalog()
    assert catalog.keys()  # non-empty
    for key in catalog.keys():
        provider, _, model = key.partition(":")
        rates = catalog.rates(provider, model)
        assert rates is not None
        assert rates.input > 0 and rates.output > 0
        assert rates.cache_read is not None and rates.cache_write is not None

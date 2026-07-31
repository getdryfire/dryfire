"""AC-017 — cost calculation (SPEC §3.2). Pure domain math: Usage + Rates ->
Decimal | None. Decimal throughout so a long run's summed cost never drifts."""

from decimal import Decimal

from agentcheck.domain.model.message import Usage
from agentcheck.domain.pricing.calculator import Cost, Rates, calculate


def _usage(**over: int) -> Usage:
    base = dict(input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0)
    base.update(over)
    return Usage(**base)


def test_known_usage_returns_hand_computed_value() -> None:
    # (1000 * 3 + 500 * 15) / 1e6 = 10500 / 1_000_000 = 0.0105
    rates = Rates(input=Decimal("3"), output=Decimal("15"))
    cost = calculate(_usage(input_tokens=1000, output_tokens=500), rates)
    assert cost == Cost(total=Decimal("0.0105"), cache_priced_as_input=False)


def test_unpriced_model_returns_none_without_raising() -> None:
    assert calculate(_usage(input_tokens=1000), None) is None


def test_cache_tokens_priced_separately_when_defined() -> None:
    rates = Rates(
        input=Decimal("3"),
        output=Decimal("15"),
        cache_read=Decimal("0.30"),
        cache_write=Decimal("3.75"),
    )
    usage = _usage(
        input_tokens=1000, output_tokens=500, cache_read_tokens=2000, cache_write_tokens=400
    )
    cost = calculate(usage, rates)
    # (1000*3 + 500*15 + 2000*0.30 + 400*3.75) / 1e6 = (3000+7500+600+1500)/1e6
    assert cost is not None
    assert cost.total == Decimal("0.0126")
    assert cost.cache_priced_as_input is False


def test_missing_cache_pricing_falls_back_to_input_and_records_it() -> None:
    rates = Rates(input=Decimal("3"), output=Decimal("15"))  # no cache rates
    cost = calculate(_usage(input_tokens=1000, cache_read_tokens=2000), rates)
    # cache reads charged at the input rate: (1000*3 + 2000*3) / 1e6 = 0.009
    assert cost is not None
    assert cost.total == Decimal("0.009")
    assert cost.cache_priced_as_input is True


def test_summing_a_thousand_costs_does_not_drift() -> None:
    rates = Rates(input=Decimal("0.30"), output=Decimal("0.60"))
    one = calculate(_usage(input_tokens=1, output_tokens=1), rates)
    assert one is not None
    total = sum((one.total for _ in range(1000)), Decimal(0))
    # 1000 * (0.30 + 0.60) / 1e6 = 900 / 1e6 = 0.0009 — exact, no float dust.
    assert total == Decimal("0.0009")

"""Cost calculation (SPEC §3.2) — pure domain math, no I/O.

Cost is **advisory**: an unknown model yields `None` (the catalog's job), never a
guess. Here we only turn a `Usage` and its `Rates` into a `Cost`. `Decimal`
throughout so summing thousands of case costs over a run never drifts; callers
convert to `float` only at the display boundary.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from dryfire.domain.model.message import Usage

_PER_MILLION = Decimal(1_000_000)


class Rates(BaseModel):
    """USD per million tokens for one `provider:model`. Cache rates are optional:
    a model without them prices cache reads at the input rate (recorded on the
    `Cost`), rather than guessing or dropping the tokens."""

    model_config = ConfigDict(frozen=True)

    input: Decimal
    output: Decimal
    cache_read: Decimal | None = None
    cache_write: Decimal | None = None


class Cost(BaseModel):
    """A computed cost. `cache_priced_as_input` is True when cache tokens were
    charged at the input rate because the model defined no cache pricing — honest
    about the approximation rather than hiding it."""

    model_config = ConfigDict(frozen=True)

    total: Decimal
    cache_priced_as_input: bool = False


def calculate(usage: Usage, rates: Rates | None) -> Cost | None:
    """Cost of one `Usage` at `rates`, or None when the model is unpriced."""
    if rates is None:
        return None

    priced_as_input = False
    read_rate = rates.cache_read
    if read_rate is None:
        read_rate = rates.input
        priced_as_input = priced_as_input or usage.cache_read_tokens > 0
    write_rate = rates.cache_write
    if write_rate is None:
        write_rate = rates.input
        priced_as_input = priced_as_input or usage.cache_write_tokens > 0

    total = (
        usage.input_tokens * rates.input
        + usage.output_tokens * rates.output
        + usage.cache_read_tokens * read_rate
        + usage.cache_write_tokens * write_rate
    ) / _PER_MILLION
    return Cost(total=total, cache_priced_as_input=priced_as_input)

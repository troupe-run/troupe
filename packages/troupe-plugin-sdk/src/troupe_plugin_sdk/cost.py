"""A run's cost estimated from troupe's price (spec: runner-protocol, "An estimated cost is worked
out from troupe's price, and marked as one" and "An estimate covers every token the run used, or is
absent"; spec: plugin-sdk; estimated-cost design D7, D8).

A runner whose engine reports no cost may send ``estimatedCostUsd``, but only from the price
troupe gave in ``run/start``'s ``runtime.price``, never a price of its own. ``estimate`` does the
arithmetic and applies the contract's rule, so every runner leaves the estimate out in the same
cases: an estimate prices every token the run used, or there is none.
"""

from troupe_plugin_sdk.runner import Price, Usage

TOKENS_PER_RATE = 1_000_000
"""A price's rates are US dollars per million tokens."""
DECIMAL_PLACES = 10
"""Estimates are rounded to ten decimal places: far below a cent, and clear of float noise."""


def estimate(usage: Usage | None, price: Price | None) -> float | None:
    """The run's ``usage`` at ``price``, in US dollars, or None when the contract says an estimate
    is absent: no usage or no price, no ``inputTokens`` or ``outputTokens``, a rate for a cache
    counter that wasn't reported, or a cache counter holding tokens the price has no rate for.
    One kind of token is never priced at another kind's rate."""
    if usage is None or price is None:
        return None
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    total = usage.input_tokens * price.input + usage.output_tokens * price.output
    for tokens, rate in (
        (usage.cache_read_tokens, price.cache_read),
        (usage.cache_write_tokens, price.cache_write),
    ):
        if rate is not None:
            if tokens is None:
                return None  # the price covers tokens the engine didn't count
            total += tokens * rate
        elif tokens:
            return None  # tokens the price has no rate for
    return round(total / TOKENS_PER_RATE, DECIMAL_PLACES)

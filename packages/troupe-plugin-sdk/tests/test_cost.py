"""The SDK's cost estimator (spec: plugin-sdk, "The SDK estimates a cost from usage and a price";
spec: runner-protocol, "An estimate covers every token the run used, or is absent")."""

from hypothesis import given
from hypothesis import strategies as st

from troupe_plugin_sdk.cost import estimate
from troupe_plugin_sdk.runner import Price, Usage

FULL = Price(input=2, output=8, cache_read=0.5, cache_write=2.5)


def test_every_counter_priced_gives_the_sum_of_each_counter_at_its_rate() -> None:
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_read_tokens=200_000,
        cache_write_tokens=100_000,
    )
    assert estimate(usage, FULL) == 6.35


def test_input_and_output_alone_with_a_price_of_only_those() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=500_000)
    assert estimate(usage, Price(input=2, output=8)) == 6


def test_no_usage_gives_no_estimate() -> None:
    assert estimate(None, FULL) is None


def test_no_price_gives_no_estimate() -> None:
    assert estimate(Usage(input_tokens=1, output_tokens=1), None) is None


def test_no_input_or_output_tokens_gives_no_estimate() -> None:
    assert estimate(Usage(output_tokens=10), FULL) is None
    assert estimate(Usage(input_tokens=10), FULL) is None


def test_cache_reads_with_no_cache_read_rate_give_no_estimate() -> None:
    usage = Usage(input_tokens=10, output_tokens=10, cache_read_tokens=100)
    assert estimate(usage, Price(input=2, output=8)) is None


def test_a_rate_for_a_counter_the_engine_didnt_report_gives_no_estimate() -> None:
    usage = Usage(input_tokens=10, output_tokens=10, cache_read_tokens=0)
    assert estimate(usage, Price(input=2, output=8, cache_read=0.5, cache_write=2.5)) is None


def test_a_counter_at_zero_with_no_rate_doesnt_block_the_estimate() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=0, cache_write_tokens=0)
    assert estimate(usage, Price(input=2, output=8)) == 2


def test_the_openai_runners_example_is_0_00078() -> None:
    usage = Usage(input_tokens=260, output_tokens=30, cache_read_tokens=40)
    assert estimate(usage, Price(input=2, output=8, cache_read=0.5)) == 0.00078


def test_an_estimate_with_more_than_ten_decimal_places_is_rounded_to_ten() -> None:
    # 1 token at 0.123456789123 per million is 1.23456789123e-07 before rounding.
    usage = Usage(input_tokens=1, output_tokens=0)
    assert estimate(usage, Price(input=0.123456789123, output=0)) == 1.235e-07


def test_float_noise_in_the_sum_is_rounded_away() -> None:
    # 3 x 0.1 + 7 x 0.2 per million is 1.7000000000000002e-06 in floating point.
    usage = Usage(input_tokens=3, output_tokens=7)
    assert estimate(usage, Price(input=0.1, output=0.2)) == 1.7e-06


COUNT = st.none() | st.integers(0, 10**9)
RATE = st.none() | st.floats(0, 100, allow_nan=False)


def _absent(usage: Usage, price: Price) -> bool:
    """The contract's rule, stated apart from the estimator: an estimate is absent exactly when
    input or output tokens are unknown, or a cache counter and its rate don't line up."""
    if usage.input_tokens is None or usage.output_tokens is None:
        return True
    pairs = (
        (usage.cache_read_tokens, price.cache_read),
        (usage.cache_write_tokens, price.cache_write),
    )
    unreported = any(rate is not None and tokens is None for tokens, rate in pairs)
    unpriced = any(rate is None and tokens not in (None, 0) for tokens, rate in pairs)
    return unreported or unpriced


@given(
    st.builds(
        Usage,
        input_tokens=COUNT,
        output_tokens=COUNT,
        cache_read_tokens=COUNT,
        cache_write_tokens=COUNT,
    ),
    st.builds(
        Price,
        input=st.floats(0, 100, allow_nan=False),
        output=st.floats(0, 100, allow_nan=False),
        cache_read=RATE,
        cache_write=RATE,
    ),
)
def test_agrees_with_the_contract_on_every_input(usage: Usage, price: Price) -> None:
    found = estimate(usage, price)
    if _absent(usage, price):
        assert found is None
        return
    assert usage.input_tokens is not None
    assert usage.output_tokens is not None
    expected = usage.input_tokens * price.input + usage.output_tokens * price.output
    expected += (usage.cache_read_tokens or 0) * (price.cache_read or 0)
    expected += (usage.cache_write_tokens or 0) * (price.cache_write or 0)
    assert found is not None
    assert found >= 0
    assert abs(found - expected / 1_000_000) <= 1e-10 + abs(expected) * 1e-15

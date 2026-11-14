"""The runner's options are closed, and each request asks for the run's output limit (spec:
anthropic-runner, "The runner's options are closed", "Each request asks for the run's output limit",
"Every run has a turn limit and a token budget"; design D5).

The defaults are checked here, by parsing empty options, and never by running a service on them:
tests run on TEST_LIMITS. That each request's max_tokens is the parsed value is the loop's to show;
this file checks the value the loop is given."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from anthropic_harness import TEST_LIMITS, own_validator
from troupe_runner_anthropic.defaults import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MAX_TOTAL_TOKENS,
    DEFAULT_MAX_TURNS,
)
from troupe_runner_anthropic.options import Options, OptionsError, parse_options

OPTIONS = ("maxTurns", "maxTotalTokens", "maxOutputTokens", "contextWindow")


# Requirement: Every run has a turn limit and a token budget; Each request asks for the run's
# output limit, "No output limit in the options"


def test_empty_options_give_the_runners_named_defaults_and_no_context_window() -> None:
    assert parse_options({}) == Options(
        max_turns=DEFAULT_MAX_TURNS,
        max_total_tokens=DEFAULT_MAX_TOTAL_TOKENS,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        context_window=None,
    )
    assert (DEFAULT_MAX_TURNS, DEFAULT_MAX_TOTAL_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS) == (
        50,
        1_000_000,
        16_000,
    )


def test_the_test_limits_are_read_as_given() -> None:
    assert parse_options(TEST_LIMITS) == Options(max_turns=5, max_total_tokens=20_000)


# Requirement: Each request asks for the run's output limit, "An output limit in the options"


def test_max_output_tokens_is_read_as_the_output_limit() -> None:
    assert parse_options({"maxOutputTokens": 2048}).max_output_tokens == 2048


def test_context_window_is_read_when_set() -> None:
    assert parse_options({"contextWindow": 8192}).context_window == 8192


def test_every_option_set_at_once_is_read_into_its_own_field() -> None:
    assert parse_options(
        {"maxTurns": 3, "maxTotalTokens": 1000, "maxOutputTokens": 2048, "contextWindow": 8192}
    ) == Options(3, 1000, 2048, 8192)


# Requirement: The runner's options are closed, "An unknown option"; The service comes from the
# run's runtime, "An endpoint in the options"


@pytest.mark.parametrize(
    "key", ["troupeConformanceUnknownOption", "endpoint", "model", "credential", "max_tokens"]
)
def test_an_unknown_option_is_refused_naming_it_and_the_runtime(key: str) -> None:
    with pytest.raises(OptionsError) as raised:
        parse_options({key: "x"})
    assert raised.value.code == "anthropic.unknown-option"
    assert raised.value.where == f"options.{key}"
    assert "runtime" in raised.value.fix


# Requirement: The runner's options are closed, "A malformed value"


@pytest.mark.parametrize(
    ("options", "where"),
    [
        ({"maxOutputTokens": 0}, "options.maxOutputTokens"),
        ({"contextWindow": "big"}, "options.contextWindow"),
        ({"maxTurns": 0}, "options.maxTurns"),
        ({"maxTurns": True}, "options.maxTurns"),
        ({"maxTurns": 2.5}, "options.maxTurns"),
        ({"maxTotalTokens": "lots"}, "options.maxTotalTokens"),
        ({"maxTotalTokens": -1}, "options.maxTotalTokens"),
        ({"contextWindow": None}, "options.contextWindow"),
    ],
    ids=repr,
)
def test_a_malformed_value_is_refused_naming_the_option_and_what_is_valid(
    options: dict[str, Any], where: str
) -> None:
    with pytest.raises(OptionsError) as raised:
        parse_options(options)
    assert raised.value.code == "anthropic.invalid-options"
    assert raised.value.where == where
    assert "1 or more" in raised.value.fix


def test_a_whole_number_written_as_a_float_is_read_as_the_integer_the_schema_accepts() -> None:
    assert parse_options({"maxOutputTokens": 3.0}).max_output_tokens == 3
    assert own_validator("options.schema.json").is_valid({"maxOutputTokens": 3.0})


@pytest.mark.parametrize("value", [[], None, "{}", 1], ids=repr)
def test_options_that_arent_an_object_are_refused(value: object) -> None:
    with pytest.raises(OptionsError) as raised:
        parse_options(value)
    assert raised.value.code == "anthropic.invalid-options"
    assert raised.value.where == "options"


_values = st.one_of(
    st.integers(min_value=-3, max_value=10**7),
    st.booleans(),
    st.floats(allow_nan=False),
    st.text(max_size=5),
    st.none(),
    st.lists(st.integers(), max_size=2),
)


@given(
    st.dictionaries(st.sampled_from([*OPTIONS, "endpoint", "x"]), _values, max_size=4)
    | st.one_of(st.none(), st.integers(), st.text(max_size=3), st.lists(st.integers(), max_size=2))
)
def test_the_code_and_the_published_schema_agree_on_every_options_value(options: object) -> None:
    try:
        parse_options(options)
        accepted = True
    except OptionsError:
        accepted = False
    assert accepted == own_validator("options.schema.json").is_valid(options)

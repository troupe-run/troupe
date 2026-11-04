"""The runner's options are closed, and every run has a turn limit and a token budget (spec:
openai-chat-runner, "The runner's options are closed", "Every run has a turn limit and a token
budget"; design D7).

The defaults are checked here, by parsing empty options, and never by running a service on them:
tests run on TEST_LIMITS (design D7)."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chat_harness import TEST_LIMITS, own_validator
from troupe_runner_openai_chat.defaults import DEFAULT_MAX_TOTAL_TOKENS, DEFAULT_MAX_TURNS
from troupe_runner_openai_chat.options import Options, OptionsError, parse_options


def test_empty_options_give_the_runners_named_defaults() -> None:
    assert parse_options({}) == Options(DEFAULT_MAX_TURNS, DEFAULT_MAX_TOTAL_TOKENS)
    assert (DEFAULT_MAX_TURNS, DEFAULT_MAX_TOTAL_TOKENS) == (50, 1_000_000)


def test_the_test_limits_are_read_as_given() -> None:
    assert parse_options(TEST_LIMITS) == Options(max_turns=5, max_total_tokens=20_000)


@pytest.mark.parametrize("key", ["troupeConformanceUnknownOption", "endpoint", "model"])
def test_an_unknown_option_is_refused_naming_it(key: str) -> None:
    with pytest.raises(OptionsError) as raised:
        parse_options({key: "x"})
    assert raised.value.code == "openai-chat.unknown-option"
    assert raised.value.where == f"options.{key}"
    assert "runtime" in raised.value.fix


@pytest.mark.parametrize(
    ("options", "where"),
    [
        ({"maxTurns": 0}, "options.maxTurns"),
        ({"maxTurns": True}, "options.maxTurns"),
        ({"maxTurns": 2.5}, "options.maxTurns"),
        ({"maxTotalTokens": "lots"}, "options.maxTotalTokens"),
    ],
    ids=repr,
)
def test_a_malformed_value_is_refused_naming_the_option_and_what_is_valid(
    options: dict[str, Any], where: str
) -> None:
    with pytest.raises(OptionsError) as raised:
        parse_options(options)
    assert raised.value.code == "openai-chat.invalid-options"
    assert raised.value.where == where
    assert "1 or more" in raised.value.fix


def test_a_whole_number_written_as_a_float_is_read_as_the_integer_the_schema_accepts() -> None:
    assert parse_options({"maxTurns": 3.0}) == Options(3, DEFAULT_MAX_TOTAL_TOKENS)
    assert own_validator("options.schema.json").is_valid({"maxTurns": 3.0})


def test_options_that_arent_an_object_are_refused() -> None:
    with pytest.raises(OptionsError) as raised:
        parse_options([])
    assert raised.value.code == "openai-chat.invalid-options"


_values = st.one_of(
    st.integers(min_value=-3, max_value=10**7),
    st.booleans(),
    st.floats(allow_nan=False),
    st.text(max_size=5),
    st.none(),
)


@given(
    st.dictionaries(
        st.sampled_from(["maxTurns", "maxTotalTokens", "endpoint", "x"]), _values, max_size=3
    )
)
def test_the_code_and_the_published_schema_agree_on_every_options_object(
    options: dict[str, Any],
) -> None:
    try:
        parse_options(options)
        accepted = True
    except OptionsError:
        accepted = False
    assert accepted == own_validator("options.schema.json").is_valid(options)

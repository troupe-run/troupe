"""The runner's options are closed, and its parser agrees with its published schema (spec:
lm-studio-runner, "The runner's options are closed", "The runner publishes its schemas")."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lm_studio_harness import own_validator
from troupe_runner_lm_studio.defaults import (
    DEFAULT_CONTEXT_LENGTH,
    DEFAULT_MAX_TOTAL_TOKENS,
    DEFAULT_MAX_TURNS,
)
from troupe_runner_lm_studio.options import Options, OptionsError, parse_options


def test_no_options_are_the_runners_named_defaults_with_no_temperature() -> None:
    assert parse_options({}) == Options(
        DEFAULT_MAX_TURNS, DEFAULT_MAX_TOTAL_TOKENS, DEFAULT_CONTEXT_LENGTH, None
    )


def test_each_option_is_read() -> None:
    options = parse_options(
        {"maxTurns": 3, "maxTotalTokens": 900, "contextLength": 4096, "temperature": 0.2}
    )
    assert options == Options(3, 900, 4096, 0.2)


@pytest.mark.parametrize("key", ["troupeConformanceUnknownOption", "endpoint", "model"])
def test_an_option_the_runner_doesnt_define_is_unknown_naming_it(key: str) -> None:
    with pytest.raises(OptionsError) as caught:
        parse_options({key: "x"})
    assert caught.value.code == "lm-studio.unknown-option"
    assert caught.value.where == f"options.{key}"


@pytest.mark.parametrize(
    ("options", "where"),
    [
        ({"maxTurns": 0}, "options.maxTurns"),
        ({"maxTurns": True}, "options.maxTurns"),
        ({"maxTotalTokens": "lots"}, "options.maxTotalTokens"),
        ({"contextLength": 1.5}, "options.contextLength"),
        ({"temperature": 1.5}, "options.temperature"),
        ({"temperature": -0.1}, "options.temperature"),
        ({"temperature": "warm"}, "options.temperature"),
    ],
)
def test_a_malformed_value_is_invalid_naming_the_option_and_whats_valid(
    options: dict[str, Any], where: str
) -> None:
    with pytest.raises(OptionsError) as caught:
        parse_options(options)
    assert caught.value.code == "lm-studio.invalid-options"
    assert caught.value.where == where
    assert caught.value.fix


VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-3, max_value=10**7),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-2, max_value=2),
    st.floats(min_value=0, max_value=5).map(float.__floor__).map(float),
    st.text(max_size=3),
)
KEYS = st.sampled_from(["maxTurns", "maxTotalTokens", "contextLength", "temperature", "other"])


@given(st.dictionaries(KEYS, VALUES, max_size=4))
def test_the_parser_and_the_published_schema_accept_and_refuse_the_same_options(
    options: dict[str, Any],
) -> None:
    try:
        parse_options(options)
        parsed = True
    except OptionsError:
        parsed = False
    assert own_validator("options.schema.json").is_valid(options) == parsed

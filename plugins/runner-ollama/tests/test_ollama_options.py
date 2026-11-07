"""The Ollama runner's options: closed, checked, and in agreement with the published schema (spec:
ollama-runner, "The runner's options are closed", "The service comes from the run's runtime",
"The runner publishes its schemas"; local-model-runner design D10, D11; ollama-uses-runtime D2)."""

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ollama_harness import own_validator
from troupe_runner_ollama.defaults import MAX_TURNS
from troupe_runner_ollama.options import Options, OptionsError, parse_options

SCHEMA = own_validator("options.schema.json")


def _refused(options: object) -> OptionsError:
    with pytest.raises(OptionsError) as caught:
        parse_options(options)
    return caught.value


# Requirement: The runner's options are closed


def test_no_options_take_every_default() -> None:
    assert parse_options({}) == Options()
    assert parse_options({}).max_turns == MAX_TURNS


def test_every_option_is_read() -> None:
    options = parse_options(
        {
            "maxTurns": 3.0,
            "contextLength": 32768,
            "temperature": 0,
            "seed": -5,
            "think": "medium",
        }
    )
    assert options == Options(
        max_turns=3,
        context_length=32768,
        temperature=0.0,
        seed=-5,
        think="medium",
    )


def test_an_unknown_option_is_refused_naming_it() -> None:
    error = _refused({"troupeConformanceUnknownOption": True})
    assert error.code == "ollama.unknown-option"
    assert error.where == "options.troupeConformanceUnknownOption"


@pytest.mark.parametrize(
    ("key", "value"), [("model", "qwen3:4b"), ("endpoint", "http://127.0.0.1:11434")]
)
def test_an_endpoint_or_model_in_the_options_is_refused_as_unknown(key: str, value: str) -> None:
    # They're the run's runtime's now (spec: "An endpoint or model in the options").
    error = _refused({key: value})
    assert error.code == "ollama.unknown-option"
    assert error.where == f"options.{key}"
    assert not SCHEMA.is_valid({key: value})


@pytest.mark.parametrize(
    ("options", "where", "valid"),
    [
        ({"maxTurns": 0}, "options.maxTurns", "1 to 1000"),
        ({"maxTurns": 1001}, "options.maxTurns", "1 to 1000"),
        ({"maxTurns": 2.5}, "options.maxTurns", "1 to 1000"),
        ({"maxTurns": True}, "options.maxTurns", "1 to 1000"),
        ({"contextLength": 0}, "options.contextLength", "tokens"),
        ({"temperature": -0.1}, "options.temperature", "0 or more"),
        ({"temperature": "hot"}, "options.temperature", "0 or more"),
        ({"seed": 1.5}, "options.seed", "whole number"),
        ({"think": "maximum"}, "options.think", "low, medium, high"),
        ({"think": None}, "options.think", "low, medium, high"),
    ],
)
def test_a_malformed_value_is_refused_naming_the_option_with_a_fix_saying_whats_valid(
    options: dict[str, Any], where: str, valid: str
) -> None:
    error = _refused(options)
    assert error.code == "ollama.invalid-options"
    assert error.where == where
    assert valid in error.fix
    assert not SCHEMA.is_valid(options)


@pytest.mark.parametrize("turns", [1, 1000])
def test_max_turns_takes_each_bound(turns: int) -> None:
    assert parse_options({"maxTurns": turns}).max_turns == turns


@pytest.mark.parametrize("think", [True, False, "low", "medium", "high"])
def test_think_takes_a_boolean_or_a_level(think: bool | str) -> None:
    assert parse_options({"think": think}).think == think


# Requirement: The runner publishes its schemas (the parser and the schema agree)


def _accepted(options: object) -> bool:
    try:
        parse_options(options)
    except OptionsError:
        return False
    return True


_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=8,
)
_CONTROL = st.sampled_from(["\x00", "\n", "\t", "\x1f", "\x7f"])
_TEXT = (
    st.text(max_size=12)
    | st.builds(lambda a, c, b: a + c + b, st.text(max_size=6), _CONTROL, st.text(max_size=6))
    | st.sampled_from(["", "qwen3:4b", "a\n", "llama3.2"])
)
_NUMBERS = (
    st.floats(allow_nan=False, allow_infinity=False)
    | st.integers()
    | st.booleans()
    | st.sampled_from([0, 0.0, -0.0, 1, 1.0, 1000, 1000.0, 1001, 2.5, -1, 1e300])
)
_HOSTS = st.sampled_from(["127.0.0.1", "localhost", "[::1]", "gpu-box.local", "", "a b", "h@x"])
_ENDPOINTS = (
    st.builds(
        lambda scheme, host, port, tail: f"{scheme}{host}{port}{tail}",
        st.sampled_from(["http://", "https://", "ftp://", "", "http:/"]),
        _HOSTS,
        st.sampled_from(["", ":11434", ":1", ":123456", ":", ":x"]),
        st.sampled_from(["", "/", "//", "/api", "?q", "#f", "\n", " "]),
    )
    | _TEXT
)
_VALUES: dict[str, st.SearchStrategy[object]] = {
    "model": _TEXT | _JSON,
    "endpoint": _ENDPOINTS | _JSON,
    "maxTurns": _NUMBERS | _JSON,
    "contextLength": _NUMBERS | _JSON,
    "temperature": _NUMBERS | _JSON,
    "seed": _NUMBERS | _JSON,
    "think": st.sampled_from([True, False, "low", "medium", "high", "max", "", None]) | _JSON,
}


@pytest.mark.parametrize("key", sorted(_VALUES))
@given(data=st.data())
def test_the_code_and_the_published_schema_agree_on_each_options_values(
    key: str, data: st.DataObject
) -> None:
    options = {key: data.draw(_VALUES[key])}
    assert _accepted(options) == SCHEMA.is_valid(options), json.dumps(options, default=str)


@given(st.fixed_dictionaries({}, optional={**_VALUES, "speed": _JSON}) | _JSON)
def test_the_code_and_the_published_schema_accept_exactly_the_same_options(
    options: object,
) -> None:
    assert _accepted(options) == SCHEMA.is_valid(options)

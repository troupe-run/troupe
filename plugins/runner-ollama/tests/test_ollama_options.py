"""The Ollama runner's options: closed, checked, and in agreement with the published schema (spec:
ollama-runner, "The runner's options are closed", "The endpoint is an option with a named default",
"The runner publishes its schemas"; local-model-runner design D10, D11)."""

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ollama_harness import own_validator
from troupe_runner_ollama.defaults import DEFAULT_ENDPOINT, MAX_TURNS
from troupe_runner_ollama.options import Options, OptionsError, parse_options

SCHEMA = own_validator("options.schema.json")


def _refused(options: object) -> OptionsError:
    with pytest.raises(OptionsError) as caught:
        parse_options(options)
    return caught.value


# Requirement: The runner's options are closed


def test_the_model_alone_takes_every_default() -> None:
    assert parse_options({"model": "qwen3:4b"}) == Options(model="qwen3:4b")
    assert parse_options({"model": "qwen3:4b"}).endpoint == DEFAULT_ENDPOINT
    assert parse_options({"model": "qwen3:4b"}).max_turns == MAX_TURNS


def test_every_option_is_read() -> None:
    options = parse_options(
        {
            "model": "qwen3:4b",
            "endpoint": "https://gpu-box.local:8443/",
            "maxTurns": 3.0,
            "contextLength": 32768,
            "temperature": 0,
            "seed": -5,
            "think": "medium",
        }
    )
    assert options == Options(
        model="qwen3:4b",
        endpoint="https://gpu-box.local:8443",
        max_turns=3,
        context_length=32768,
        temperature=0.0,
        seed=-5,
        think="medium",
    )


def test_an_unknown_option_is_refused_naming_it() -> None:
    error = _refused({"model": "m", "troupeConformanceUnknownOption": True})
    assert error.code == "ollama.unknown-option"
    assert error.where == "options.troupeConformanceUnknownOption"


def test_options_without_a_model_are_refused_naming_model() -> None:
    error = _refused({})
    assert error.code == "ollama.invalid-options"
    assert error.where == "options.model"


@pytest.mark.parametrize(
    ("options", "where", "valid"),
    [
        ({"model": ""}, "options.model", "qwen3:4b"),
        ({"model": "qwen\n3"}, "options.model", "control"),
        ({"model": 3}, "options.model", "qwen3:4b"),
        ({"model": "m", "maxTurns": 0}, "options.maxTurns", "1 to 1000"),
        ({"model": "m", "maxTurns": 1001}, "options.maxTurns", "1 to 1000"),
        ({"model": "m", "maxTurns": 2.5}, "options.maxTurns", "1 to 1000"),
        ({"model": "m", "maxTurns": True}, "options.maxTurns", "1 to 1000"),
        ({"model": "m", "contextLength": 0}, "options.contextLength", "tokens"),
        ({"model": "m", "temperature": -0.1}, "options.temperature", "0 or more"),
        ({"model": "m", "temperature": "hot"}, "options.temperature", "0 or more"),
        ({"model": "m", "seed": 1.5}, "options.seed", "whole number"),
        ({"model": "m", "think": "maximum"}, "options.think", "low, medium, high"),
        ({"model": "m", "think": None}, "options.think", "low, medium, high"),
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
    assert parse_options({"model": "m", "maxTurns": turns}).max_turns == turns


@pytest.mark.parametrize("think", [True, False, "low", "medium", "high"])
def test_think_takes_a_boolean_or_a_level(think: bool | str) -> None:
    assert parse_options({"model": "m", "think": think}).think == think


# Requirement: The endpoint is an option with a named default


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434/",
        "http://[::1]:11434",
        "https://gpu-box.local",
        "http://gpu-box.local:11434",
        "http://127.0.0.1:65535",
        "http://" + "a" * 63 + ".example",
    ],
)
def test_an_http_or_https_endpoint_with_a_host_is_accepted(endpoint: str) -> None:
    options = {"model": "m", "endpoint": endpoint}
    assert parse_options(options).endpoint == endpoint.rstrip("/")
    assert SCHEMA.is_valid(options)


@pytest.mark.parametrize(
    ("endpoint", "problem"),
    [
        ("ftp://127.0.0.1:11434", "isn't an http or https URL"),
        ("127.0.0.1:11434", "isn't an http or https URL"),
        ("http://127.0.0.1:11434/api", "has a path"),
        ("http://127.0.0.1:11434//", "has a path"),
        ("http://127.0.0.1:11434?x=1", "query or a fragment"),
        ("http://127.0.0.1:11434#top", "query or a fragment"),
        ("http://", "isn't an http or https URL"),
        ("http://127.0.0.1:11434\n", "control character"),
        ("http://user:secret@127.0.0.1:11434", "user name or password"),
        ("http://127.0.0.1:99999", "a port is at most 65535"),
        ("http://127.0.0.1:65536", "a port is at most 65535"),
        ("http://a..b:11434", "1 to 63"),
        ("http://" + "a" * 64 + ".com", "1 to 63"),
        ("http://host.:11434", "1 to 63"),
        ("http://token@127.0.0.1:11434", "user name or password"),
    ],
)
def test_an_endpoint_that_isnt_a_host_and_port_is_refused(endpoint: str, problem: str) -> None:
    options = {"model": "m", "endpoint": endpoint}
    error = _refused(options)
    assert error.code == "ollama.invalid-options"
    assert error.where == "options.endpoint"
    assert problem in error.problem
    assert not SCHEMA.is_valid(options)


def test_an_endpoints_password_is_never_repeated_in_the_refusal() -> None:
    error = _refused({"model": "m", "endpoint": "http://user:secret@127.0.0.1:11434"})
    assert "secret" not in f"{error} {error.problem} {error.fix} {error.where}"


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
    options = {"model": "qwen3:4b", key: data.draw(_VALUES[key])}
    assert _accepted(options) == SCHEMA.is_valid(options), json.dumps(options, default=str)


@given(st.fixed_dictionaries({}, optional={**_VALUES, "speed": _JSON}) | _JSON)
def test_the_code_and_the_published_schema_accept_exactly_the_same_options(
    options: object,
) -> None:
    assert _accepted(options) == SCHEMA.is_valid(options)

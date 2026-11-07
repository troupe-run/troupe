"""Resolving a runtime, and what a run on one starts with (spec: runtimes; runtimes design D3,
D7)."""

import json
import re
from typing import Any

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from protocol_schemas import PROTOCOL_BASE, validator_for
from troupe.core import defaults, runtimes
from troupe.core.errors import TroupeError
from troupe.core.runtimes import Sourced, for_run, resolve
from troupe_runner_ollama import runtime as ollama_runtime

KEY = "sk-test-0123456789abcdef"
NO_CONFIG: dict[str, Any] = {}


def _config(**runtimes_: dict[str, Any]) -> dict[str, Any]:
    return {"runtimes": runtimes_}


def _error(raised: pytest.ExceptionInfo[TroupeError]) -> str:
    return json.dumps(raised.value.to_data())


# Requirement: troupe has built-in runtimes


def test_a_built_in_needs_no_config() -> None:
    resolved = resolve("ollama", NO_CONFIG, {})
    assert resolved.endpoint == Sourced("http://127.0.0.1:11434", "default")
    assert resolved.model is None
    assert resolved.credential is None


# Requirement: Theatre config overrides a built-in field by field


def test_only_the_model_is_overridden() -> None:
    resolved = resolve("openai", _config(openai={"model": "gpt-test"}), {})
    assert resolved.endpoint == Sourced("https://api.openai.com/v1", "default")
    assert resolved.credential == Sourced("OPENAI_API_KEY", "default")
    assert resolved.model == Sourced("gpt-test", "theatre")


def test_a_new_runtime_is_defined_wholly_by_config() -> None:
    config = _config(myhost={"endpoint": "https://llm.example/v1", "credential": {"env": "K"}})
    resolved = resolve("myhost", config, {})
    assert resolved.endpoint == Sourced("https://llm.example/v1", "theatre")
    assert resolved.credential == Sourced("K", "theatre")


def test_a_runtime_that_doesnt_exist_is_refused_naming_those_that_do() -> None:
    with pytest.raises(TroupeError) as raised:
        resolve("nowhere", NO_CONFIG, {})
    assert raised.value.code == "config.invalid"
    assert "lm-studio, ollama, openai" in raised.value.problem


# Requirement: The person's environment overrides a runtime's values


def test_the_endpoint_from_the_environment() -> None:
    config = _config(openai={"endpoint": "https://gateway.example/v1"})
    env = {"TROUPE_RUNTIME_OPENAI_ENDPOINT": "https://proxy.example/v1"}
    assert resolve("openai", config, env).endpoint == Sourced("https://proxy.example/v1", "env")


def test_a_hyphenated_name() -> None:
    env = {"TROUPE_RUNTIME_LM_STUDIO_MODEL": "qwen3"}
    assert resolve("lm-studio", NO_CONFIG, env).model == Sourced("qwen3", "env")


def test_the_credentials_variable_from_the_environment() -> None:
    env = {"TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV": "MY_OPENAI_KEY"}
    assert resolve("openai", NO_CONFIG, env).credential == Sourced("MY_OPENAI_KEY", "env")


def test_empty_counts_as_unset() -> None:
    env = {"TROUPE_RUNTIME_OLLAMA_ENDPOINT": ""}
    assert resolve("ollama", NO_CONFIG, env).endpoint.source == "default"


def test_another_runtimes_variable_is_not_read() -> None:
    env = {"TROUPE_RUNTIME_ELSEWHERE_ENDPOINT": "not a url"}
    assert resolve("ollama", NO_CONFIG, env).endpoint.source == "default"


# Requirement: A malformed runtime variable is an error


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("TROUPE_RUNTIME_OLLAMA_ENDPOINT", "localhost:11434"),
        ("TROUPE_RUNTIME_OLLAMA_ENDPOINT", "https://u:p@example.com"),
        ("TROUPE_RUNTIME_OLLAMA_MODEL", "a\nb"),
        ("TROUPE_RUNTIME_OLLAMA_CREDENTIAL_ENV", "MY KEY"),
        ("TROUPE_RUNTIME_OLLAMA_CREDENTIAL_ENV", "TROUPE_RUNTIME_CREDENTIAL"),
    ],
)
def test_a_malformed_variable_is_an_error_naming_it(variable: str, value: str) -> None:
    with pytest.raises(TroupeError) as raised:
        resolve("ollama", NO_CONFIG, {variable: value})
    assert raised.value.code == "runtime.invalid-value"
    assert raised.value.details == {
        "variable": variable,
        "accepted": [runtimes.ACCEPTED[variable.removeprefix("TROUPE_RUNTIME_OLLAMA_").lower()]],
    }


MALFORMED = [
    ("TROUPE_RUNTIME_OLLAMA_ENDPOINT", "localhost:11434"),
    ("TROUPE_RUNTIME_OLLAMA_ENDPOINT", "https://u:p@example.com"),
    ("TROUPE_RUNTIME_OLLAMA_MODEL", "a\nb"),
    ("TROUPE_RUNTIME_OLLAMA_CREDENTIAL_ENV", "MY KEY"),
    ("TROUPE_RUNTIME_OLLAMA_CREDENTIAL_ENV", "TROUPE_RUNTIME_CREDENTIAL"),
]


@pytest.mark.parametrize(("variable", "value"), MALFORMED)
def test_a_malformed_variable_names_it_and_whats_accepted_in_problem_fix_and_details(
    variable: str, value: str
) -> None:
    accepted = runtimes.ACCEPTED[variable.removeprefix("TROUPE_RUNTIME_OLLAMA_").lower()]
    with pytest.raises(TroupeError) as raised:
        resolve("ollama", NO_CONFIG, {variable: value})
    error = raised.value
    assert variable in error.problem
    assert accepted in error.problem
    assert variable in error.fix
    assert accepted in error.fix
    assert error.details["variable"] == variable
    assert error.details["accepted"] == [accepted]


CANARY = st.text(alphabet="ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789", min_size=12)
SHAPES = {
    "ENDPOINT": [
        "https://user:{}@example.com/v1",
        "{}.example:11434",
        "https://example.com/{}?q=1",
        "https://example.com/#{}",
    ],
    "MODEL": ["{}\n", "\x00{}", "gpt-{}\r\n"],
    "CREDENTIAL_ENV": ["sk-{}", "sk-test {}", "9{}", "TROUPE_{}", "{}\n"],
}


@given(
    st.sampled_from([(field, shape) for field, shapes in SHAPES.items() for shape in shapes]),
    CANARY,
)
def test_a_malformed_variables_refusal_holds_no_part_of_its_value(
    field_and_shape: tuple[str, str], canary: str
) -> None:
    field, shape = field_and_shape
    variable, value = f"TROUPE_RUNTIME_OLLAMA_{field}", shape.format(canary)
    with pytest.raises(TroupeError) as raised:
        resolve("ollama", NO_CONFIG, {variable: value})
    assert raised.value.code == "runtime.invalid-value"
    error = _error(raised)
    assert canary not in error
    assert json.dumps(value)[1:-1] not in error


def test_a_key_where_a_variables_name_should_be_isnt_in_the_refusal() -> None:
    variable = "TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV"
    with pytest.raises(TroupeError) as raised:
        resolve("openai", NO_CONFIG, {variable: "sk-test q7ZxW9pL"})
    assert raised.value.code == "runtime.invalid-value"
    assert variable in raised.value.problem
    assert "q7ZxW9pL" not in _error(raised)


def test_an_endpoint_carrying_a_password_isnt_in_the_refusal() -> None:
    endpoint = "https://user:hunter2-secret@example.com/v1"
    with pytest.raises(TroupeError) as raised:
        resolve("ollama", NO_CONFIG, {"TROUPE_RUNTIME_OLLAMA_ENDPOINT": endpoint})
    assert raised.value.code == "runtime.invalid-value"
    assert "hunter2-secret" not in _error(raised)
    assert "example.com" not in _error(raised)


# Requirement: The run's model comes from the environment, the actor, then the runtime


def test_the_actors_model() -> None:
    config = _config(openai={"model": "gpt-a"})
    run = for_run("openai", "tester", "gpt-b", config, {"OPENAI_API_KEY": KEY})
    assert run.model == Sourced("gpt-b", "actor")


def test_the_persons_override_wins() -> None:
    env = {"OPENAI_API_KEY": KEY, "TROUPE_RUNTIME_OPENAI_MODEL": "gpt-c"}
    run = for_run("openai", "tester", "gpt-b", NO_CONFIG, env)
    assert run.model == Sourced("gpt-c", "env")


def test_the_runtimes_model_when_the_actor_sets_none() -> None:
    config = _config(openai={"model": "gpt-a"})
    run = for_run("openai", "tester", None, config, {"OPENAI_API_KEY": KEY})
    assert run.model == Sourced("gpt-a", "theatre")


def test_no_model_anywhere_is_refused_naming_the_three_places() -> None:
    with pytest.raises(TroupeError) as raised:
        for_run("openai", "tester", None, NO_CONFIG, {"OPENAI_API_KEY": KEY})
    assert raised.value.code == "runtime.no-model"
    assert raised.value.details == {
        "runtime": "openai",
        "actor": "tester",
        "places": ["actors.tester.model", "runtimes.openai.model", "TROUPE_RUNTIME_OPENAI_MODEL"],
    }


# Requirement: A run's credential is read from the named variable when the run starts

MODEL = _config(openai={"model": "gpt-test"})


def test_the_credential_is_read_from_the_variable_config_names() -> None:
    config = _config(openai={"model": "gpt-test", "credential": {"env": "MY_OPENAI_KEY"}})
    run = for_run("openai", "tester", None, config, {"MY_OPENAI_KEY": KEY, "OPENAI_API_KEY": "x"})
    assert run.value == KEY
    assert run.run_start() == {
        "name": "openai",
        "endpoint": "https://api.openai.com/v1",
        "model": "gpt-test",
        "credential": True,
    }


@pytest.mark.parametrize("env", [{}, {"OPENAI_API_KEY": ""}], ids=["unset", "empty"])
def test_the_key_isnt_set(env: dict[str, str]) -> None:
    with pytest.raises(TroupeError) as raised:
        for_run("openai", "tester", None, MODEL, env)
    assert raised.value.code == "runtime.credential-unset"
    assert raised.value.details == {"runtime": "openai", "variable": "OPENAI_API_KEY"}


def test_a_runtime_with_no_credential_reads_none() -> None:
    run = for_run("ollama", "tester", "llama3.2", NO_CONFIG, {"OPENAI_API_KEY": KEY})
    assert run.value is None
    assert run.run_start()["credential"] is False


def test_the_recorded_runtime_names_the_variable_and_never_the_value() -> None:
    config = _config(openai={"model": "gpt-test", "endpoint": "https://gateway.example/v1"})
    run = for_run("openai", "tester", None, config, {"OPENAI_API_KEY": KEY})
    recorded = run.to_data()
    assert recorded == {
        "name": "openai",
        "endpoint": {"value": "https://gateway.example/v1", "source": "theatre"},
        "model": {"value": "gpt-test", "source": "theatre"},
        "credential": {"env": {"value": "OPENAI_API_KEY", "source": "default"}, "set": True},
    }
    validator_for(PROTOCOL_BASE + "runtime.schema.json#/$defs/resolved").validate(recorded)
    assert KEY not in json.dumps(recorded)


# Requirement: troupe has built-in runtimes (no built-in price)
# Requirement: A run's price is the price of its model

PRICE_A = {"input": 1, "output": 4}
PRICE_B = {"input": 2, "output": 8, "cacheRead": 0.5, "cacheWrite": 0}
PRICED = {"openai": {"prices": {"gpt-a": PRICE_A, "gpt-b": PRICE_B}}}


def test_no_built_in_runtime_names_a_price() -> None:
    assert all("prices" not in runtime for runtime in defaults.RUNTIMES.values())


def test_a_built_in_runtime_with_no_config_gives_a_run_no_price() -> None:
    run = for_run("openai", "tester", "gpt-test", NO_CONFIG, {"OPENAI_API_KEY": KEY})
    assert run.run_start() == {
        "name": "openai",
        "endpoint": "https://api.openai.com/v1",
        "model": "gpt-test",
        "credential": True,
    }
    assert "price" not in run.to_data()


def test_the_actors_model_is_priced() -> None:
    run = for_run("openai", "tester", "gpt-b", _config(**PRICED), {"OPENAI_API_KEY": KEY})
    assert run.run_start()["price"] == PRICE_B
    assert run.to_data()["price"] == {"value": PRICE_B, "source": "theatre"}
    validator_for(PROTOCOL_BASE + "runtime.schema.json#/$defs/resolved").validate(run.to_data())


def test_the_runtimes_own_model_is_priced() -> None:
    config = _config(openai={**PRICED["openai"], "model": "gpt-a"})
    run = for_run("openai", "tester", None, config, {"OPENAI_API_KEY": KEY})
    assert run.run_start()["price"] == PRICE_A


def test_the_model_from_the_environment_has_no_price() -> None:
    env = {"OPENAI_API_KEY": KEY, "TROUPE_RUNTIME_OPENAI_MODEL": "gpt-c"}
    run = for_run("openai", "tester", "gpt-b", _config(**PRICED), env)
    assert run.model == Sourced("gpt-c", "env")
    assert "price" not in run.run_start()
    assert "price" not in run.to_data()


def test_the_model_from_the_environment_is_priced_when_config_prices_it() -> None:
    env = {"OPENAI_API_KEY": KEY, "TROUPE_RUNTIME_OPENAI_MODEL": "gpt-a"}
    run = for_run("openai", "tester", "gpt-b", _config(**PRICED), env)
    assert run.run_start()["price"] == PRICE_A


@pytest.mark.parametrize("model", ["gpt-b-2026-01-01", "GPT-B", "gpt-b ", "gpt"])
def test_a_near_match_has_no_price(model: str) -> None:
    run = for_run("openai", "tester", model, _config(**PRICED), {"OPENAI_API_KEY": KEY})
    assert "price" not in run.run_start()


def test_no_variable_sets_a_price() -> None:
    env = {
        "OPENAI_API_KEY": KEY,
        "TROUPE_RUNTIME_OPENAI_PRICE": json.dumps(PRICE_B),
        "TROUPE_RUNTIME_OPENAI_PRICES": json.dumps({"gpt-b": PRICE_B}),
    }
    run = for_run("openai", "tester", "gpt-b", NO_CONFIG, env)
    assert "price" not in run.run_start()


def test_a_resolved_runtime_shows_the_price_of_its_own_model_only() -> None:
    config = _config(openai={**PRICED["openai"], "model": "gpt-a"})
    shown = resolve("openai", config, {}).to_data({})
    assert shown["price"] == {"value": PRICE_A, "source": "theatre"}
    assert "price" not in resolve("openai", _config(**PRICED), {}).to_data({})


# Requirement: A credential is sent only over HTTPS or to a loopback address


def _on(endpoint: str) -> dict[str, Any]:
    return _config(myhost={"endpoint": endpoint, "model": "m", "credential": {"env": "K"}})


def test_plain_http_to_another_host_is_refused() -> None:
    with pytest.raises(TroupeError) as raised:
        for_run("myhost", "tester", None, _on("http://example.com/v1"), {"K": KEY})
    assert raised.value.code == "runtime.insecure-endpoint"
    assert raised.value.details == {"runtime": "myhost", "endpoint": "http://example.com/v1"}


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:8080/v1",
        "http://127.0.0.2/v1",
        "http://localhost:1234",
        "http://LOCALHOST",
        "http://[::1]:1234/v1",
        "https://example.com/v1",
    ],
)
def test_plain_http_to_this_machine_or_https_anywhere_starts(endpoint: str) -> None:
    assert for_run("myhost", "tester", None, _on(endpoint), {"K": KEY}).value == KEY


@pytest.mark.parametrize(
    "endpoint", ["http://localhost.example.com", "http://127.0.0.1.example.com", "http://10.0.0.1"]
)
def test_a_host_that_only_looks_local_is_refused(endpoint: str) -> None:
    with pytest.raises(TroupeError, match="plain HTTP"):
        for_run("myhost", "tester", None, _on(endpoint), {"K": KEY})


def test_plain_http_without_a_credential_starts() -> None:
    config = _config(myhost={"endpoint": "http://example.com", "model": "m"})
    assert for_run("myhost", "tester", None, config, {}).value is None


# Requirement: A credential too short to mask is refused


def test_a_placeholder_key_is_refused_naming_the_variable_but_not_the_value() -> None:
    with pytest.raises(TroupeError) as raised:
        for_run("myhost", "tester", None, _on("https://x.example"), {"K": "ollama"})
    assert raised.value.code == "runtime.credential-too-short"
    assert raised.value.details == {"runtime": "myhost", "variable": "K", "minimumBytes": 8}
    assert "ollama" not in _error(raised)


@pytest.mark.parametrize(
    ("env", "code"),
    [
        ({}, "runtime.credential-unset"),
        ({"K": "q7Zx"}, "runtime.credential-too-short"),
        ({"K": KEY + "\r\n"}, "runtime.credential-malformed"),
        ({"K": KEY}, "runtime.insecure-endpoint"),
    ],
)
def test_no_refusal_holds_any_part_of_the_value(env: dict[str, str], code: str) -> None:
    with pytest.raises(TroupeError) as raised:
        for_run("myhost", "tester", None, _on("http://example.com"), env)
    assert raised.value.code == code
    for value in env.values():
        for form in (value, value.strip(), json.dumps(value)[1:-1]):
            assert form not in _error(raised)


# Requirement: A credential holding whitespace or a control character is refused


@pytest.mark.parametrize(
    "value",
    ["sk-test-q7ZxW9pL4vR2\r\n", "sk-test q7ZxW9pL4vR2", "sk-test-q7ZxW9pL4vR2\x00"],
    ids=["a line ending", "a space inside", "a control character"],
)
def test_a_malformed_key_is_refused_naming_the_variable_but_not_the_value(value: str) -> None:
    with pytest.raises(TroupeError) as raised:
        for_run("myhost", "tester", None, _on("https://x.example"), {"K": value})
    assert raised.value.code == "runtime.credential-malformed"
    assert raised.value.details == {"runtime": "myhost", "variable": "K"}
    assert "The credential in K," in raised.value.problem
    assert "q7ZxW9pL4vR2" not in _error(raised)


def test_a_short_key_with_a_line_ending_is_refused_as_malformed_not_too_short() -> None:
    with pytest.raises(TroupeError) as raised:
        for_run("myhost", "tester", None, _on("https://x.example"), {"K": "abc\n"})
    assert raised.value.code == "runtime.credential-malformed"


def test_a_well_formed_key_starts_with_that_credential() -> None:
    started = for_run(
        "myhost", "tester", None, _on("https://x.example"), {"K": "sk-test-q7ZxW9pL4vR2"}
    )
    assert started.value == "sk-test-q7ZxW9pL4vR2"


# Requirement: A refusal never repeats a credential variable's name taken from the environment

HEX_NAME = "a3f9c2e17b4d8e05f6a1"
BY_ENV = "TROUPE_RUNTIME_MYHOST_CREDENTIAL_ENV"
CREDENTIAL_REFUSALS = [
    pytest.param(None, "runtime.credential-unset", id="unset"),
    pytest.param(KEY + "\r\n", "runtime.credential-malformed", id="malformed"),
    pytest.param("q7Zx", "runtime.credential-too-short", id="too short"),
]


@pytest.mark.parametrize(("value", "code"), CREDENTIAL_REFUSALS)
def test_a_name_from_the_environment_is_never_repeated_in_a_refusal(
    value: str | None, code: str
) -> None:
    env = {BY_ENV: HEX_NAME} | ({HEX_NAME: value} if value is not None else {})
    with pytest.raises(TroupeError) as raised:
        for_run("myhost", "tester", None, _on("https://x.example"), env)
    assert raised.value.code == code
    assert raised.value.details["namedBy"] == BY_ENV
    assert "variable" not in raised.value.details
    assert BY_ENV in raised.value.problem
    assert HEX_NAME[:8] not in _error(raised)
    if value is not None:
        for form in (value, value.strip(), json.dumps(value)[1:-1]):
            assert form not in _error(raised)


@pytest.mark.parametrize(("value", "code"), CREDENTIAL_REFUSALS)
def test_a_name_from_config_is_named_in_a_refusal(value: str | None, code: str) -> None:
    env = {"K": value} if value is not None else {}
    with pytest.raises(TroupeError) as raised:
        for_run("myhost", "tester", None, _on("https://x.example"), env)
    assert raised.value.code == code
    assert raised.value.details["variable"] == "K"
    assert "namedBy" not in raised.value.details


@pytest.mark.parametrize(("value", "code"), CREDENTIAL_REFUSALS)
def test_a_built_in_name_is_named_in_a_refusal(value: str | None, code: str) -> None:
    env = {"OPENAI_API_KEY": value} if value is not None else {}
    with pytest.raises(TroupeError) as raised:
        for_run("openai", "tester", "gpt-test", NO_CONFIG, env)
    assert raised.value.code == code
    assert raised.value.details["variable"] == "OPENAI_API_KEY"
    assert "OPENAI_API_KEY" in raised.value.problem


@pytest.mark.parametrize(
    "details",
    [
        {"runtime": "myhost", "variable": "K", "namedBy": BY_ENV},
        {"runtime": "myhost"},
    ],
    ids=["both", "neither"],
)
def test_the_schema_takes_exactly_one_of_variable_and_named_by(details: dict[str, str]) -> None:
    with pytest.raises(TroupeError) as raised:
        for_run("myhost", "tester", None, _on("https://x.example"), {})
    error = raised.value.to_data() | {"details": details}
    assert validator_for(PROTOCOL_BASE + "error.schema.json").is_valid(raised.value.to_data())
    assert not validator_for(PROTOCOL_BASE + "error.schema.json").is_valid(error)


# The environment's values are checked as the schema checks config's (design D3)

SCHEMA = PROTOCOL_BASE + "runtime.schema.json#/$defs/"


@given(st.one_of(st.text(max_size=20), st.text(max_size=12).map(lambda s: "https://" + s)))
@example("https://example.com\n")
@example("https://example.com/\x7f")
@example("http://[::1]:1/v1")
def test_the_endpoint_check_and_the_schema_accept_the_same(value: str) -> None:
    assert bool(runtimes.PATTERNS["endpoint"].match(value)) == validator_for(
        SCHEMA + "endpoint"
    ).is_valid(value)


@given(st.text(max_size=300))
@example("a\n")
@example("x" * 256)
@example("x" * 257)
def test_the_model_check_and_the_schema_accept_the_same(value: str) -> None:
    assert bool(runtimes.PATTERNS["model"].match(value)) == validator_for(
        SCHEMA + "model"
    ).is_valid(value)


@given(st.one_of(st.text(max_size=12), st.from_regex(re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,8}"))))
@example("TROUPE_X")
@example("tRoUpE_x")
@example("K\n")
def test_the_variable_check_and_the_schema_accept_the_same(value: str) -> None:
    assert bool(runtimes.VARIABLE_PATTERN.match(value)) == validator_for(
        SCHEMA + "variable"
    ).is_valid(value)


# The Ollama runner names a runtime's endpoint variable in its fixes, with its own copy of core's
# rule, since it can't import core (ollama-uses-runtime design D2, "Risks / Trade-offs"). This is
# the guard against the two drifting apart.


@pytest.mark.parametrize("name", ["ollama", "openai", "lm-studio", "my-gpu-box-2"])
@pytest.mark.parametrize("field", ["endpoint", "model", "credential_env"])
def test_the_ollama_runners_variable_names_are_cores(name: str, field: str) -> None:
    assert ollama_runtime.env_name(name, field) == runtimes.env_name(name, field)


@given(st.from_regex(r"\A[a-z][a-z0-9-]{0,63}\Z"))
def test_the_ollama_runners_endpoint_variable_is_cores_for_any_runtime_name(name: str) -> None:
    assert ollama_runtime.env_name(name, "endpoint") == runtimes.env_name(name, "endpoint")

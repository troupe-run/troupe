"""The OpenAI-style runner publishes closed schemas for its options and its errors (spec:
openai-chat-runner, "The runner publishes its schemas"). The protocol's strictness check runs over
them with every other shipped schema, in core's test_protocol_strict.py."""

import json
from typing import Any

import jsonschema
import pytest

from chat_harness import OWN, RUNNER_SCHEMAS, TEST_LIMITS, own_validator, validator

NAMES = ("options.schema.json", "errors.schema.json")


def _schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((RUNNER_SCHEMAS / name).read_text(encoding="utf-8"))
    return loaded


@pytest.mark.parametrize("name", NAMES)
def test_each_schema_is_draft_2020_12_with_an_id_under_the_plugin(name: str) -> None:
    schema = _schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == OWN + name
    jsonschema.Draft202012Validator.check_schema(schema)


def test_the_options_schema_is_closed_and_defines_only_the_two_limits() -> None:
    schema = _schema("options.schema.json")
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"maxTurns", "maxTotalTokens"}


def test_the_errors_schema_closes_each_error_and_lists_the_four_codes() -> None:
    schema = _schema("errors.schema.json")
    assert schema["unevaluatedProperties"] is False
    codes = {branch["properties"]["code"]["const"] for branch in schema["oneOf"]}
    assert codes == {
        "openai-chat.unknown-option",
        "openai-chat.invalid-options",
        "openai-chat.no-runtime",
        "openai-chat.insecure-endpoint",
    }


@pytest.mark.parametrize(
    "options", [{}, {"maxTurns": 1}, {"maxTotalTokens": 1}, TEST_LIMITS], ids=repr
)
def test_the_options_schema_accepts_each_documented_option(options: dict[str, Any]) -> None:
    assert own_validator("options.schema.json").is_valid(options)


@pytest.mark.parametrize(
    "options",
    [
        {"maxTurns": 0},
        {"maxTurns": 1.5},
        {"maxTurns": True},
        {"maxTotalTokens": "lots"},
        {"maxTotalTokens": -1},
        {"endpoint": "https://api.openai.com/v1"},
        {"model": "small-model"},
        {"troupeConformanceUnknownOption": True},
    ],
    ids=repr,
)
def test_the_options_schema_refuses_a_bad_value_or_an_unknown_key(options: dict[str, Any]) -> None:
    assert not own_validator("options.schema.json").is_valid(options)


@pytest.mark.parametrize(
    "error",
    [
        {
            "code": "openai-chat.unknown-option",
            "problem": "p",
            "fix": "f",
            "details": {"where": "options.endpoint"},
        },
        {
            "code": "openai-chat.no-runtime",
            "problem": "p",
            "fix": "f",
            "details": {"where": "runtime"},
        },
        {
            "code": "openai-chat.insecure-endpoint",
            "problem": "p",
            "fix": "f",
            "details": {"endpoint": "http://models.example.com/v1"},
        },
    ],
)
def test_an_error_the_runner_sends_validates_as_a_runner_error(error: dict[str, Any]) -> None:
    response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "p", "data": error}}
    assert validator("message.schema.json#/$defs/fromRunner").is_valid(response)


def test_an_error_with_details_its_code_doesnt_define_is_refused() -> None:
    error = {
        "code": "openai-chat.insecure-endpoint",
        "problem": "p",
        "fix": "f",
        "details": {"where": "runtime"},
    }
    response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "p", "data": error}}
    assert not validator("message.schema.json#/$defs/fromRunner").is_valid(response)

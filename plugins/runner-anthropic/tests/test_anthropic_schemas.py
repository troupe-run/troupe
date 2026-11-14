"""The Anthropic runner publishes closed schemas for its options and its errors (spec:
anthropic-runner, "The runner publishes its schemas").

The protocol's strictness check runs over both with every other shipped schema, in core's
test_protocol_strict.py (its schema_files() takes every plugins/*/src/*/schemas/*.schema.json).
It isn't imported here: it lives in core's tests, and importing it would make this suite reach
core's. What this file checks is what that check can't: the draft, the $id, which options and
codes there are, and that documented options and the errors the runner sends validate."""

import json
from typing import Any

import jsonschema
import pytest

from anthropic_harness import OWN, RUNNER_SCHEMAS, TEST_LIMITS, own_validator, validator

NAMES = ("options.schema.json", "errors.schema.json")

SPEC_CODES = {
    "anthropic.unknown-option",
    "anthropic.invalid-options",
    "anthropic.no-runtime",
    "anthropic.unsupported-endpoint",
    "anthropic.insecure-endpoint",
    "anthropic.credential-mismatch",
    "anthropic.malformed-credential",
}
"""The codes "The runner publishes its schemas" requires, copied from the spec."""


def _schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((RUNNER_SCHEMAS / name).read_text(encoding="utf-8"))
    return loaded


@pytest.mark.parametrize("name", NAMES)
def test_each_schema_is_draft_2020_12_with_an_id_under_the_plugin(name: str) -> None:
    schema = _schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == OWN + name
    jsonschema.Draft202012Validator.check_schema(schema)


def test_the_options_schema_is_closed_and_defines_only_the_four_options() -> None:
    schema = _schema("options.schema.json")
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "maxTurns",
        "maxTotalTokens",
        "maxOutputTokens",
        "contextWindow",
    }
    for name, option in schema["properties"].items():
        assert (option["type"], option["minimum"]) == ("integer", 1), name


def test_the_errors_schema_closes_each_error_and_lists_exactly_the_specs_codes() -> None:
    schema = _schema("errors.schema.json")
    assert schema["unevaluatedProperties"] is False
    codes = [branch["properties"]["code"]["const"] for branch in schema["oneOf"]]
    assert len(codes) == len(set(codes))
    assert set(codes) == SPEC_CODES


# Scenario: The schemas pass the strictness check ("each documented option validates")


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"maxTurns": 1},
        {"maxTotalTokens": 1},
        {"maxOutputTokens": 2048},
        {"contextWindow": 8192},
        TEST_LIMITS,
        {"maxTurns": 3, "maxTotalTokens": 1000, "maxOutputTokens": 2048, "contextWindow": 8192},
    ],
    ids=repr,
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
        {"maxOutputTokens": 0},
        {"contextWindow": "big"},
        {"endpoint": "https://api.anthropic.com"},
        {"model": "small-model"},
        {"troupeConformanceUnknownOption": True},
    ],
    ids=repr,
)
def test_the_options_schema_refuses_a_bad_value_or_an_unknown_key(options: dict[str, Any]) -> None:
    assert not own_validator("options.schema.json").is_valid(options)


def _response(error: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "p", "data": error}}


@pytest.mark.parametrize(
    "error",
    [
        {"code": code, "problem": "p", "fix": "f", "details": {"where": "runtime"}}
        for code in sorted(SPEC_CODES - {"anthropic.insecure-endpoint"})
    ]
    + [
        {
            "code": "anthropic.insecure-endpoint",
            "problem": "p",
            "fix": "f",
            "details": {"endpoint": "http://models.example.com"},
        }
    ],
    ids=lambda error: error["code"],
)
def test_an_error_with_each_spec_code_validates_as_a_runner_error(error: dict[str, Any]) -> None:
    assert validator("message.schema.json#/$defs/fromRunner").is_valid(_response(error))


@pytest.mark.parametrize(
    "error",
    [
        {
            "code": "anthropic.insecure-endpoint",
            "problem": "p",
            "fix": "f",
            "details": {"where": "runtime"},
        },
        {"code": "anthropic.no-runtime", "problem": "p", "fix": "f"},
        {"code": "anthropic.no-such-code", "problem": "p", "fix": "f", "details": {"where": "x"}},
    ],
    ids=["insecure-endpoint with where", "no-runtime without details", "unknown code"],
)
def test_an_error_its_schema_doesnt_define_is_refused(error: dict[str, Any]) -> None:
    assert not validator("message.schema.json#/$defs/fromRunner").is_valid(_response(error))

"""The Claude Code runner publishes closed schemas for its options and its errors (spec:
claude-code-runner, "The runner publishes its schemas")."""

import json
from typing import Any

import jsonschema
import pytest

from claude_harness import OWN, RUNNER_SCHEMAS, own_validator, validator

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


def test_the_options_schema_is_closed() -> None:
    assert _schema("options.schema.json")["additionalProperties"] is False


def test_the_errors_schema_closes_each_error_and_lists_the_four_codes() -> None:
    schema = _schema("errors.schema.json")
    assert schema["unevaluatedProperties"] is False
    codes = {branch["properties"]["code"]["const"] for branch in schema["oneOf"]}
    assert codes == {
        "claude-code.unknown-option",
        "claude-code.invalid-options",
        "claude-code.not-found",
        "claude-code.start-failed",
    }


def test_the_options_schema_accepts_an_empty_object_and_every_option_together() -> None:
    options = {
        "model": "claude-haiku-5-5",
        "maxBudgetUsd": 0.1,
        "permissionMode": "acceptEdits",
        "allowedTools": ["Bash(git status)", "Read"],
        "disallowedTools": ["WebFetch"],
        "settingSources": ["project", "local"],
    }
    assert own_validator("options.schema.json").is_valid({})
    assert own_validator("options.schema.json").is_valid(options)


@pytest.mark.parametrize(
    "error",
    [
        {
            "code": "claude-code.unknown-option",
            "problem": "p",
            "fix": "f",
            "details": {"where": "options.x"},
        },
        {"code": "claude-code.not-found", "problem": "p", "fix": "f", "details": {}},
        {
            "code": "claude-code.not-found",
            "problem": "p",
            "fix": "f",
            "details": {"path": "/usr/bin"},
        },
    ],
)
def test_an_error_the_runner_sends_validates_as_a_runner_error(error: dict[str, Any]) -> None:
    response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "p", "data": error}}
    assert validator("message.schema.json#/$defs/fromRunner").is_valid(response)


def test_an_error_with_a_field_its_code_doesnt_define_is_refused() -> None:
    data = {"code": "claude-code.not-found", "problem": "p", "fix": "f", "details": {"where": "x"}}
    response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "p", "data": data}}
    assert not validator("message.schema.json#/$defs/fromRunner").is_valid(response)

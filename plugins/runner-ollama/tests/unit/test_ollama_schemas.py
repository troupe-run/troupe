"""The Ollama runner publishes closed schemas for its options and its errors (spec: ollama-runner,
"The runner publishes its schemas").

The schemas are checked for strictness with every other schema troupe ships, in troupe's own
test_protocol_strict.py.
"""

import json
from typing import Any

import jsonschema
import pytest

from ollama_harness import OWN, RUNNER_SCHEMAS, new_run_id, own_validator, validator

NAMES = ("options.schema.json", "errors.schema.json")

EVERY_OPTION = {
    "maxTurns": 10,
    "contextLength": 32768,
    "temperature": 0,
    "seed": 7,
    "think": "low",
}


def _schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((RUNNER_SCHEMAS / name).read_text(encoding="utf-8"))
    return loaded


def _run_start(options: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "run/start",
        "params": {
            "runId": new_run_id(),
            "direction": "d",
            "workspace": "/w",
            "options": options,
            "limits": {"eventMaxBytes": 65536},
            "effects": {"write": [], "delete": [], "move": []},
            "scratch": "/s",
            "onContextFull": "fail",
            "runtime": {
                "name": "ollama",
                "endpoint": "http://127.0.0.1:11434",
                "model": "qwen3:4b",
                "credential": False,
            },
        },
    }


@pytest.mark.parametrize("name", NAMES)
def test_each_schema_is_draft_2020_12_with_an_id_under_the_plugin(name: str) -> None:
    schema = _schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == OWN + name
    jsonschema.Draft202012Validator.check_schema(schema)


def test_the_options_schema_is_closed_and_requires_nothing() -> None:
    schema = _schema("options.schema.json")
    assert schema["additionalProperties"] is False
    assert "required" not in schema


def test_the_options_schema_defines_no_endpoint_or_model() -> None:
    # They're the run's runtime's (spec: "The service comes from the run's runtime").
    assert not {"endpoint", "model"} & set(_schema("options.schema.json")["properties"])


def test_the_errors_schema_closes_each_error_and_lists_the_eight_codes() -> None:
    schema = _schema("errors.schema.json")
    assert schema["unevaluatedProperties"] is False
    codes = {branch["properties"]["code"]["const"] for branch in schema["oneOf"]}
    assert codes == {
        "ollama.unknown-option",
        "ollama.invalid-options",
        "ollama.unreachable",
        "ollama.model-not-found",
        "ollama.model-without-tools",
        "ollama.no-runtime",
        "ollama.invalid-runtime",
        "ollama.credential-unsupported",
    }


def test_the_options_schema_accepts_no_options_and_every_option_together() -> None:
    assert own_validator("options.schema.json").is_valid({})
    assert own_validator("options.schema.json").is_valid(EVERY_OPTION)


def test_a_run_start_with_every_option_validates_against_the_bound_contract() -> None:
    assert validator("message.schema.json#/$defs/fromHost").is_valid(_run_start(EVERY_OPTION))


def test_a_run_start_with_an_option_the_runner_doesnt_define_doesnt_validate() -> None:
    options = {"troupeConformanceUnknownOption": True}
    assert not validator("message.schema.json#/$defs/fromHost").is_valid(_run_start(options))


@pytest.mark.parametrize(
    "error",
    [
        {
            "code": "ollama.unknown-option",
            "problem": "p",
            "fix": "f",
            "details": {"where": "options.x"},
        },
        {
            "code": "ollama.unreachable",
            "problem": "p",
            "fix": "f",
            "details": {"endpoint": "http://127.0.0.1:11434"},
        },
        *(
            {"code": code, "problem": "p", "fix": "f", "details": {"where": where}}
            for code, where in (
                ("ollama.no-runtime", "runtime"),
                ("ollama.invalid-runtime", "runtime.endpoint"),
                ("ollama.credential-unsupported", "runtime.credential"),
            )
        ),
        {
            "code": "ollama.model-not-found",
            "problem": "p",
            "fix": "f",
            "details": {"endpoint": "http://127.0.0.1:11434", "model": "qwen3:4b"},
        },
        {
            "code": "ollama.model-without-tools",
            "problem": "p",
            "fix": "f",
            "details": {"model": "gemma3", "capabilities": ["completion"]},
        },
        {
            "code": "ollama.model-without-tools",
            "problem": "p",
            "fix": "f",
            "details": {"model": "m"},
        },
    ],
)
def test_an_error_the_runner_sends_validates_as_a_runner_error(error: dict[str, Any]) -> None:
    response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "p", "data": error}}
    assert validator("message.schema.json#/$defs/fromRunner").is_valid(response)


def test_an_error_with_a_field_its_code_doesnt_define_is_refused() -> None:
    data = {"code": "ollama.unreachable", "problem": "p", "fix": "f", "details": {"where": "x"}}
    response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "p", "data": data}}
    assert not validator("message.schema.json#/$defs/fromRunner").is_valid(response)

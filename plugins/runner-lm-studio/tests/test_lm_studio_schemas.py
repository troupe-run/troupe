"""The runner publishes closed schemas for its options and errors, and its requirements as data
(spec: lm-studio-runner, "The runner publishes its schemas", "The runner publishes its platform
requirements as data"). The protocol's strictness check runs over them with every other shipped
schema, in core's test_protocol_strict.py."""

import json
import tomllib
from typing import Any

import jsonschema
import pytest

from lm_studio_harness import OWN, PACKAGE, ROOT, RUNNER_SCHEMAS, own_validator
from troupe_runner_lm_studio.runner import version_tested_with

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


def test_the_options_schema_is_closed_and_defines_only_the_four_options() -> None:
    schema = _schema("options.schema.json")
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "maxTurns",
        "maxTotalTokens",
        "contextLength",
        "temperature",
    }


def test_the_errors_schema_closes_each_error_and_lists_the_runners_codes() -> None:
    schema = _schema("errors.schema.json")
    assert schema["unevaluatedProperties"] is False
    codes = {branch["properties"]["code"]["const"] for branch in schema["oneOf"]}
    assert codes == {
        "lm-studio.unknown-option",
        "lm-studio.invalid-options",
        "lm-studio.no-runtime",
        "lm-studio.unsupported-endpoint",
        "lm-studio.credential-unsupported",
        "lm-studio.credential-mismatch",
        "lm-studio.unreachable",
        "lm-studio.incompatible",
        "lm-studio.model-not-found",
        "lm-studio.model-without-tools",
    }


def test_the_published_requirement_is_lm_studio_0_4_28_naming_the_library() -> None:
    data = json.loads((PACKAGE / "requirements.json").read_text(encoding="utf-8"))
    (requirement,) = data["requires"]
    assert requirement["name"] == "lm-studio"
    assert requirement["minimum"] == "0.4.28"
    assert "lmstudio 1.5.0" in requirement["why"]
    assert "reports no version" in requirement["why"]
    assert version_tested_with() == "0.4.28"


def test_the_options_schema_accepts_each_documented_option() -> None:
    validator = own_validator("options.schema.json")
    assert validator.is_valid(
        {"maxTurns": 1, "maxTotalTokens": 1, "contextLength": 512, "temperature": 0}
    )


# Requirement: The runner talks to LM Studio only through the lmstudio package


def test_the_plugin_depends_on_the_sdk_and_lmstudio_pinned_and_the_lock_pins_its_tree() -> None:
    plugin = tomllib.loads((PACKAGE.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert plugin["project"]["dependencies"] == ["troupe-plugin-sdk", "lmstudio==1.5.0"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {package["name"]: package for package in lock["package"]}
    assert locked["lmstudio"]["version"] == "1.5.0"
    for dependency in locked["lmstudio"]["dependencies"]:
        assert dependency["name"] in locked

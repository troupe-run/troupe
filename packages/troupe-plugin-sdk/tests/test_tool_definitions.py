"""The tools a runner offers its model, and the limits it may lower (spec: runner-tools, "The tools
are file tools, with no shell", "Each tool's input", "Results are capped by named limits";
runner-sdk design D5, D10)."""

from dataclasses import fields
from typing import Any

import jsonschema
import pytest

from troupe_plugin_sdk import defaults
from troupe_plugin_sdk.defaults import ToolLimits
from troupe_plugin_sdk.tools import Tools


def _closed(schema: dict[str, Any]) -> bool:
    if schema.get("type") == "object":
        return schema.get("additionalProperties") is False and all(
            _closed(prop) for prop in schema.get("properties", {}).values()
        )
    return True


def test_there_are_exactly_the_seven_file_tools_and_no_shell() -> None:
    names = [definition.name for definition in Tools.definitions()]
    assert names == ["Read", "Write", "Edit", "Glob", "Grep", "Delete", "Move"]
    assert Tools.names() == names


@pytest.mark.parametrize("definition", Tools.definitions(), ids=lambda d: d.name)
def test_each_definition_has_a_description_and_a_closed_valid_input_schema(definition: Any) -> None:  # noqa: ANN401
    assert definition.description
    jsonschema.Draft202012Validator.check_schema(definition.input_schema)
    assert _closed(definition.input_schema)


EXAMPLES = [
    ("Read", {"file_path": "src/a.py"}),
    ("Read", {"file_path": "src/a.py", "offset": 10, "limit": 5}),
    ("Write", {"file_path": "out/hello.txt", "content": "hello"}),
    ("Edit", {"file_path": "src/a.py", "old_string": "a", "new_string": "b"}),
    ("Edit", {"file_path": "src/a.py", "old_string": "a", "new_string": "b", "replace_all": True}),
    ("Glob", {"pattern": "**/*.py"}),
    ("Glob", {"pattern": "*.py", "path": "src"}),
    ("Grep", {"pattern": "def main", "glob": "**/*.py"}),
    ("Grep", {"pattern": "x", "path": "src"}),
    ("Delete", {"file_path": "out/old.txt"}),
    ("Move", {"source": "drafts/a.md", "destination": "drafts/old/a.md"}),
]


@pytest.mark.parametrize(("name", "data"), EXAMPLES)
def test_the_specs_example_inputs_validate_against_their_tools_schema(
    name: str, data: dict[str, Any]
) -> None:
    [schema] = [d.input_schema for d in Tools.definitions() if d.name == name]
    jsonschema.validate(data, schema)


def test_an_unknown_field_doesnt_validate_against_reads_schema() -> None:
    [schema] = [d.input_schema for d in Tools.definitions() if d.name == "Read"]
    assert not jsonschema.Draft202012Validator(schema).is_valid(
        {"file_path": "a", "encoding": "utf-8"}
    )


def test_the_limits_default_to_their_named_defaults() -> None:
    limits = ToolLimits()
    assert limits.read_max_bytes == defaults.READ_MAX_BYTES
    assert limits.read_max_lines == defaults.READ_MAX_LINES
    assert limits.glob_max_paths == defaults.GLOB_MAX_PATHS
    assert limits.grep_max_matches == defaults.GREP_MAX_MATCHES
    assert limits.grep_file_max_bytes == defaults.GREP_FILE_MAX_BYTES
    assert limits.summary_max_bytes == defaults.SUMMARY_MAX_BYTES


@pytest.mark.parametrize("name", [f.name for f in fields(ToolLimits)])
def test_each_limit_can_be_lowered(name: str) -> None:
    assert getattr(ToolLimits(**{name: 1}), name) == 1


@pytest.mark.parametrize("name", [f.name for f in fields(ToolLimits)])
def test_each_limit_above_its_default_is_refused_naming_it(name: str) -> None:
    default = getattr(ToolLimits(), name)
    expected = rf"ToolLimits\.{name} is {default + 1}, above its default"
    with pytest.raises(ValueError, match=expected):
        ToolLimits(**{name: default + 1})


@pytest.mark.parametrize("value", [0, -1])
def test_a_limit_below_one_is_refused(value: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ToolLimits(read_max_bytes=value)

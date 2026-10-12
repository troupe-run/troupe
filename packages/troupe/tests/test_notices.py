"""Tests for notices (runner-contract design D7)."""

import jsonschema
import pytest

from runner_schemas import SCHEMAS, load
from troupe.core.notices import CODES, Notice

SCHEMA = load(SCHEMAS / "notice.schema.json")


def test_the_notice_schema_is_a_valid_json_schema_with_the_error_schemas_fields() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    error = load(SCHEMAS / "error.schema.json")
    assert SCHEMA["properties"].keys() == error["properties"].keys()
    assert SCHEMA["required"] == error["required"]


@pytest.mark.parametrize("code", sorted(CODES))
def test_every_declared_notice_code_serialises_to_data_the_schema_accepts(code: str) -> None:
    bare = Notice(code, problem="The run has been silent for 30s.", fix="Wait, or cancel it.")
    full = Notice(code, problem="p", fix="f", path="/theatre", details={"seconds": 30})
    for notice in (bare, full):
        jsonschema.validate(notice.to_data(), SCHEMA)


def test_an_undeclared_notice_code_is_refused() -> None:
    with pytest.raises(ValueError, match="undeclared notice code"):
        Notice("run.made-up", problem="p", fix="f")

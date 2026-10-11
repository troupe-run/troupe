import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from troupe.core.errors import CODES, TroupeError
from troupe.core.exit_codes import ExitCode

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "protocol" / "schemas" / "error.schema.json"
SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_error_schema_is_a_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("code", sorted(CODES))
def test_every_declared_error_code_serialises_to_data_the_schema_accepts(code: str) -> None:
    bare = TroupeError(code, problem="something went wrong", fix="do this instead")
    full = TroupeError(
        code,
        problem="something went wrong",
        fix="do this instead",
        path="/home/someone/theatre/.troupe",
        details={"waited_seconds": 1.5},
    )
    for error in (bare, full):
        jsonschema.validate(error.to_data(), SCHEMA)


def test_error_data_leaves_out_path_and_details_when_absent() -> None:
    data = TroupeError("usage.invalid", problem="p", fix="f").to_data()
    assert data == {"code": "usage.invalid", "problem": "p", "fix": "f"}


def test_an_undeclared_error_code_is_refused() -> None:
    with pytest.raises(ValueError, match="undeclared error code"):
        TroupeError("made.up", problem="p", fix="f")


def test_each_error_code_maps_to_a_defined_exit_code() -> None:
    assert all(isinstance(exit_code, ExitCode) for exit_code in CODES.values())
    assert TroupeError("usage.invalid", problem="p", fix="f").exit_code is ExitCode.USAGE

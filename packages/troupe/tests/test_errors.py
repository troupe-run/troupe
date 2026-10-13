import jsonschema
import pytest

from catalogues import branches, detail_keys
from protocol_guard import ProtocolGuardError, unchecked
from protocol_schemas import check_error
from troupe.core.errors import CODES, TroupeError
from troupe.core.exit_codes import ExitCode

# Requirement: Every error and notice code is catalogued with its details

CATALOGUE = branches("error.schema.json")


def test_troupe_declares_exactly_the_error_codes_the_protocol_lists() -> None:
    assert set(CODES) == set(CATALOGUE)


@pytest.mark.parametrize(
    "code", sorted(c for c, b in CATALOGUE.items() if b["properties"]["details"] is False)
)
def test_a_code_without_details_validates_bare_and_refuses_any_detail(code: str) -> None:
    check_error(TroupeError(code, problem="p", fix="f", path="/theatre").to_data())
    with unchecked():
        error = TroupeError(code, problem="p", fix="f", details={"x": 1})
    with pytest.raises(jsonschema.ValidationError):
        check_error(error.to_data())


@pytest.mark.parametrize(
    "code", sorted(c for c, b in CATALOGUE.items() if b["properties"]["details"] is not False)
)
def test_a_code_with_details_refuses_a_detail_its_schema_does_not_define(code: str) -> None:
    with unchecked():
        data = TroupeError(code, problem="p", fix="f", details={"notADetail": 1}).to_data()
    with pytest.raises(jsonschema.ValidationError):
        check_error(data)


def test_an_unlisted_code_does_not_validate() -> None:
    with pytest.raises(jsonschema.ValidationError):
        check_error({"code": "made.up", "problem": "p", "fix": "f"})


# Requirement: Detail keys are camelCase


@pytest.mark.parametrize("code", sorted(CATALOGUE))
def test_no_error_details_schema_defines_a_key_with_an_underscore(code: str) -> None:
    assert {
        key for key in detail_keys(CATALOGUE[code]["properties"]["details"]) if "_" in key
    } == set()


def test_error_data_leaves_out_path_and_details_when_absent() -> None:
    data = TroupeError("usage.invalid", problem="p", fix="f").to_data()
    assert data == {"code": "usage.invalid", "problem": "p", "fix": "f"}


def test_an_undeclared_error_code_is_refused() -> None:
    with pytest.raises(ValueError, match="undeclared error code"):
        TroupeError("made.up", problem="p", fix="f")


def test_each_error_code_maps_to_a_defined_exit_code() -> None:
    assert all(isinstance(exit_code, ExitCode) for exit_code in CODES.values())
    assert TroupeError("usage.invalid", problem="p", fix="f").exit_code is ExitCode.USAGE


# Requirement: Every error, notice and recorded event is checked as tests make it


def test_constructing_an_error_with_a_detail_its_schema_does_not_define_fails_naming_both() -> None:
    with pytest.raises(ProtocolGuardError, match=r"'lock.timeout'.*'bogus' was unexpected"):
        TroupeError("lock.timeout", problem="p", fix="f", details={"waitedSeconds": 1, "bogus": 2})

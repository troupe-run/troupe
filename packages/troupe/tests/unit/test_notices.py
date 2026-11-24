"""Tests for notices (runner-contract design D7)."""

import jsonschema
import pytest

from catalogues import branches, detail_keys
from protocol_guard import ProtocolGuardError, unchecked
from protocol_schemas import SCHEMAS, check_notice, load
from troupe.core.notices import CODES, Notice


def test_a_notice_has_the_same_fields_as_an_error() -> None:
    fields = load(SCHEMAS / "notice.schema.json")["$defs"]["fields"]
    error_fields = load(SCHEMAS / "error.schema.json")["$defs"]["fields"]
    assert fields["properties"].keys() == error_fields["properties"].keys()
    assert fields["required"] == error_fields["required"]


# Requirement: Every error and notice code is catalogued with its details

CATALOGUE = branches("notice.schema.json")


def test_troupe_declares_exactly_the_notice_codes_the_protocol_lists() -> None:
    assert set(CODES) == set(CATALOGUE)


@pytest.mark.parametrize("code", sorted(CATALOGUE))
def test_a_notice_refuses_a_detail_its_codes_schema_does_not_define(code: str) -> None:
    with unchecked():
        notice = Notice(code, problem="p", fix="f", details={"notADetail": 1})
    with pytest.raises(jsonschema.ValidationError):
        check_notice(notice.to_data())


@pytest.mark.parametrize("code", sorted(CATALOGUE))
def test_no_notice_details_schema_defines_a_key_with_an_underscore(code: str) -> None:
    assert {
        key for key in detail_keys(CATALOGUE[code]["properties"]["details"]) if "_" in key
    } == set()


def test_an_undeclared_notice_code_is_refused() -> None:
    with pytest.raises(ValueError, match="undeclared notice code"):
        Notice("run.made-up", problem="p", fix="f")


def test_constructing_a_notice_with_a_detail_its_schema_does_not_define_fails_naming_both() -> None:
    with pytest.raises(ProtocolGuardError, match=r"'run.silent'.*'bogus' was unexpected"):
        Notice("run.silent", problem="p", fix="f", details={"seconds": 1, "bogus": 2})

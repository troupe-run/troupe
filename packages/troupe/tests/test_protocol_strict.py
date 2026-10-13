"""Tests for the strictness check and every schema troupe ships (spec: protocol)."""

from pathlib import Path
from typing import Any

import jsonschema
import pytest

from protocol_schemas import ROOT, expected_id, load, schema_files
from strictness import Problem, check

URI = "https://troupe.run/protocol/test.schema.json"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _problems(schema: dict[str, Any], *others: dict[str, Any]) -> list[tuple[str, str]]:
    documents = {URI: {"$schema": DRAFT, "$id": URI, **schema}}
    documents.update({other["$id"]: other for other in others})
    return [(problem.pointer, problem.rule) for problem in check(documents)]


CLOSED: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": {}}

# Requirement: The strictness check proves itself


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        pytest.param(
            {"type": "object", "properties": {"a": {"type": "string"}}},
            [("", "accepts an object that isn't closed")],
            id="open object",
        ),
        pytest.param(
            {"type": "object"},
            [("", "accepts an object that isn't closed")],
            id="bare object",
        ),
        pytest.param(
            {**CLOSED, "properties": {"a": {"description": "no type"}}},
            [("/properties/a", "constrains no type")],
            id="annotation-only value",
        ),
        pytest.param(
            {**CLOSED, "properties": {"a": True}},
            [("/properties/a", "accepts any value")],
            id="true",
        ),
        pytest.param(
            {**CLOSED, "properties": {"a": {}}},
            [("/properties/a", "accepts any value")],
            id="empty schema",
        ),
        pytest.param(
            {"type": "object", "additionalProperties": {"type": "integer"}},
            [("", "is a map whose keys aren't typed (no propertyNames)")],
            id="map without propertyNames",
        ),
        pytest.param(
            {"type": "object", "additionalProperties": True},
            [
                ("", "accepts an object that isn't closed"),
                ("/additionalProperties", "accepts any value"),
            ],
            id="additionalProperties true",
        ),
        pytest.param(
            {**CLOSED, "properties": {"a": {"type": "array"}}},
            [("/properties/a", "accepts an array without saying what its items are")],
            id="array without items",
        ),
        pytest.param(
            {**CLOSED, "patternProperties": {"^x": {"type": "string"}}},
            [],
            id="pattern properties under a closed object",
        ),
        pytest.param(
            {**CLOSED, "propertiez": {"a": {}}},
            [("/propertiez", "is a keyword the check doesn't know")],
            id="unknown keyword",
        ),
        pytest.param(
            {**CLOSED, "properties": {"a": {"$ref": "#/$defs/missing"}}},
            [("/properties/a/$ref", "refers to '#/$defs/missing', which doesn't resolve")],
            id="reference that doesn't resolve",
        ),
        pytest.param(
            {**CLOSED, "$defs": {"unused": {"type": "object"}}},
            [("/$defs/unused", "accepts an object that isn't closed")],
            id="unused open definition",
        ),
        pytest.param(
            {
                **CLOSED,
                "properties": {"a": {"$ref": "#/$defs/open"}},
                "$defs": {"open": {"type": "object"}},
            },
            [("/$defs/open", "accepts an object that isn't closed")],
            id="open definition reached by reference",
        ),
    ],
)
def test_the_check_reports_each_known_bad_schema_at_the_location_that_breaks_the_rule(
    schema: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    assert _problems(schema) == sorted(expected)


def test_the_check_accepts_branch_properties_under_an_enclosing_unevaluated_properties_false() -> (
    None
):
    schema = {
        "type": "object",
        "required": ["code"],
        "properties": {"code": {"type": "string"}},
        "unevaluatedProperties": False,
        "oneOf": [
            {"properties": {"code": {"const": "a"}, "details": {"$ref": "#/$defs/a"}}},
            {"properties": {"code": {"const": "b"}, "details": False}},
        ],
        "$defs": {
            "a": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"n": {"type": "integer"}},
            }
        },
    }
    assert _problems(schema) == []


def test_the_check_reports_properties_in_a_branch_when_nothing_closes_the_object() -> None:
    schema = {"type": "object", "oneOf": [{"properties": {"code": {"const": "a"}}}]}
    assert _problems(schema) == [
        ("", "accepts an object that isn't closed"),
        ("/oneOf/0", "accepts an object that isn't closed"),
    ]


def test_the_check_accepts_a_closed_dynamic_anchor_default_and_follows_the_dynamic_ref() -> None:
    schema = {
        **CLOSED,
        "properties": {"options": {"$dynamicRef": "#options"}},
        "$defs": {
            "options": {
                "$dynamicAnchor": "options",
                "type": "object",
                "additionalProperties": False,
            }
        },
    }
    assert _problems(schema) == []


def test_the_check_reports_an_open_dynamic_anchor_default() -> None:
    schema = {
        **CLOSED,
        "properties": {"options": {"$dynamicRef": "#options"}},
        "$defs": {"options": {"$dynamicAnchor": "options", "type": "object"}},
    }
    assert _problems(schema) == [("/$defs/options", "accepts an object that isn't closed")]


def test_the_check_follows_references_into_other_documents() -> None:
    other = {
        "$schema": DRAFT,
        "$id": "https://troupe.run/protocol/other.schema.json",
        "type": "object",
    }
    schema = {**CLOSED, "properties": {"a": {"$ref": "other.schema.json"}}}
    documents = {URI: {"$schema": DRAFT, "$id": URI, **schema}, other["$id"]: other}
    assert check(documents) == [Problem(other["$id"], "", "accepts an object that isn't closed")]


def test_the_check_accepts_open_properties_in_if_and_not_since_conditions_never_widen() -> None:
    schema = {
        **CLOSED,
        "properties": {"kind": {"type": "string"}, "n": {"type": "integer"}},
        "if": {"properties": {"kind": {"const": "a"}}},
        "then": {"required": ["n"]},
        "not": {"required": ["kind", "n"]},
    }
    assert _problems(schema) == []


# Requirement: Every schema is JSON Schema draft 2020-12


def _ids(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("path", schema_files(), ids=_ids)
def test_each_shipped_schema_is_a_valid_draft_2020_12_schema(path: Path) -> None:
    jsonschema.Draft202012Validator.check_schema(load(path))


@pytest.mark.parametrize("path", schema_files(), ids=_ids)
def test_each_shipped_schema_id_matches_its_path(path: Path) -> None:
    assert load(path)["$id"] == expected_id(path)


@pytest.mark.parametrize("path", schema_files(), ids=_ids)
def test_every_reference_in_each_shipped_schema_resolves(path: Path) -> None:
    schema = load(path)
    documents = {load(other)["$id"]: load(other) for other in schema_files()}
    problems = [
        p for p in check(documents) if p.uri == schema["$id"] and "doesn't resolve" in p.rule
    ]
    assert problems == []


# Requirement: Every object is closed; Every value is typed


def test_every_shipped_schema_is_strict() -> None:
    documents = {load(path)["$id"]: load(path) for path in schema_files()}
    assert [str(problem) for problem in check(documents)] == []

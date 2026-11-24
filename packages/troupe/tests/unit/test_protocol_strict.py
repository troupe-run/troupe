"""Tests for the strictness check and every schema troupe ships (spec: protocol)."""

from pathlib import Path
from typing import Any

import jsonschema
import pytest

from protocol_schemas import ROOT, expected_id, load, schema_files
from strictness import NULL_MARKER, Problem, accepts_null, check

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
            {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
            [("", "accepts an object that isn't closed")],
            id="open object",
        ),
        pytest.param(
            {"type": "object"},
            [("", "accepts an object that isn't closed")],
            id="bare object",
        ),
        pytest.param(
            {**CLOSED, "required": ["a"], "properties": {"a": {"description": "no type"}}},
            [("/properties/a", "constrains no type")],
            id="annotation-only value",
        ),
        pytest.param(
            {**CLOSED, "required": ["a"], "properties": {"a": True}},
            [("/properties/a", "accepts any value")],
            id="true",
        ),
        pytest.param(
            {**CLOSED, "required": ["a"], "properties": {"a": {}}},
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
            {**CLOSED, "required": ["a"], "properties": {"a": {"type": "array"}}},
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
            {**CLOSED, "required": ["a"], "properties": {"a": {"$ref": "#/$defs/missing"}}},
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
                "required": ["a"],
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
            {
                "properties": {"code": {"const": "a"}, "details": {"$ref": "#/$defs/a"}},
                "required": ["details"],
            },
            {"properties": {"code": {"const": "b"}, "details": False}},
        ],
        "$defs": {
            "a": {
                "type": "object",
                "additionalProperties": False,
                "required": ["n"],
                "properties": {"n": {"type": "integer"}},
            }
        },
    }
    assert _problems(schema) == []


def test_the_check_reports_properties_in_a_branch_when_nothing_closes_the_object() -> None:
    schema = {
        "type": "object",
        "oneOf": [{"properties": {"code": {"const": "a"}}, "required": ["code"]}],
    }
    assert _problems(schema) == [
        ("", "accepts an object that isn't closed"),
        ("/oneOf/0", "accepts an object that isn't closed"),
    ]


def test_the_check_accepts_a_closed_dynamic_anchor_default_and_follows_the_dynamic_ref() -> None:
    schema = {
        **CLOSED,
        "required": ["options"],
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
        "required": ["options"],
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
    schema = {**CLOSED, "required": ["a"], "properties": {"a": {"$ref": "other.schema.json"}}}
    documents = {URI: {"$schema": DRAFT, "$id": URI, **schema}, other["$id"]: other}
    assert check(documents) == [Problem(other["$id"], "", "accepts an object that isn't closed")]


def test_the_check_accepts_open_properties_in_if_and_not_since_conditions_never_widen() -> None:
    schema = {
        **CLOSED,
        "properties": {
            "kind": {"type": "string"},
            "n": {"type": "integer", "description": "Absent unless kind is a."},
        },
        "required": ["kind"],
        "if": {"properties": {"kind": {"const": "a"}}},
        "then": {"required": ["n"]},
        "not": {"required": ["kind", "n"]},
    }
    assert _problems(schema) == []


# Requirement: Null is accepted only where it is marked


def _with_a(value: object) -> dict[str, Any]:
    return {**CLOSED, "required": ["a"], "properties": {"a": value}}


MARKER = {"kind": "external", "means": "the request couldn't be read"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(
            {"type": "null"},
            [("/properties/a", "accepts null without saying why")],
            id="type null",
        ),
        pytest.param(
            {"type": ["string", "null"]},
            [("/properties/a", "accepts null without saying why")],
            id="type list with null",
        ),
        pytest.param(
            {"const": None},
            [("/properties/a", "accepts null without saying why")],
            id="const null",
        ),
        pytest.param(
            {"enum": ["a", None]},
            [("/properties/a", "accepts null without saying why")],
            id="enum with null",
        ),
        pytest.param(
            {"type": "null", "x-troupe-null": {"kind": "sometimes", "means": "x"}},
            [("/properties/a/x-troupe-null", "has a malformed null marker")],
            id="marker with unknown kind",
        ),
        pytest.param(
            {"type": "null", "x-troupe-null": {"kind": "clear", "means": " "}},
            [("/properties/a/x-troupe-null", "has a malformed null marker")],
            id="marker with empty meaning",
        ),
        pytest.param(
            {"type": "null", "x-troupe-null": {**MARKER, "since": "1"}},
            [("/properties/a/x-troupe-null", "has a malformed null marker")],
            id="marker with an extra field",
        ),
        pytest.param(
            {"type": "string", "x-troupe-null": MARKER},
            [("/properties/a", "marks a null it doesn't accept")],
            id="stray marker",
        ),
        pytest.param(
            {"anyOf": [{"type": "integer"}, {"type": "null", "x-troupe-null": MARKER}]},
            [],
            id="marked null",
        ),
        pytest.param(
            {"type": "string", "not": {"type": "null"}},
            [],
            id="null only in a condition",
        ),
        pytest.param(
            {"type": "integer", "if": {"enum": [0, None]}, "then": {"minimum": 0}},
            [],
            id="null only in if",
        ),
    ],
)
def test_the_check_reports_each_unmarked_or_badly_marked_null_at_its_location(
    value: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    assert _problems(_with_a(value)) == sorted(expected)


# Requirement: Absent fields are left out, never sent as null (absence is described)


def test_the_check_reports_an_optional_property_with_no_description() -> None:
    schema = {**CLOSED, "properties": {"a": {"type": "string"}}}
    assert _problems(schema) == [
        ("/properties/a", "is optional but doesn't say what its absence means")
    ]


def test_the_check_accepts_a_described_optional_property_and_an_undescribed_required_one() -> None:
    schema = {
        **CLOSED,
        "required": ["b"],
        "properties": {
            "a": {"type": "string", "description": "Absent when there's nothing to say."},
            "b": {"type": "string"},
            "c": False,
        },
    }
    assert _problems(schema) == []


def test_a_field_only_a_branch_declares_must_say_what_its_absence_means() -> None:
    schema = {
        **CLOSED,
        "required": ["kind"],
        "properties": {"kind": {"enum": ["a", "b"]}},
        "unevaluatedProperties": False,
        "oneOf": [
            {"properties": {"kind": {"const": "a"}, "note": {"type": "string"}}},
            {
                "properties": {
                    "kind": {"const": "b"},
                    "note": {"description": "Absent: nothing to add.", "type": "string"},
                }
            },
        ],
    }
    assert _problems(schema) == [
        ("/oneOf/0/properties/note", "is optional but doesn't say what its absence means")
    ]


def test_a_field_described_through_a_reference_or_all_of_is_covered_in_a_branch() -> None:
    schema = {
        **CLOSED,
        "$ref": "#/$defs/base",
        "allOf": [{"properties": {"extra": {"description": "Absent: none.", "type": "string"}}}],
        "oneOf": [{"properties": {"note": {"const": "x"}, "extra": {"const": "y"}}}],
        "$defs": {
            "base": {
                "type": "object",
                "properties": {"note": {"description": "Absent: none.", "type": "string"}},
            }
        },
    }
    assert _problems(schema) == []


def test_the_check_leaves_properties_refined_by_a_branch_to_the_object_that_declares_them() -> None:
    schema = {
        **CLOSED,
        "required": ["code"],
        "properties": {"code": {"type": "string"}},
        "oneOf": [{"properties": {"code": {"const": "a"}}}],
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


# Requirement: The JSON-RPC error id is the one marked null


def _null_nodes(node: object, pointer: str = "") -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if isinstance(node, dict):
        if accepts_null(node):
            found.append((pointer, node.get(NULL_MARKER)))
        for key, value in node.items():
            if key not in ("enum", "const", "examples", "default", NULL_MARKER):
                found.extend(_null_nodes(value, f"{pointer}/{key}"))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_null_nodes(item, f"{pointer}/{index}"))
    return found


def test_the_only_null_in_the_shipped_schemas_is_the_error_responses_external_id() -> None:
    found = [
        (_ids(path), pointer, marker)
        for path in schema_files()
        for pointer, marker in _null_nodes(load(path))
    ]
    assert [(where, pointer) for where, pointer, _ in found] == [
        ("protocol/schemas/runner/error-response.schema.json", "/properties/id/anyOf/1")
    ]
    [(_, _, marker)] = found
    assert isinstance(marker, dict)
    assert marker["kind"] == "external"

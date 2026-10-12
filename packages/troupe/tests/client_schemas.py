"""The client protocol's JSON Schemas, loaded for validation in tests (spec: client-protocol).

Every schema under protocol/schemas/ is registered under its $id, so the client schemas' references
to lineage, errors, notices and run events resolve.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMAS = Path(__file__).resolve().parents[3] / "protocol" / "schemas"
CLIENT_SCHEMAS = SCHEMAS / "client"
BASE = "https://troupe.run/protocol/client/"
MESSAGES = {
    method: {part: f"{method}-{part}.schema.json" for part in parts}
    for method, parts in {
        "perform": ("request", "update", "result"),
        "status": ("request", "result"),
        "logs": ("request", "update", "result"),
    }.items()
}
"""Each method's messages, by part."""


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@cache
def registry() -> Registry[Any]:
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012))
        for schema in map(load, sorted(SCHEMAS.rglob("*.schema.json")))
    )


def validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for ``ref``, relative to the client schemas."""
    return jsonschema.Draft202012Validator({"$ref": urljoin(BASE, ref)}, registry=registry())


def is_valid(instance: object, ref: str) -> bool:
    return validator(ref).is_valid(instance)


def check(instance: object, ref: str) -> None:
    validator(ref).validate(instance)

"""The event store's JSON Schemas, loaded for validation in tests (event-store design D3, D8, D12).

The schemas in protocol/schemas/ are the source of truth (decision #7). They are registered under
their $ids, so lineage.schema.json can be referenced from event-record.schema.json.
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
BASE = "https://troupe.run/protocol/"
FILES = (
    "lineage.schema.json",
    "event-record.schema.json",
    "notice.schema.json",
    "error.schema.json",
)


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    return data


@cache
def registry() -> Registry[Any]:
    return Registry().with_resources(
        (load(name)["$id"], Resource.from_contents(load(name), default_specification=DRAFT202012))
        for name in FILES
    )


def validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for ``ref``, relative to protocol/schemas (``file.schema.json#/$defs/x``)."""
    return jsonschema.Draft202012Validator({"$ref": urljoin(BASE, ref)}, registry=registry())


def is_valid(instance: object, ref: str) -> bool:
    return validator(ref).is_valid(instance)

"""The runner contract's JSON Schemas, loaded for validation in tests (spec: runner-protocol).

The schemas in protocol/schemas/ are the source of truth (decision #7). Every schema is registered
under its $id, so relative $refs between them, including the shared error schema, resolve.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMAS = Path(__file__).resolve().parents[3] / "protocol" / "schemas"
RUNNER_SCHEMAS = SCHEMAS / "runner"
BASE = "https://troupe.run/protocol/runner/"

RESULT_SCHEMAS = {
    "initialize": "initialize.schema.json#/$defs/result",
    "run/start": "run-start.schema.json#/$defs/result",
    "run/cancel": "run-cancel.schema.json#/$defs/result",
    "shutdown": "shutdown.schema.json#/$defs/result",
}
"""The schema for the result of each request method."""


def schema_files() -> list[Path]:
    return sorted([SCHEMAS / "error.schema.json", *RUNNER_SCHEMAS.glob("*.schema.json")])


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@cache
def registry() -> Registry[Any]:
    resources = [
        (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012))
        for schema in map(load, schema_files())
    ]
    return Registry().with_resources(resources)


def validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for ``ref``, relative to the runner schemas (``file.schema.json#/$defs/x``)."""
    return jsonschema.Draft202012Validator({"$ref": BASE + ref}, registry=registry())


def validate(instance: object, ref: str) -> None:
    validator(ref).validate(instance)


def is_valid(instance: object, ref: str) -> bool:
    return validator(ref).is_valid(instance)


def validate_exchange(sent: list[dict[str, Any]], received: list[dict[str, Any]]) -> None:
    """Validate a conversation: every message, and each success result against its method's schema.

    ``sent`` is what the host wrote and ``received`` what the runner wrote, each in order.
    """
    methods: dict[object, str] = {}
    for message in sent:
        validate(message, "message.schema.json#/$defs/fromHost")
        if "id" in message:
            methods[message["id"]] = message["method"]
    for message in received:
        validate(message, "message.schema.json#/$defs/fromRunner")
        if "result" in message:
            validate(message["result"], RESULT_SCHEMAS[methods[message["id"]]])

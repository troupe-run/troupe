"""The client protocol's JSON Schemas, loaded for validation in tests (spec: client-protocol).

Every schema is loaded once by protocol_schemas, under its $id, so the client schemas' references
to lineage, errors, notices and run events resolve.
"""

from urllib.parse import urljoin

import jsonschema

import protocol_schemas
from protocol_schemas import SCHEMAS, load

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


__all__ = ["CLIENT_SCHEMAS", "MESSAGES", "check", "is_valid", "load", "validator"]


def validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for ``ref``, relative to the client schemas."""
    return protocol_schemas.validator_for(urljoin(BASE, ref))


def is_valid(instance: object, ref: str) -> bool:
    return validator(ref).is_valid(instance)


def check(instance: object, ref: str) -> None:
    validator(ref).validate(instance)

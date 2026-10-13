"""The runner contract's JSON Schemas, for validation in tests (spec: runner-protocol).

The schemas in protocol/schemas/ are the source of truth (decision #7), loaded once by
protocol_schemas, so references between them, including the shared error schema, resolve.

troupe's tests drive the scripted runner, so by default its published schemas fill the contract's
extension points (its options and its own error codes). Pass ``runner=None`` to check against the
contract alone.
"""

from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import jsonschema
from referencing import Registry

import protocol_schemas
from protocol_schemas import SCHEMAS, load

__all__ = [
    "RESULT_SCHEMAS",
    "RUNNER_SCHEMAS",
    "SCHEMAS",
    "SCRIPTED",
    "is_valid",
    "load",
    "registry",
    "schema_files",
    "validate",
    "validate_exchange",
    "validator",
]

RUNNER_SCHEMAS = SCHEMAS / "runner"
SCRIPTED = "runner-scripted"
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


def registry() -> Registry[Any]:
    return protocol_schemas.registry()


def validator(ref: str, runner: str | None = SCRIPTED) -> jsonschema.Draft202012Validator:
    """A validator for ``ref``, relative to the runner schemas (``file.schema.json#/$defs/x``)."""
    return protocol_schemas.validator_for(urljoin(BASE, ref), runner)


def validate(instance: object, ref: str, runner: str | None = SCRIPTED) -> None:
    validator(ref, runner).validate(instance)


def is_valid(instance: object, ref: str, runner: str | None = SCRIPTED) -> bool:
    return validator(ref, runner).is_valid(instance)


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

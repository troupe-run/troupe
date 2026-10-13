"""The event store's JSON Schemas, loaded for validation in tests (event-store design D3, D8, D12).

The schemas in protocol/schemas/ are the source of truth (decision #7). They are loaded once by
protocol_schemas, under their $ids, so lineage.schema.json resolves from event-record.schema.json.
"""

import copy
from typing import Any
from urllib.parse import urljoin

import jsonschema

import protocol_schemas
from protocol_schemas import PROTOCOL_BASE, SCHEMAS

FILES = (
    "lineage.schema.json",
    "event-record.schema.json",
    "notice.schema.json",
    "error.schema.json",
)


def load(name: str) -> dict[str, Any]:
    return protocol_schemas.load(SCHEMAS / name)


def validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for ``ref``, relative to protocol/schemas (``file.schema.json#/$defs/x``)."""
    return protocol_schemas.validator_for(urljoin(PROTOCOL_BASE, ref))


def is_valid(instance: object, ref: str) -> bool:
    return validator(ref).is_valid(instance)


# Example lineage, valid by the schema, for tests to vary.

HASH = "sha256:" + "ab" * 32
OTHER_HASH = "sha256:" + "cd" * 32
ULID = "01K7ZX3N8V4Q2M6R9T5W1Y0B3C"
AT = "2026-10-12T03:04:05.678Z"

LINEAGE: dict[str, Any] = {
    "actor": {"kind": "human", "id": "ada@example.com", "source": "vcs"},
    "via": "cli",
    "at": AT,
    "change": ULID,
    "cause": {"kind": "command", "id": ULID},
    "approvals": [],
    "vcs": {"adapter": "git", "branch": "main", "head": "a" * 40},
}

UNENFORCED_LOCAL: dict[str, Any] = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}
ENFORCED: dict[str, Any] = {"name": "docker", "effects": "enforced"}


def lineage(**changes: object) -> dict[str, Any]:
    result = copy.deepcopy(LINEAGE)
    result.update(changes)
    return result


def without(data: dict[str, Any], key: str) -> dict[str, Any]:
    result = copy.deepcopy(data)
    del result[key]
    return result

"""Every JSON Schema troupe ships, loaded once for validation in tests (spec: protocol).

The schemas in protocol/schemas/ are the source of truth (decision #7), and each plugin publishes
its own under plugins/<name>/schemas/. Every one is registered under its $id, so references between
them resolve, across files and across protocol and plugins.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "protocol" / "schemas"
PLUGINS = ROOT / "plugins"
PROTOCOL_BASE = "https://troupe.run/protocol/"
PLUGINS_BASE = "https://troupe.run/plugins/"


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def protocol_files() -> list[Path]:
    return sorted(SCHEMAS.rglob("*.schema.json"))


def plugin_files() -> list[Path]:
    return sorted(PLUGINS.glob("*/schemas/*.schema.json"))


def schema_files() -> list[Path]:
    """Every schema troupe ships: the protocol's, then each plugin's."""
    return [*protocol_files(), *plugin_files()]


def expected_id(path: Path) -> str:
    """The $id a schema file must have: its path under protocol/schemas/ or plugins/."""
    if path.is_relative_to(SCHEMAS):
        return PROTOCOL_BASE + path.relative_to(SCHEMAS).as_posix()
    plugin, _, name = path.relative_to(PLUGINS).parts
    return f"{PLUGINS_BASE}{plugin}/{name}"


@cache
def registry() -> Registry[Any]:
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012))
        for schema in map(load, schema_files())
    )


def validator(schema: dict[str, Any]) -> jsonschema.Draft202012Validator:
    """A validator for ``schema``, which may refer to any shipped schema by its $id."""
    return jsonschema.Draft202012Validator(schema, registry=registry())


def validator_for(uri: str) -> jsonschema.Draft202012Validator:
    """A validator for the schema at ``uri`` (an absolute $id, optionally with a fragment)."""
    return validator({"$ref": uri})

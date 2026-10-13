"""The error and notice catalogues in protocol/, read for tests (spec: protocol; design D5)."""

from typing import Any

from protocol_schemas import SCHEMAS, load


def branches(name: str) -> dict[str, dict[str, Any]]:
    """Each code in the ``name`` schema's catalogue, with its oneOf branch."""
    schema = load(SCHEMAS / name)
    return {branch["properties"]["code"]["const"]: branch for branch in schema["oneOf"]}


def detail_keys(node: object) -> set[str]:
    """Every property name under a details schema, however deeply nested."""
    if isinstance(node, dict):
        names = (
            set(node.get("properties", {})) if isinstance(node.get("properties"), dict) else set()
        )
        return names | {key for value in node.values() for key in detail_keys(value)}
    if isinstance(node, list):
        return {key for item in node for key in detail_keys(item)}
    return set()

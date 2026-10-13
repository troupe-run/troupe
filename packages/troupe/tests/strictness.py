"""The strictness check for every schema troupe ships (spec: protocol; strict-schemas design D1).

A schema is strict when every object it accepts is closed and every value it accepts is typed. The
walk starts at each document's root and follows references, carrying two facts down from the nodes
that apply to the same instance:

- closed: an enclosing node already shuts the object (``unevaluatedProperties: false``, or
  ``additionalProperties: false`` around a composition), so a branch may declare properties;
- typed: an enclosing node already says what the value is, so a branch may only refine it.

Both are cleared where a keyword describes a new instance (a property's value, an array's items).
Conditions (``if`` and ``not``) never widen what is accepted, so they aren't held to either rule,
nor to the null rule.

A node that accepts null (by ``type``, ``const`` or ``enum``) must carry the null marker, saying
which kind of null it is and what it means (spec: protocol; omit-nulls design D1). A node that
declares an object (its ``type`` includes ``object``) must describe each property it doesn't
require, since that description is where absence is defined (omit-nulls design D2).
Definitions are checked where they're used, and any definition nothing uses is checked on its own.
A keyword the walk doesn't know fails, so nothing is skipped by accident.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urldefrag, urljoin

SAME_INSTANCE_LISTS = ("allOf", "anyOf", "oneOf")
SAME_INSTANCE = ("then", "else")
CONDITIONS = ("if", "not")
NEW_INSTANCE = (
    "additionalProperties",
    "unevaluatedProperties",
    "items",
    "contains",
    "unevaluatedItems",
)
NEW_INSTANCE_MAPS = ("properties", "patternProperties")
REFERENCES = ("$ref", "$dynamicRef")
DEFINITIONS = ("$defs",)
VALUE_KEYWORDS = frozenset(
    {
        "$schema", "$id", "$anchor", "$dynamicAnchor", "$comment", "title", "description",
        "examples", "default", "deprecated", "readOnly", "writeOnly", "type", "const", "enum",
        "format", "pattern", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
        "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "uniqueItems", "minProperties",
        "maxProperties", "required", "dependentRequired", "contentEncoding", "contentMediaType",
        "x-troupe-null",
    }
)  # fmt: skip
"""Keywords whose values are data or annotations, not subschemas."""
SUBSCHEMA_KEYWORDS = frozenset(
    {
        *SAME_INSTANCE_LISTS, *SAME_INSTANCE, *CONDITIONS, *NEW_INSTANCE, *NEW_INSTANCE_MAPS,
        *REFERENCES, "prefixItems", "propertyNames", "dependentSchemas",
    }
)  # fmt: skip
"""Keywords whose values are subschemas the walk follows."""
TYPING = ("type", "const", "enum", *REFERENCES, *SAME_INSTANCE_LISTS)
NULL_MARKER = "x-troupe-null"
NULL_KINDS = ("clear", "external")
"""``clear``: "clear this" in an update, which absence can't say. ``external``: a format troupe
doesn't own requires the null."""


@dataclass(frozen=True, order=True)
class Problem:
    """A place in a schema that breaks a strictness rule."""

    uri: str
    pointer: str
    rule: str

    def __str__(self) -> str:
        return f"{self.uri}#{self.pointer}: {self.rule}"


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _pointer(document: Any, pointer: str) -> Any:  # noqa: ANN401 - any JSON value
    node = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def _anchors(node: Any, pointer: str = "") -> Iterator[tuple[str, str]]:  # noqa: ANN401
    if isinstance(node, dict):
        for key in ("$anchor", "$dynamicAnchor"):
            if isinstance(node.get(key), str):
                yield node[key], pointer
        for key, value in node.items():
            if key not in VALUE_KEYWORDS:
                yield from _anchors(value, f"{pointer}/{_escape(key)}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _anchors(item, f"{pointer}/{index}")


def accepts_null(node: Mapping[str, Any]) -> bool:
    """Whether ``node`` itself lets null through, by ``type``, ``const`` or ``enum``."""
    enum = node.get("enum")
    return (
        "null" in _types(node)
        or ("const" in node and node["const"] is None)
        or (isinstance(enum, list) and None in enum)
    )


def _well_formed_marker(marker: object) -> bool:
    return (
        isinstance(marker, dict)
        and set(marker) == {"kind", "means"}
        and marker["kind"] in NULL_KINDS
        and isinstance(marker["means"], str)
        and marker["means"].strip() != ""
    )


def _types(node: Mapping[str, Any]) -> set[str]:
    declared = node.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return set(declared)
    return set()


class _Walk:
    def __init__(self, documents: Mapping[str, Mapping[str, Any]]) -> None:
        self.documents = documents
        self.problems: set[Problem] = set()
        self.seen: set[tuple[str, str, bool, bool, bool]] = set()
        self.reached: set[tuple[str, str]] = set()

    def report(self, uri: str, pointer: str, rule: str) -> None:
        self.problems.add(Problem(uri, pointer, rule))

    def resolve(self, uri: str, ref: str) -> tuple[str, str] | None:
        target, fragment = urldefrag(urljoin(uri, ref))
        document = self.documents.get(target)
        if document is None:
            return None
        if fragment == "" or fragment.startswith("/"):
            try:
                _pointer(document, fragment)
            except (KeyError, IndexError, ValueError, TypeError):
                return None
            return target, fragment
        for name, pointer in _anchors(document):
            if name == fragment:
                return target, pointer
        return None

    def walk(
        self, uri: str, pointer: str, *, closed: bool, typed: bool, condition: bool = False
    ) -> None:
        key = (uri, pointer, closed, typed, condition)
        if key in self.seen:
            return
        self.seen.add(key)
        self.reached.add((uri, pointer))
        node = _pointer(self.documents[uri], pointer)
        if node is False:
            return
        if node is True or node == {}:
            self.report(uri, pointer, "accepts any value")
            return
        if not isinstance(node, dict):
            self.report(uri, pointer, "isn't a schema")
            return
        self.check(uri, pointer, node, closed=closed, typed=typed)
        if not condition:
            self.check_values(uri, pointer, node)
        self.descend(uri, pointer, node, closed=closed, typed=typed, condition=condition)

    def check(
        self, uri: str, pointer: str, node: Mapping[str, Any], *, closed: bool, typed: bool
    ) -> None:
        if not typed and not any(key in node for key in TYPING):
            self.report(uri, pointer, "constrains no type")
        types = _types(node)
        accepts_object = "object" in types or any(key in node for key in NEW_INSTANCE_MAPS)
        additional = node.get("additionalProperties")
        if isinstance(additional, dict) and "propertyNames" not in node:
            self.report(uri, pointer, "is a map whose keys aren't typed (no propertyNames)")
        shut = additional is False or node.get("unevaluatedProperties") is False
        is_map = isinstance(additional, dict) and additional != {}
        if accepts_object and not (shut or closed or is_map):
            self.report(uri, pointer, "accepts an object that isn't closed")
        if "array" in types and "items" not in node:
            self.report(uri, pointer, "accepts an array without saying what its items are")
        for key in node:
            if key in VALUE_KEYWORDS or key in DEFINITIONS:
                continue
            if key not in SUBSCHEMA_KEYWORDS:
                self.report(uri, f"{pointer}/{_escape(key)}", "is a keyword the check doesn't know")

    def check_values(self, uri: str, pointer: str, node: Mapping[str, Any]) -> None:
        """The rules for what an accepting node (one outside a condition) lets through."""
        marked = NULL_MARKER in node
        if accepts_null(node) and not marked:
            self.report(uri, pointer, "accepts null without saying why")
        if marked and not accepts_null(node):
            self.report(uri, pointer, "marks a null it doesn't accept")
        if marked and not _well_formed_marker(node[NULL_MARKER]):
            self.report(uri, f"{pointer}/{NULL_MARKER}", "has a malformed null marker")
        properties = node.get("properties")
        if "object" in _types(node) and isinstance(properties, dict):
            required = set(node.get("required", []))
            for name, schema in properties.items():
                if name in required or schema is False:
                    continue
                if not (isinstance(schema, dict) and "description" in schema):
                    self.report(
                        uri,
                        f"{pointer}/properties/{_escape(name)}",
                        "is optional but doesn't say what its absence means",
                    )

    def descend(
        self,
        uri: str,
        pointer: str,
        node: Mapping[str, Any],
        *,
        closed: bool,
        typed: bool,
        condition: bool,
    ) -> None:
        here_closed = (
            closed
            or node.get("unevaluatedProperties") is False
            or node.get("additionalProperties") is False
        )
        here_typed = typed or any(key in node for key in TYPING)
        for key in REFERENCES:
            if isinstance(node.get(key), str):
                target = self.resolve(uri, node[key])
                if target is None:
                    self.report(
                        uri, f"{pointer}/{key}", f"refers to {node[key]!r}, which doesn't resolve"
                    )
                else:
                    self.walk(*target, closed=here_closed, typed=typed, condition=condition)
        for key in SAME_INSTANCE_LISTS:
            for index, _ in enumerate(node.get(key, [])):
                self.walk(
                    uri,
                    f"{pointer}/{key}/{index}",
                    closed=here_closed,
                    typed=here_typed,
                    condition=condition,
                )
        for key in SAME_INSTANCE:
            if key in node:
                self.walk(
                    uri,
                    f"{pointer}/{key}",
                    closed=here_closed,
                    typed=here_typed,
                    condition=condition,
                )
        for key in node.get("dependentSchemas", {}):
            self.walk(
                uri,
                f"{pointer}/dependentSchemas/{_escape(key)}",
                closed=here_closed,
                typed=here_typed,
                condition=condition,
            )
        for key in CONDITIONS:
            if key in node:
                self.walk(uri, f"{pointer}/{key}", closed=True, typed=True, condition=True)
        for key in NEW_INSTANCE_MAPS:
            for name in node.get(key, {}):
                self.walk(
                    uri,
                    f"{pointer}/{key}/{_escape(name)}",
                    closed=False,
                    typed=False,
                    condition=condition,
                )
        for key in NEW_INSTANCE:
            if key in node and node[key] is not False:
                if key in ("additionalProperties", "unevaluatedProperties") and node[key] is True:
                    self.report(uri, f"{pointer}/{key}", "accepts any value")
                    continue
                self.walk(uri, f"{pointer}/{key}", closed=False, typed=False, condition=condition)
        for index, _ in enumerate(node.get("prefixItems", [])):
            self.walk(
                uri,
                f"{pointer}/prefixItems/{index}",
                closed=False,
                typed=False,
                condition=condition,
            )
        if "propertyNames" in node:
            # A property name is always a string, so a pattern alone is enough to type it.
            self.walk(
                uri, f"{pointer}/propertyNames", closed=False, typed=True, condition=condition
            )

    def definitions(self, uri: str, node: Any, pointer: str = "") -> Iterator[str]:  # noqa: ANN401
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{pointer}/{_escape(key)}"
                if key in DEFINITIONS and isinstance(value, dict):
                    for name in value:
                        yield f"{child}/{_escape(name)}"
                if key not in VALUE_KEYWORDS:
                    yield from self.definitions(uri, value, child)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                yield from self.definitions(uri, item, f"{pointer}/{index}")


def check(documents: Mapping[str, Mapping[str, Any]]) -> list[Problem]:
    """Every strictness problem in ``documents``, a map of each schema's $id to the schema."""
    walk = _Walk(documents)
    for uri, document in documents.items():
        if set(document) - {"$schema", "$id", "title", "description", "$comment", "$defs"}:
            walk.walk(uri, "", closed=False, typed=False)
    for uri, document in documents.items():
        for pointer in walk.definitions(uri, document):
            if (uri, pointer) not in walk.reached:
                walk.walk(uri, pointer, closed=False, typed=False)
    return sorted(walk.problems)

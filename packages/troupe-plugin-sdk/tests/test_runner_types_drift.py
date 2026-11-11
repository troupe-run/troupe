"""Each runner type has exactly its schema's fields, so a schema that gains, loses or changes the
requiredness of a field fails here until the type follows (spec: plugin-sdk, "The SDK's types are
checked against the contract's schemas"; runner-sdk design D3).

The round-trip tests in test_runner_types.py draw from hand-written strategies, which would keep
passing after a schema gained a field. This compares the two directly: every field the type
declares, with whether it's required, against the schema's `properties` and `required`, following
`$ref`s, and into each nested message type."""

import copy
import dataclasses
import json
import typing
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin

import pytest

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.messages import Message

PROTOCOL = Path(__file__).resolve().parents[3] / "protocol" / "schemas"
ROOT = "https://troupe.run/protocol/"
BASE = ROOT + "runner/"

TYPES: list[tuple[type[Message], str]] = [
    (p.InitializeParams, "initialize.schema.json#/properties/params"),
    (p.InitializeResult, "initialize.schema.json#/$defs/result"),
    (p.RunStartParams, "run-start.schema.json#/properties/params"),
    (p.RunStartResult, "run-start.schema.json#/$defs/result"),
    (p.RunCancelParams, "run-cancel.schema.json#/properties/params"),
    *(
        (cls, f"run-event.schema.json#/$defs/{cls.TYPE}")
        for cls in vars(p).values()
        if isinstance(cls, type) and issubclass(cls, p.RunEvent) and cls.TYPE is not None
    ),
]


def _load(uri: str) -> Any:  # noqa: ANN401 - JSON
    url, fragment = urldefrag(uri)
    node: Any = json.loads((PROTOCOL / url.removeprefix(ROOT)).read_text(encoding="utf-8"))
    for part in [part for part in fragment.split("/") if part]:
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _resolve(node: Any, base: str) -> tuple[Any, str]:  # noqa: ANN401 - JSON
    """``node`` with any `$ref` chain followed, and the URI it now lives at."""
    while isinstance(node, dict) and "$ref" in node and "properties" not in node:
        base = urljoin(base, node["$ref"])
        node = _load(base)
    return node, base


def _fields(cls: type[Message]) -> dict[str, tuple[bool, Any]]:
    """Each JSON field cls declares: whether it's required, and its type hint."""
    hints = typing.get_type_hints(cls)
    found: dict[str, tuple[bool, Any]] = {}
    for field in dataclasses.fields(cls):
        required = field.default is dataclasses.MISSING and (
            field.default_factory is dataclasses.MISSING
        )
        found[field.metadata["json"]] = (required, hints[field.name])
    if issubclass(cls, p.RunEvent) and cls.TYPE is not None:
        found["type"] = (True, str)
    return found


def _message_type(hint: Any) -> type[Message] | None:  # noqa: ANN401 - a type hint
    for candidate in (hint, *typing.get_args(hint)):
        if isinstance(candidate, type) and issubclass(candidate, Message):
            return candidate
    return None


def differences(cls: type[Message], node: Any, base: str, where: str) -> list[str]:  # noqa: ANN401
    """Every way cls's fields differ from the object schema at node, nested types included."""
    node, base = _resolve(node, base)
    properties: dict[str, Any] = node.get("properties", {})
    required = set(node.get("required", []))
    fields = _fields(cls)
    found = [
        f"{where}: the schema has {name!r}, which {cls.__name__} doesn't"
        for name in sorted(set(properties) - set(fields))
    ]
    found += [
        f"{where}: {cls.__name__} has {name!r}, which the schema doesn't"
        for name in sorted(set(fields) - set(properties))
    ]
    for name in sorted(set(fields) & set(properties)):
        is_required, hint = fields[name]
        if is_required != (name in required):
            should = "required" if name in required else "optional"
            found.append(f"{where}: {cls.__name__}.{name} should be {should}, as in the schema")
        nested = _message_type(hint)
        if nested is not None:
            found += differences(nested, properties[name], base, f"{where}.{name}")
    return found


def test_every_event_type_the_schema_lets_a_runner_send_has_an_sdk_type() -> None:
    uri = urljoin(BASE, "run-event.schema.json#/$defs/event")
    defs = _load(urljoin(BASE, "run-event.schema.json#/$defs"))
    schema_types = set()
    for choice in _load(uri)["oneOf"]:
        refs = [choice] if "$ref" in choice else choice["allOf"]
        for ref in refs:
            if "$ref" in ref:
                schema_types.add(defs[ref["$ref"].rsplit("/", 1)[1]]["properties"]["type"]["const"])
    assert schema_types == set(p.EVENT_TYPES)
    assert schema_types == set(typing.get_args(p.EventType))


@pytest.mark.parametrize(("cls", "ref"), TYPES, ids=[cls.__name__ for cls, _ in TYPES])
def test_each_types_fields_are_exactly_its_schemas_properties(cls: type[Message], ref: str) -> None:
    uri = urljoin(BASE, ref)
    assert differences(cls, _load(uri), uri, cls.__name__) == []


def test_a_field_the_schema_gains_is_named_with_the_type(monkeypatch: pytest.MonkeyPatch) -> None:
    uri = urljoin(BASE, "run-event.schema.json#/$defs/tool_result")
    schema = copy.deepcopy(_load(uri))
    schema["properties"]["durationMs"] = {"type": "integer"}

    assert differences(p.ToolResultEvent, schema, uri, "tool_result") == [
        "tool_result: the schema has 'durationMs', which ToolResultEvent doesn't"
    ]


def test_a_field_that_becomes_required_is_named() -> None:
    uri = urljoin(BASE, "run-event.schema.json#/$defs/result")
    schema = copy.deepcopy(_load(uri))
    schema["required"].append("turns")

    assert differences(p.ResultEvent, schema, uri, "result") == [
        "result: ResultEvent.turns should be required, as in the schema"
    ]


def test_a_nested_types_missing_field_is_named_with_its_path() -> None:
    uri = urljoin(BASE, "run-event.schema.json#/$defs/result")
    schema = copy.deepcopy(_load(uri))
    usage, usage_uri = _resolve(schema["properties"]["usage"], uri)
    usage = copy.deepcopy(usage)
    usage["properties"]["reasoningTokens"] = {"type": "integer"}
    schema["properties"]["usage"] = usage

    assert differences(p.ResultEvent, schema, uri, "result") == [
        "result.usage: the schema has 'reasoningTokens', which Usage doesn't"
    ]
    assert usage_uri


def _reasons_differences(reasons: tuple[str, ...], schema_enum: list[str]) -> list[str]:
    found = [
        f"FailureReason lacks {r!r}, which the schema lists"
        for r in schema_enum
        if r not in reasons
    ]
    found += [
        f"FailureReason has {r!r}, which the schema doesn't"
        for r in reasons
        if r not in schema_enum
    ]
    return found


def test_the_failure_reasons_are_exactly_the_schemas() -> None:
    schema = _load(urljoin(BASE, "run-event.schema.json#/$defs/failureReason"))
    assert _reasons_differences(p.FAILURE_REASONS, schema["enum"]) == []


def test_a_reason_the_schema_gains_is_named_with_the_type() -> None:
    schema = _load(urljoin(BASE, "run-event.schema.json#/$defs/failureReason"))
    assert _reasons_differences(p.FAILURE_REASONS, [*schema["enum"], "timeout"]) == [
        "FailureReason lacks 'timeout', which the schema lists"
    ]


def _values_differences(name: str, values: tuple[str, ...], schema_enum: list[str]) -> list[str]:
    found = [f"{name} lacks {v!r}, which the schema lists" for v in schema_enum if v not in values]
    found += [f"{name} has {v!r}, which the schema doesn't" for v in values if v not in schema_enum]
    return found


def test_the_retry_reasons_are_exactly_the_schemas() -> None:
    schema = _load(urljoin(BASE, "run-event.schema.json#/$defs/retryReason"))
    assert _values_differences("RetryReason", p.RETRY_REASONS, schema["enum"]) == []


def test_the_not_retried_values_are_exactly_the_schemas() -> None:
    schema = _load(urljoin(BASE, "run-event.schema.json#/$defs/notRetried"))
    assert _values_differences("NotRetried", p.NOT_RETRIED, schema["enum"]) == []


def test_a_not_retried_value_the_schema_gains_is_named_with_the_type() -> None:
    schema = _load(urljoin(BASE, "run-event.schema.json#/$defs/notRetried"))
    assert _values_differences("NotRetried", p.NOT_RETRIED, [*schema["enum"], "idempotency"]) == [
        "NotRetried lacks 'idempotency', which the schema lists"
    ]

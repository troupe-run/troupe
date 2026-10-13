"""Strict JSON messages as frozen dataclasses (runner-contract design D11; perform-status-logs
design D2).

The JSON Schemas in protocol/ are the source of truth (decision #7). Until a generator is chosen,
each message type mirrors its schema by hand, declaring every field with ``json_field``, and tests
check the types against the schemas. The runner contract and the client protocol both build on
this.

``from_data`` is strict, like the schemas: an unknown field, a missing required field, a wrong type
or a value out of range raises ProtocolError, naming where. ``to_data`` produces the JSON shape,
leaving out optional fields that are absent.
"""

import json
import re
import types
import typing
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields
from typing import Any, ClassVar, Literal, Self, get_args, get_origin, get_type_hints


class ProtocolError(ValueError):
    """A message that breaks its contract: the runner contract, or the client protocol."""


def json_field(
    name: str,
    *,
    default: object = MISSING,
    min_length: int | None = None,
    minimum: int | None = None,
    pattern: re.Pattern[str] | None = None,
    min_items: int | None = None,
    unique: bool = False,
) -> Any:  # noqa: ANN401 - dataclasses.field returns Any
    """A field's JSON name and constraints. A field whose default is None is optional: it is left
    out when it has nothing to say, and never sent or accepted as null (omit-nulls)."""
    metadata = {
        "json": name,
        "min_length": min_length,
        "minimum": minimum,
        "pattern": pattern,
        "min_items": min_items,
        "unique": unique,
    }
    if default is MISSING:
        return field(metadata=metadata)
    return field(default=default, metadata=metadata)


def fail(where: str, problem: str) -> ProtocolError:
    return ProtocolError(f"{where}: {problem}")


def _decode(value: object, hint: object, where: str, meta: Mapping[str, Any]) -> object:
    origin = get_origin(hint)
    if origin in (types.UnionType, typing.Union):
        choices = [arg for arg in get_args(hint) if arg is not type(None)]
        if len(choices) > 1:
            return decode_one_of(choices, value, where)
        return _decode(value, choices[0], where, meta)
    if origin is Literal:
        if value not in get_args(hint) or isinstance(value, bool):
            allowed = ", ".join(repr(arg) for arg in get_args(hint))
            raise fail(where, f"must be one of {allowed}, not {value!r}")
        return value
    if hint is str:
        if not isinstance(value, str):
            raise fail(where, f"must be a string, not {type(value).__name__}")
        if meta.get("min_length") is not None and len(value) < meta["min_length"]:
            raise fail(where, "must not be empty")
        if meta.get("pattern") is not None and not meta["pattern"].match(value):
            raise fail(where, f"{value!r} doesn't match {meta['pattern'].pattern}")
        return value
    if hint is bool:
        if not isinstance(value, bool):
            raise fail(where, f"must be true or false, not {value!r}")
        return value
    if hint is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise fail(where, f"must be an integer, not {value!r}")
        if meta.get("minimum") is not None and value < meta["minimum"]:
            raise fail(where, f"must be at least {meta['minimum']}, not {value}")
        return value
    if hint is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise fail(where, f"must be a number, not {value!r}")
        if meta.get("minimum") is not None and value < meta["minimum"]:
            raise fail(where, f"must be at least {meta['minimum']}, not {value}")
        return float(value)
    if origin is list:
        (item,) = get_args(hint)
        if not isinstance(value, list):
            raise fail(where, "must be an array")
        if meta.get("min_items") is not None and len(value) < meta["min_items"]:
            raise fail(where, f"must have at least {meta['min_items']} item(s)")
        decoded = [_decode(entry, item, f"{where}[{i}]", {}) for i, entry in enumerate(value)]
        if meta.get("unique") and len({json.dumps(v) for v in decoded}) != len(decoded):
            raise fail(where, "must not repeat an item")
        return decoded
    if origin is dict:
        _, item = get_args(hint)
        if not isinstance(value, dict):
            raise fail(where, "must be an object")
        if item is object:
            return dict(value)
        return {
            key: _decode(entry, item, f"{where}.{key}", {"minimum": meta.get("minimum")})
            for key, entry in value.items()
        }
    if isinstance(hint, type) and issubclass(hint, Message):
        return hint._decode(value, where)
    raise TypeError(f"no decoder for {hint!r}")  # a bug in this module, not in the message


def decode_one_of(choices: Sequence[object], value: object, where: str) -> "Message":
    """``value`` as whichever of ``choices`` (message types, each with its own TYPE under the same
    discriminator field) its discriminator names."""
    kinds: dict[object, type[Message]] = {}
    for choice in choices:
        if not (isinstance(choice, type) and issubclass(choice, Message) and choice.TYPE):
            raise TypeError(f"a union of {choices!r} isn't one of tagged messages")
        kinds[choice.TYPE] = choice
    tags = {choice.TYPE_FIELD for choice in kinds.values()}
    if len(tags) != 1:
        raise TypeError(f"the messages in {choices!r} don't share one discriminator field")
    (tag,) = tags
    if not isinstance(value, dict):
        raise fail(where, "must be an object")
    kind = value.get(tag)
    if kind not in kinds:
        allowed = ", ".join(repr(k) for k in kinds)
        raise fail(where, f"{tag} must be one of {allowed}, not {kind!r}")
    return kinds[kind]._decode(value, where)


def decode(hint: object, value: object, where: str) -> object:
    """``value`` decoded as ``hint`` (a message type, or a union of tagged ones), strictly."""
    return _decode(value, hint, where, {})


def _encode(value: object) -> object:
    if isinstance(value, Message):
        return value.to_data()
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


_HINTS: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    if cls not in _HINTS:
        _HINTS[cls] = get_type_hints(cls)
    return _HINTS[cls]


@dataclass(frozen=True)
class Message:
    """Base for every JSON object of the contract."""

    TYPE: ClassVar[str | None] = None
    """For a message that is one of several kinds: the value of its discriminator field."""

    TYPE_FIELD: ClassVar[str] = "type"
    """The discriminator's field: ``type`` in the runner contract, ``kind`` in the client
    protocol."""

    @classmethod
    def from_data(cls, data: object) -> Self:
        return cls._decode(data, cls.__name__)

    @classmethod
    def _decode(cls, data: object, where: str) -> Self:
        if not isinstance(data, dict):
            raise fail(where, "must be an object")
        hints = _hints(cls)
        known = {f.metadata["json"] for f in fields(cls)}
        if cls.TYPE is not None:
            known.add(cls.TYPE_FIELD)
            if data.get(cls.TYPE_FIELD) != cls.TYPE:
                raise fail(where, f"{cls.TYPE_FIELD} must be {cls.TYPE!r}")
        unknown = sorted(set(data) - known)
        if unknown:
            raise fail(where, f"unknown field(s) {', '.join(map(repr, unknown))}")
        values: dict[str, object] = {}
        for f in fields(cls):
            name = f.metadata["json"]
            if name not in data:
                if f.default is MISSING:
                    raise fail(where, f"missing required field {name!r}")
                continue
            values[f.name] = _decode(data[name], hints[f.name], f"{where}.{name}", f.metadata)
        instance = cls(**values)
        instance._check(where)
        return instance

    def _check(self, where: str) -> None:
        """Rules beyond a single field's shape. Raise ProtocolError when broken."""

    def to_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.TYPE is not None:
            data[self.TYPE_FIELD] = self.TYPE
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None and f.default is None:
                continue
            data[f.metadata["json"]] = _encode(value)
        return data

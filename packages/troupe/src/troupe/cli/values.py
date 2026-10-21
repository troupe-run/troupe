"""Values typed on the command line by the schema at their path (spec: config, "Command-line values
are typed by the schema"; config-model design D10).

The core's requests carry JSON values, so typing a value is the CLI's job: a later surface sends
JSON directly. A string field takes the text as given, ``3`` included; an integer, number or
boolean is parsed strictly (``true``, never ``yes``); a list or a group is JSON. Where the schema
gives no single type (an option that is ``oneOf`` several kinds, or a path no schema describes),
the value must be given as JSON with ``--json``, and is refused otherwise, naming the path.

``<path>=@<file>`` reads the value from a file: a string field is the file's text exactly, and
anything else is the file parsed as JSON, or as YAML for ``.yaml`` and ``.yml``.
"""

import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from referencing import Registry
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from troupe.core import interim, schemas, strict_json
from troupe.core.errors import TroupeError

ACTOR_SCHEMA = "https://troupe.run/protocol/config/actor.schema.json"
RUNNER_OPTIONS = "#runnerOptions"


def split_path(dotted: str) -> list[str]:
    """``actors.tester.runner`` as keys. Refused when a key is empty."""
    keys = dotted.split(".")
    if not dotted or any(not key for key in keys):
        raise _usage(dotted, f"{dotted!r} isn't a path: keys joined by dots, none empty")
    return keys


def _usage(path: str, problem: str, fix: str | None = None) -> TroupeError:
    return TroupeError(
        "config.invalid",
        problem=f"{problem}.",
        fix=fix or "Run `troupe config set --help` for how values are written.",
        details={"path": [k for k in path.split(".") if k] or [path], "rule": problem},
    )


# What the schema says a path holds.


def _kinds(node: Any, resolver: Any, runner: str | None, seen: int = 0) -> set[str]:  # noqa: ANN401
    """The JSON types ``node`` allows, following references and combinations."""
    if seen > 32 or not isinstance(node, Mapping):
        return set()
    if node.get("$dynamicRef") == RUNNER_OPTIONS:
        return {"object"}
    if "$ref" in node:
        resolved = resolver.lookup(node["$ref"])
        return _kinds(resolved.contents, resolved.resolver, runner, seen + 1)
    if "const" in node:
        return {_json_type(node["const"])}
    if "enum" in node:
        return {_json_type(value) for value in node["enum"]}
    for combination in ("oneOf", "anyOf"):
        if combination in node:
            branches = [_kinds(b, resolver, runner, seen + 1) for b in node[combination]]
            if "type" in node and not all(branches):
                return _types(node["type"])  # a branch that says no type doesn't narrow it
            found: set[str] = set().union(*branches)
            return found & _types(node["type"]) if "type" in node else found
    if "type" in node:
        return _types(node["type"])
    return set()


def _types(declared: object) -> set[str]:
    if isinstance(declared, str):
        names = {declared}
    else:
        names = {str(n) for n in declared} if isinstance(declared, list) else set()
    if "number" in names:
        names.add("integer")
    return {str(n) for n in names}


def _json_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def _child(node: Any, resolver: Any, key: str) -> tuple[Any, Any] | None:  # noqa: ANN401
    """The schema for ``key`` inside ``node``, an object's schema, and its resolver."""
    for _ in range(32):
        if not isinstance(node, Mapping):
            return None
        if "$ref" in node:
            resolved = resolver.lookup(node["$ref"])
            node, resolver = resolved.contents, resolved.resolver
            continue
        break
    properties = node.get("properties", {}) if isinstance(node, Mapping) else {}
    if key in properties:
        return properties[key], resolver
    for combination in ("oneOf", "anyOf", "allOf"):
        for branch in node.get(combination, ()):
            found = _child(branch, resolver, key)
            if found is not None:
                return found
    extra = node.get("additionalProperties")
    if isinstance(extra, Mapping):
        return extra, resolver
    return None


def kinds_at(path: Sequence[str], runner: str | None) -> set[str]:
    """The JSON types the schema allows at ``path``: empty when no single schema says."""
    if len(path) >= 1 and path[0] != "actors":
        return set()
    if len(path) == 1:
        return {"object"}
    if len(path) == 2:
        return {"object"}
    field = path[2]
    if field == "character":
        return {"string"} if len(path) == 3 else set()
    if field == "options":
        if runner is None or runner not in interim.RUNNERS:
            return set() if len(path) > 3 else {"object"}
        options = interim.options_schema(runner)
        registry: Registry[Any] = schemas.registry(interim.runner(runner).package)
        at: Any = options
        within = registry.resolver(options["$id"])
        for key in path[3:]:
            found = _child(at, within, key)
            if found is None:
                return set()
            at, within = found
        return _kinds(at, within, runner)
    registry = schemas.registry()
    resolver = registry.resolver(ACTOR_SCHEMA)
    node: Any = registry.contents(ACTOR_SCHEMA)
    for key in path[2:]:
        found = _child(node, resolver, key)
        if found is None:
            return set()
        node, resolver = found
    return _kinds(node, resolver, runner)


# Reading a value.


def _from_file(path: str, typed: str, want_text: bool) -> object:
    try:
        data = Path(typed).read_bytes()
    except OSError as error:
        raise _usage(path, f"{typed} couldn't be read: {error.strerror or error}") from error
    if want_text:
        return data.decode("utf-8")
    try:
        if Path(typed).suffix in (".yaml", ".yml"):
            return YAML(typ="safe", pure=True).load(io.BytesIO(data))
        return strict_json.loads(data)
    except (strict_json.StrictJSONError, YAMLError, UnicodeDecodeError) as error:
        raise _usage(path, f"{typed} isn't JSON or YAML: {error}") from error


def value_of(dotted: str, text: str, *, runner: str | None, as_json: bool) -> object:
    """The value ``text`` gives the path ``dotted``, typed by its schema."""
    path = split_path(dotted)
    kinds = kinds_at(path, runner)
    if text.startswith("@"):
        return _from_file(dotted, text[1:], want_text=kinds == {"string"} and not as_json)
    if as_json:
        try:
            return strict_json.loads(text)
        except strict_json.StrictJSONError as error:
            raise _usage(dotted, f"{text!r} isn't JSON ({error})") from error
    if kinds == {"string"}:
        return text
    if kinds == {"boolean"}:
        if text not in ("true", "false"):
            raise _usage(dotted, f"{dotted} is true or false, not {text!r}", "Write true or false.")
        return text == "true"
    if kinds <= {"integer", "number"} and kinds:
        try:
            return int(text) if kinds == {"integer"} else float(text)
        except ValueError as error:
            raise _usage(dotted, f"{dotted} is a number, not {text!r}") from error
    if kinds in ({"array"}, {"object"}):
        try:
            value = strict_json.loads(text)
        except strict_json.StrictJSONError as error:
            raise _usage(
                dotted,
                f"{dotted} is a JSON {'list' if 'array' in kinds else 'group'}"
                f", and {text!r} isn't JSON ({error})",
            ) from error
        if _json_type(value) not in kinds:
            raise _usage(dotted, f"{dotted} is a {'list' if 'array' in kinds else 'group'}")
        return value
    raise _usage(
        dotted,
        f"the schema doesn't give {dotted} one type, so troupe can't tell how to read {text!r}",
        "Give the value as JSON, with --json.",
    )

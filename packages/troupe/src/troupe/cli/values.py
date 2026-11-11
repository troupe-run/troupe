"""Values typed on the command line by the schema at their path (spec: config, "Command-line values
are typed by the schema"; config-model design D10).

The core's requests carry JSON values, so typing a value is the CLI's job: a later surface sends
JSON directly. A string field takes the text as given, ``3`` included; an integer, number or
boolean is parsed strictly (``true``, never ``yes``); a list or a group is JSON. Where the schema
gives no single type (an option that is ``oneOf`` several kinds, or a path no schema describes),
the value must be given as JSON with ``--json``, and is refused otherwise, naming the path.

``<path>=@<file>`` reads the value from a file: a string field is the file's text exactly, and
anything else is the file parsed as JSON, or as YAML for ``.yaml`` and ``.yml``.

A refusal never repeats the value, or any of a file's text: it names the path, what the path takes,
and for JSON or YAML that can't be read, where and why in words that hold none of it. The value may
hold a password, and the person has it on their own command line (spec: config, "A refused config
value is repeated nowhere"; config-set-json-redacts design D1, D2).
"""

import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from referencing import Registry
from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from troupe.core import interim, schemas, strict_json
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError

ACTOR_SCHEMA = "https://troupe.run/protocol/config/actor.schema.json"
RUNTIME_SCHEMA = "https://troupe.run/protocol/config/runtime.schema.json"
RUNNER_OPTIONS = "#runnerOptions"


def _usage(
    path: Sequence[str],
    problem: str,
    fix: str | None = None,
    *,
    line: int | None = None,
    column: int | None = None,
) -> TroupeError:
    """A refusal of the value at ``path``. ``problem`` must hold none of the value; ``line`` and
    ``column`` say where JSON or YAML stopped making sense."""
    details: dict[str, Any] = {"path": list(path), "rule": problem}
    where = ""
    if line is not None and column is not None:
        details |= {"line": line, "column": column}
        where = f" (line {line}, column {column})"
    return TroupeError(
        "config.invalid",
        problem=f"{problem}{where}.",
        fix=fix or "Run `troupe config set --help` for how values are written.",
        details=details,
    )


def _not_json(path: Sequence[str], what: str, error: strict_json.StrictJSONError) -> TroupeError:
    """``what`` isn't JSON: the reason and position, which hold none of the text (design D2)."""
    return _usage(path, f"{what} isn't JSON: {error.rule}", line=error.line, column=error.column)


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
    if len(path) >= 1 and path[0] not in ("actors", "runtimes"):
        return set()
    if len(path) == 1:
        return {"object"}
    if len(path) == 2:
        return {"object"}
    if path[0] == "runtimes":
        return _kinds_in(RUNTIME_SCHEMA, path[2:], runner)
    field = path[2]
    if field == "character":
        return {"string"} if len(path) == 3 else set()
    if field == "options":
        # A runner that isn't installed has no options schema to read here: core's check of the
        # change refuses it, naming the actor's path and the extra (runner-extras design D7).
        if runner is None or runner not in interim.RUNNERS or not interim.installed(runner):
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
    return _kinds_in(ACTOR_SCHEMA, path[2:], runner)


def _kinds_in(schema: str, keys: Sequence[str], runner: str | None) -> set[str]:
    """The JSON types ``schema`` allows at ``keys`` within it."""
    registry = schemas.registry()
    resolver = registry.resolver(schema)
    node: Any = registry.contents(schema)
    for key in keys:
        found = _child(node, resolver, key)
        if found is None:
            return set()
        node, resolver = found
    return _kinds(node, resolver, runner)


# Reading a value.


def _from_file(path: Sequence[str], typed: str, want_text: bool) -> object:
    """The value in the file ``typed``. A refusal names the file and where it broke, never any of
    its text: ruamel's messages quote the file, a repeated key's value included (design D2)."""
    try:
        data = Path(typed).read_bytes()
    except OSError as error:
        raise _usage(path, f"{typed} couldn't be read: {error.strerror or error}") from error
    if want_text:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _usage(path, f"{typed} isn't UTF-8 text (at byte {error.start + 1})") from error
    if Path(typed).suffix in (".yaml", ".yml"):
        try:
            return YAML(typ="safe", pure=True).load(io.BytesIO(data))
        except YAMLError as error:
            mark = error.problem_mark if isinstance(error, MarkedYAMLError) else None
            raise _usage(
                path,
                f"{typed} isn't YAML troupe can read",
                line=None if mark is None else mark.line + 1,
                column=None if mark is None else mark.column + 1,
            ) from error
    try:
        return strict_json.loads(data)
    except strict_json.StrictJSONError as error:
        raise _not_json(path, typed, error) from error


def value_of(path: Sequence[str], text: str, *, runner: str | None, as_json: bool) -> object:
    """The value ``text`` gives ``path``, typed by its schema."""
    dotted = shown(path)
    kinds = kinds_at(path, runner)
    if text.startswith("@"):
        return _from_file(path, text[1:], want_text=kinds == {"string"} and not as_json)
    if as_json:
        try:
            return strict_json.loads(text)
        except strict_json.StrictJSONError as error:
            raise _not_json(path, f"the value for {dotted}", error) from error
    if kinds == {"string"}:
        return text
    if kinds == {"boolean"}:
        if text not in ("true", "false"):
            raise _usage(
                path,
                f"{dotted} is true or false, and the value given isn't",
                "Write true or false.",
            )
        return text == "true"
    if kinds <= {"integer", "number"} and kinds:
        try:
            return int(text) if kinds == {"integer"} else float(text)
        except ValueError as error:
            number = "a whole number" if kinds == {"integer"} else "a number"
            raise _usage(path, f"{dotted} is {number}, and the value given isn't one") from error
    if kinds in ({"array"}, {"object"}):
        try:
            value = strict_json.loads(text)
        except strict_json.StrictJSONError as error:
            kind = "list" if "array" in kinds else "group"
            raise _not_json(
                path, f"{dotted} is a JSON {kind}, and the value given", error
            ) from error
        if _json_type(value) not in kinds:
            raise _usage(path, f"{dotted} is a {'list' if 'array' in kinds else 'group'}")
        return value
    raise _usage(
        path,
        f"the schema doesn't give {dotted} one type, so troupe can't tell how to read the value",
        "Give the value as JSON, with --json.",
    )

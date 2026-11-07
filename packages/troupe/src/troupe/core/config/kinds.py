"""The kinds of config, and what each must hold (spec: config; config-model design D6, D7;
runtimes design D1, D4).

The kinds are the actor and the runtime. An actor is ``actors.<name>``, written to
``actors/<name>.yaml`` and, for its character, ``actors/<name>.md``. A runtime is
``runtimes.<name>``, written to ``runtimes/<name>.yaml``: a service a runner talks to, which an
actor names (spec: runtimes). Rules that span the kinds, such as an actor naming a runtime that
exists, are checked with the rest, so unsetting a runtime an actor uses is refused, and a merge
that does it is a conflict. Its fields, other than the character, are what the actor file's
schema (``protocol/schemas/config/actor.schema.json``) describes, and its options are what its
runner's published options schema describes. Config is checked whole, before a change is recorded
and when branches' changes are merged, so a change that would make config invalid is refused,
naming the path and the rule, and records nothing.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import jsonschema

from troupe.core import defaults, interim, schemas
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError
from troupe_plugin_sdk.effects import Effects, PatternError, pattern_regex

ACTORS = "actors"
RUNTIMES = "runtimes"
KINDS = (ACTORS, RUNTIMES)
"""Every kind of config, by its key at the top of config."""

ACTOR_SCHEMA = "https://troupe.run/protocol/config/actor.schema.json"
"""The actor schema's ``$id``: how troupe finds it among the schemas it carries."""
RUNTIME_SCHEMA = "https://troupe.run/protocol/config/runtime.schema.json"
"""The runtime schema's ``$id``."""


def schema_url(kind: str) -> str:
    """Where config files of ``kind`` (``actor`` or ``runtime``) name their schema: troupe.run, by
    the major version of the protocol troupe carries (website#30; protocol-own-release design
    D7)."""
    return f"https://troupe.run/protocol/{schemas.protocol_major()}/config/{kind}.schema.json"


def actor_schema_url() -> str:
    """Where config files name the actor schema."""
    return schema_url("actor")


def runtime_schema_url() -> str:
    """Where config files name the runtime schema."""
    return schema_url("runtime")


ACTOR_NAME = re.compile(r"\A[a-z][a-z0-9-]{0,63}\Z")
CHARACTER = "character"
WRITTEN_BY_TROUPE = ("$schema",)


@dataclass(frozen=True)
class Problem:
    """Why config isn't valid: the path, and the rule it breaks."""

    path: tuple[str, ...]
    rule: str
    fix: str
    related: tuple[tuple[str, ...], ...] = ()
    """Other paths the rule spans, such as the runtime an actor names: a merge's changes to them
    count as changes to what broke it."""


def problems(config: Mapping[str, Any]) -> list[Problem]:
    """Every way ``config`` breaks a rule, in path order."""
    found: list[Problem] = []
    for key, node in sorted(config.items()):
        if key not in KINDS:
            found.append(
                Problem(
                    (key,),
                    f"config has no kind named {key!r} (the kinds are: {', '.join(KINDS)})",
                    "Unset it.",
                )
            )
        elif not isinstance(node, Mapping):
            found.append(Problem((key,), f"it must be a group of {key}, not a value", "Unset it."))
        elif key == RUNTIMES:
            for name, runtime in sorted(node.items()):
                found += runtime_problems(name, runtime)
    actors = config.get(ACTORS)
    if isinstance(actors, Mapping):
        known = runtime_names(config)
        for name, actor in sorted(actors.items()):
            found += actor_problems(name, actor, known)
    return sorted(found, key=lambda problem: problem.path)


def runtime_names(config: Mapping[str, Any]) -> list[str]:
    """Every runtime an actor can name: troupe's built-in ones and those in config, sorted."""
    node = config.get(RUNTIMES)
    configured = set(node) if isinstance(node, Mapping) else set()
    return sorted(set(defaults.RUNTIMES) | configured)


def runtime_problems(name: str, runtime: object) -> list[Problem]:
    """Every way the runtime ``name`` breaks a rule (spec: runtimes)."""
    base = (RUNTIMES, name)
    if not ACTOR_NAME.match(name):
        return [
            Problem(
                base,
                f"{name!r} isn't a runtime name: lowercase letters, digits and -, starting "
                "with a letter, at most 64",
                f"Unset {shown(base)}, and use a name that fits.",
            )
        ]
    if not isinstance(runtime, Mapping):
        return [Problem(base, "a runtime is a group of values, not a value", "Unset it.")]
    found: list[Problem] = []
    for key in WRITTEN_BY_TROUPE:
        if key in runtime:
            found.append(
                Problem((*base, key), f"{key} is written by troupe, never set", "Unset it.")
            )
    fields = {k: v for k, v in runtime.items() if k not in WRITTEN_BY_TROUPE}
    found += _schema_problems(base, fields, schemas.validator(RUNTIME_SCHEMA), against="runtime")
    if name not in defaults.RUNTIMES and "endpoint" not in runtime:
        found.append(
            Problem(
                (*base, "endpoint"),
                "it's required for a runtime that isn't one of troupe's built-in ones "
                f"({', '.join(sorted(defaults.RUNTIMES))})",
                f"Set {shown((*base, 'endpoint'))}=<url>.",
            )
        )
    return sorted(found, key=lambda problem: problem.path)


def actor_problems(
    name: str, actor: object, runtimes: Sequence[str] | None = None
) -> list[Problem]:
    """Every way the actor ``name`` breaks a rule. ``runtimes`` are the runtimes it can name:
    troupe's built-in ones when it's None."""
    base = (ACTORS, name)
    if not ACTOR_NAME.match(name):
        return [
            Problem(
                base,
                f"{name!r} isn't an actor name: lowercase letters, digits and -, starting "
                "with a letter, at most 64",
                f"Unset {shown(base)}, and use a name that fits.",
            )
        ]
    if not isinstance(actor, Mapping):
        return [Problem(base, "an actor is a group of values, not a value", "Unset it.")]
    found: list[Problem] = []
    for key in WRITTEN_BY_TROUPE:
        if key in actor:
            found.append(
                Problem((*base, key), f"{key} is written by troupe, never set", "Unset it.")
            )
    character = actor.get(CHARACTER)
    if character is not None and not isinstance(character, str):
        found.append(Problem((*base, CHARACTER), "the character is text", "Set it to text."))
    fields = {k: v for k, v in actor.items() if k not in (CHARACTER, "options", *WRITTEN_BY_TROUPE)}
    schema_problems = _schema_problems(base, fields, schemas.validator(ACTOR_SCHEMA))
    found += schema_problems
    if not schema_problems:
        found += _expect_problems(base, actor)
    runner = actor.get("runner")
    if isinstance(runner, str) and runner in interim.RUNNERS:
        options = actor.get("options", {})
        found += _schema_problems(
            (*base, "options"), options, interim.options_validator(runner), runner=runner
        )
    elif isinstance(runner, str) and ACTOR_NAME.match(runner):
        known = ", ".join(sorted(interim.RUNNERS))
        found.append(
            Problem(
                (*base, "runner"),
                f"troupe doesn't know a runner named {runner!r} (it knows: {known})",
                f"Set it to one of: {known}.",
            )
        )
    if not schema_problems:
        known_runtimes = list(runtimes) if runtimes is not None else sorted(defaults.RUNTIMES)
        found += _runtime_problems(base, actor, known_runtimes)
    return sorted(found, key=lambda problem: problem.path)


def _runtime_problems(
    base: tuple[str, ...], actor: Mapping[str, Any], known: list[str]
) -> list[Problem]:
    """Whether the actor's runtime exists and fits its runner, and its model has a runtime (spec:
    runtimes, "An actor names its runtime and may set its model")."""
    at = (*base, "runtime")
    runtime = actor.get("runtime")
    runner = actor.get("runner")
    takes = interim.RUNNERS[runner].runtime if runner in interim.RUNNERS else None
    if runtime is None:
        if takes == "required":
            return [
                Problem(
                    at,
                    f"the {runner} runner needs a runtime (there are: {', '.join(known)})",
                    f"Set {shown(at)} to one of: {', '.join(known)}.",
                )
            ]
        if "model" in actor:
            return [
                Problem(
                    at,
                    "a model is a runtime's, and this actor names no runtime",
                    f"Set {shown(at)}, or unset {shown((*base, 'model'))}.",
                )
            ]
        return []
    if takes == "none":
        return [Problem(at, f"the {runner} runner takes no runtime", f"Unset {shown(at)}.")]
    if runtime not in known:
        return [
            Problem(
                at,
                f"there's no runtime named {runtime!r} (there are: {', '.join(known)})",
                f"Set it to one of: {', '.join(known)}, or define it with troupe config set "
                f"{RUNTIMES}.{runtime}.endpoint=<url>.",
                related=((RUNTIMES, str(runtime)),),
            )
        ]
    return []


def _schema_problems(
    base: tuple[str, ...],
    value: object,
    validator: jsonschema.Draft202012Validator,
    *,
    runner: str | None = None,
    against: str = "actor",
) -> list[Problem]:
    against = f"the {runner} runner's options schema" if runner else f"the {against} schema"
    found: list[Problem] = []
    for error in sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path)):
        path = (*base, *(str(part) for part in error.absolute_path))
        if error.validator == "additionalProperties" and isinstance(error.instance, Mapping):
            allowed = set(error.schema.get("properties", {}))
            for extra in sorted(set(error.instance) - allowed):
                found.append(
                    Problem(
                        (*path, extra),
                        f"there's no such field: {against} doesn't define it",
                        f"Unset {shown((*path, extra))}.",
                    )
                )
            continue
        if error.validator == "required" and isinstance(error.instance, Mapping):
            for missing in sorted(set(error.validator_value) - set(error.instance)):
                hint = " ([] means no file has to change)" if missing == "expect" else ""
                found.append(
                    Problem(
                        (*path, missing),
                        f"it's required{hint}",
                        f"Set {shown((*path, missing))}{hint}.",
                    )
                )
            continue
        pattern = _effect_pattern_problem(path, error)
        if pattern is not None:
            found.append(pattern)
            continue
        found.append(
            Problem(path, _rule(error, against), f"Set {shown(path)} to a value {against} allows.")
        )
    return found


EFFECTS = "effects"


def _effect_pattern_problem(
    path: tuple[str, ...], error: jsonschema.ValidationError
) -> Problem | None:
    """A malformed effect pattern, in the SDK's own words (spec: effects, "A pattern that can't
    be meant is refused"): the list it's in, the pattern and the rule."""
    if error.validator not in ("pattern", "minLength") or not isinstance(error.instance, str):
        return None
    if len(path) < 5 or path[2] != EFFECTS:
        return None
    where = shown(path[:4])
    try:
        pattern_regex(error.instance, where)
    except PatternError as refused:
        rule = str(refused)
    else:  # the schema refused what the SDK accepts: a bug, but say what's known
        rule = f"{where}: {error.instance!r} isn't a pattern the actor schema accepts"
    if error.instance.startswith("/"):
        rule += ". Runs get a scratch directory for temporary files without declaring it"
    return Problem(path[:4], rule, f"Set {where} without {error.instance!r}.")


def _expect_problems(base: tuple[str, ...], actor: Mapping[str, Any]) -> list[Problem]:
    """Each ``expect`` path no ``write`` or ``move`` pattern covers (spec: effects, "Every
    expected file is covered by the declaration"; declared-effects design D2)."""
    expect = actor.get("expect")
    if not isinstance(expect, list) or not expect:
        return []
    declared = actor.get(EFFECTS) or {}
    write = list(declared.get("write") or [])
    move = list(declared.get("move") or [])
    effects = Effects(write=tuple(write), move=tuple(move))
    found: list[Problem] = []
    for index, path in enumerate(expect):
        if effects.allows("write", path) or effects.allows("move", path):
            continue
        target = (*base, EFFECTS, "write")
        fix = json.dumps([*write, path])
        found.append(
            Problem(
                (*base, "expect", str(index)),
                f"{path!r} is expected, but no write or move effect covers it, so the run "
                "couldn't make it",
                f"Declare it: troupe config set {shown(target)}='{fix}'",
            )
        )
    return found


JSON_TYPES = {
    dict: "a group",
    list: "a list",
    str: "a string",
    bool: "a boolean",
    int: "a number",
    float: "a number",
}


def _rule(error: jsonschema.ValidationError, against: str) -> str:
    """What ``error`` says, in words: the schema's own description where it has one."""
    if error.validator == "type":
        wanted: object = error.validator_value
        if isinstance(wanted, str):
            names = [wanted]
        else:
            names = [str(n) for n in wanted] if isinstance(wanted, list) else []
        actual = JSON_TYPES.get(type(error.instance), "a value")
        return f"it must be {' or '.join(_article(n) for n in names)}, not {actual} ({against})"
    if error.validator == "enum" and isinstance(error.validator_value, list):
        accepted = ", ".join(repr(value) for value in error.validator_value)
        return f"it must be one of {accepted}, not {error.instance!r} ({against})"
    description = error.schema.get("description") if isinstance(error.schema, Mapping) else None
    if error.validator in ("pattern", "oneOf", "anyOf", "const") and description:
        return f"it doesn't fit {against}: {description}"
    return f"{error.message} ({against})"


def _article(json_type: str) -> str:
    return {"object": "a group", "array": "a list", "integer": "a whole number"}.get(
        json_type, f"a {json_type}"
    )


def check(config: Mapping[str, Any]) -> None:
    """Refuse ``config`` with ``config.invalid`` when it breaks any rule, naming the first."""
    _refuse(problems(config))


def check_actor(name: str, config: Mapping[str, Any]) -> None:
    """Refuse the actor ``name`` in ``config`` with ``config.invalid`` when it breaks any rule,
    naming the first: what perform checks, so an actor recorded before a rule was tightened can't
    run (spec: effects, "Every expected file is covered by the declaration")."""
    _refuse(actor_problems(name, config[ACTORS][name], runtime_names(config)))


def _refuse(found: list[Problem]) -> None:
    if found:
        first = found[0]
        more = f" ({len(found) - 1} more)" if len(found) > 1 else ""
        raise TroupeError(
            "config.invalid",
            problem=f"{shown(first.path)}: {first.rule}{more}.",
            fix=first.fix,
            details={"path": list(first.path), "rule": first.rule},
        )


# The registry of file kinds (config-model design D7): which files under .troupe/ are config, and
# which aren't. Paths are relative to .troupe/, with / separators.

RESERVED = ("events", "local", ".gitignore", ".gitattributes", "troupe.yaml")
"""Never config: the event store's, troupe's own git files, and troupe.yaml, held for #6's root
file."""

CONFIG_DIRECTORIES = ("actors", "runtimes")
"""The directories that hold config files, one per kind."""

OPERATING_SYSTEM_FILES = (".DS_Store", "Thumbs.db", "desktop.ini")
"""Files an operating system leaves in any directory, ignored wherever they are."""

STAGED_SUFFIX = ".troupe~"
"""A file troupe is part-way through writing is staged beside its target as ``.<name>.troupe~``
(design D9)."""


@dataclass(frozen=True)
class FileKind:
    """A kind of config file: where it is, and what of an actor it holds."""

    pattern: re.Pattern[str]
    kind: str
    holds: str
    """``fields`` (the YAML file: everything but the character), or ``character`` (the text)."""
    schema: str | None


FILE_KINDS = (
    FileKind(re.compile(r"\Aactors/(?P<name>[^/]+)\.yaml\Z"), ACTORS, "fields", ACTOR_SCHEMA),
    FileKind(re.compile(r"\Aactors/(?P<name>[^/]+)\.md\Z"), ACTORS, "character", None),
    FileKind(re.compile(r"\Aruntimes/(?P<name>[^/]+)\.yaml\Z"), RUNTIMES, "fields", RUNTIME_SCHEMA),
)
"""Each kind of config file, matched by path. Shaped as a guest's registration will need (a
pattern, a kind and a schema), though guests can't add to it yet."""


def actor_files(name: str) -> tuple[str, str]:
    """The paths, relative to .troupe/, of the actor ``name``'s YAML file and character file."""
    return f"actors/{name}.yaml", f"actors/{name}.md"


def runtime_file(name: str) -> str:
    """The path, relative to .troupe/, of the runtime ``name``'s file."""
    return f"runtimes/{name}.yaml"


def staged_name(path: str) -> str:
    """Where ``path`` (relative to .troupe/) is staged while troupe writes it."""
    directory, _, name = path.rpartition("/")
    return f"{directory}/.{name}{STAGED_SUFFIX}" if directory else f".{name}{STAGED_SUFFIX}"


def staged_target(path: str) -> str | None:
    """The file a staged ``path`` is for, or None when ``path`` isn't a staged file."""
    directory, _, name = path.rpartition("/")
    if not (name.startswith(".") and name.endswith(STAGED_SUFFIX)):
        return None
    target = name[1 : -len(STAGED_SUFFIX)]
    return f"{directory}/{target}" if directory else target


def file_kind(path: str) -> FileKind | None:
    """The kind of config file at ``path``, or None when it's no kind of config file."""
    for kind in FILE_KINDS:
        match = kind.pattern.match(path)
        if match and ACTOR_NAME.match(match["name"]):
            return kind
    return None

"""The kinds of config, and what each must hold (spec: config; config-model design D6, D7).

The first kind is the actor: ``actors.<name>``, written to ``actors/<name>.yaml`` and, for its
character, ``actors/<name>.md``. Its fields, other than the character, are what the actor file's
schema (``protocol/schemas/config/actor.schema.json``) describes, and its options are what its
runner's published options schema describes. Config is checked whole, before a change is recorded
and when branches' changes are merged, so a change that would make config invalid is refused,
naming the path and the rule, and records nothing.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jsonschema

from troupe.core import interim, schemas
from troupe.core.config.changes import dotted
from troupe.core.errors import TroupeError

ACTORS = "actors"
KINDS = (ACTORS,)
"""Every kind of config, by its key at the top of config."""

ACTOR_SCHEMA = "https://troupe.run/protocol/config/actor.schema.json"
ACTOR_SCHEMA_URL = "https://troupe.run/protocol/0/config/actor.schema.json"
"""Where config files name the actor schema: troupe.run, by major version (website#30)."""

ACTOR_NAME = re.compile(r"\A[a-z][a-z0-9-]{0,63}\Z")
CHARACTER = "character"
WRITTEN_BY_TROUPE = ("$schema",)


@dataclass(frozen=True)
class Problem:
    """Why config isn't valid: the path, and the rule it breaks."""

    path: tuple[str, ...]
    rule: str
    fix: str


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
            found.append(Problem((key,), "it must be a group of actors, not a value", "Unset it."))
        else:
            for name, actor in sorted(node.items()):
                found += actor_problems(name, actor)
    return found


def actor_problems(name: str, actor: object) -> list[Problem]:
    """Every way the actor ``name`` breaks a rule."""
    base = (ACTORS, name)
    if not ACTOR_NAME.match(name):
        return [
            Problem(
                base,
                f"{name!r} isn't an actor name: lowercase letters, digits and -, starting "
                "with a letter, at most 64",
                f"Unset {dotted(base)}, and use a name that fits.",
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
    found += _schema_problems(base, fields, schemas.validator(ACTOR_SCHEMA))
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
    return sorted(found, key=lambda problem: problem.path)


def _schema_problems(
    base: tuple[str, ...],
    value: object,
    validator: jsonschema.Draft202012Validator,
    *,
    runner: str | None = None,
) -> list[Problem]:
    against = f"the {runner} runner's options schema" if runner else "the actor schema"
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
                        f"Unset {dotted((*path, extra))}.",
                    )
                )
            continue
        if error.validator == "required" and isinstance(error.instance, Mapping):
            for missing in sorted(set(error.validator_value) - set(error.instance)):
                hint = " ([] means no effect check)" if missing == "expect" else ""
                found.append(
                    Problem(
                        (*path, missing),
                        f"it's required{hint}",
                        f"Set {dotted((*path, missing))}{hint}.",
                    )
                )
            continue
        found.append(
            Problem(path, _rule(error, against), f"Set {dotted(path)} to a value {against} allows.")
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
    description = error.schema.get("description") if isinstance(error.schema, Mapping) else None
    if error.validator in ("pattern", "oneOf", "anyOf", "enum", "const") and description:
        return f"it doesn't fit {against}: {description}"
    return f"{error.message} ({against})"


def _article(json_type: str) -> str:
    return {"object": "a group", "array": "a list", "integer": "a whole number"}.get(
        json_type, f"a {json_type}"
    )


def check(config: Mapping[str, Any]) -> None:
    """Refuse ``config`` with ``config.invalid`` when it breaks any rule, naming the first."""
    found = problems(config)
    if found:
        first = found[0]
        more = f" ({len(found) - 1} more)" if len(found) > 1 else ""
        raise TroupeError(
            "config.invalid",
            problem=f"{dotted(first.path)}: {first.rule}{more}.",
            fix=first.fix,
            details={"path": list(first.path), "rule": first.rule},
        )

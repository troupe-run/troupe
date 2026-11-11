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
import shlex
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import jsonschema

from troupe.core import defaults, interim, runtimes, schemas
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


Typed = Collection[tuple[str, ...]] | None
"""The paths a person typed in the change being checked, or None when nothing was typed (a merge, a
perform). A key under one of them that isn't on any of them came from inside a value: it's part of
the value, so a rule that refuses it never repeats it (spec: config, "A refused config value is
repeated nowhere"; config-set-json-redacts design D7)."""


def _in_value(path: tuple[str, ...], typed: Typed) -> bool:
    """Whether the last key of ``path`` came from inside a value rather than a typed path."""
    if typed is None:
        return False
    return not any(tuple(each[: len(path)]) == path for each in typed)


def problems(
    config: Mapping[str, Any], touched: Collection[str] = (), typed: Typed = None
) -> list[Problem]:
    """Every way ``config`` breaks a rule, in path order. ``touched`` names the actors the change
    being checked sets or unsets anything under: one of them on a runner that isn't installed is
    refused with runner.not-installed, and any other has its options left unchecked (spec: config;
    runner-extras design D7). ``typed`` are the paths the change's person typed (see ``Typed``)."""
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
                found += runtime_problems(name, runtime, typed)
    actors = config.get(ACTORS)
    if isinstance(actors, Mapping):
        known = runtime_shapes(config)
        for name, actor in sorted(actors.items()):
            found += actor_problems(name, actor, known, touched=name in touched, typed=typed)
    return sorted(found, key=lambda problem: problem.path)


Shapes = Mapping[str, "runtimes.Resolved | None"]
"""Every runtime an actor can name, each as config makes it, or None when it has problems of its
own and so isn't judged for fit (runtime-checks design D3)."""


def runtime_shapes(config: Mapping[str, Any]) -> dict[str, "runtimes.Resolved | None"]:
    """Every runtime an actor can name, built-in or in config, each from its built-in and theatre
    values with no environment, or None when it breaks a rule of its own (runtime-checks design
    D3)."""
    node = config.get(RUNTIMES)
    given = node if isinstance(node, Mapping) else {}
    # Only a runtime with no problems of its own is resolved: resolving assumes the shapes the
    # runtime schema allows, and this is the check that finds the others.
    broken = {name for name, runtime in given.items() if runtime_problems(name, runtime)}
    clean = {name: runtime for name, runtime in given.items() if name not in broken}
    shapes = runtimes.as_configured({RUNTIMES: clean})
    for name in broken:
        shapes[name] = None
    return shapes


def _bad_name(kind: str, base: tuple[str, ...]) -> Problem:
    """A name from inside a value that isn't one: named by the group it's in, never itself."""
    return Problem(
        base[:1],
        f"it holds {_article_for(kind)} {kind} whose name isn't one: lowercase letters, digits and "
        "-, starting with a letter, at most 64",
        f"Set {shown(base[:1])} with names that fit; troupe config get {shown(base[:1])} shows "
        "what it holds.",
    )


def _article_for(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


def runtime_problems(name: str, runtime: object, typed: Typed = None) -> list[Problem]:
    """Every way the runtime ``name`` breaks a rule (spec: runtimes)."""
    base = (RUNTIMES, name)
    if not ACTOR_NAME.match(name) and _in_value(base, typed):
        return [_bad_name("runtime", base)]
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
    found += _schema_problems(
        base, fields, schemas.validator(RUNTIME_SCHEMA), against="runtime", typed=typed
    )
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
    name: str,
    actor: object,
    shapes: Shapes | None = None,
    *,
    touched: bool = True,
    typed: Typed = None,
) -> list[Problem]:
    """Every way the actor ``name`` breaks a rule. ``shapes`` are the runtimes it can name, as
    ``runtime_shapes`` gives them: troupe's built-in ones when it's None. On a runner troupe knows
    but isn't installed, its options can't be checked: when ``touched`` (the change sets or unsets
    something under it, or it's about to be performed) that's refused with runner.not-installed;
    otherwise they're left for when it's next changed or performed where its runner is installed
    (runner-extras D7). Its runtime's fit is checked either way: it needs only the runner table."""
    base = (ACTORS, name)
    if not ACTOR_NAME.match(name) and _in_value(base, typed):
        return [_bad_name("actor", base)]
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
    known = shapes if shapes is not None else runtime_shapes({})
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
    schema_problems = _schema_problems(base, fields, schemas.validator(ACTOR_SCHEMA), typed=typed)
    found += schema_problems
    if not schema_problems:
        found += _expect_problems(base, actor)
    runner = actor.get("runner")
    moved: list[Problem] = []
    if isinstance(runner, str) and runner in interim.RUNNERS and not interim.installed(runner):
        if touched:
            try:
                interim.installed_runner(runner)
            except TroupeError as error:
                at = (*base, "runner")
                raise TroupeError(
                    error.code,
                    problem=f"{shown(at)}: {error.problem}",
                    fix=error.fix,
                    details={**error.details, "path": list(at)},
                ) from None
    elif isinstance(runner, str) and runner in interim.RUNNERS:
        options = actor.get("options", {})
        moved = _moved_problems(base, actor, runner, sorted(known))
        moved_paths = {problem.path for problem in moved}
        found += moved
        found += [
            problem
            for problem in _schema_problems(
                (*base, "options"),
                options,
                interim.options_validator(runner),
                runner=runner,
                typed=typed,
                known=interim.MOVED_OPTIONS,
            )
            if problem.path not in moved_paths
        ]
    elif isinstance(runner, str) and ACTOR_NAME.match(runner):
        runners = ", ".join(sorted(interim.RUNNERS))
        found.append(
            Problem(
                (*base, "runner"),
                f"troupe doesn't know a runner named {runner!r} (it knows: {runners})",
                f"Set it to one of: {runners}.",
            )
        )
    if not schema_problems and not moved:
        # A moved option's fix names the runtime too, so the actor gets one rule with one fix.
        found += _runtime_problems(base, actor, known)
    return sorted(found, key=lambda problem: problem.path)


def _moved_problems(
    base: tuple[str, ...], actor: Mapping[str, Any], runner: str, known: Sequence[str]
) -> list[Problem]:
    """A problem for each option the actor's runner moved to its runtime, whose fix is one config
    set built from the actor's own values (spec: runtimes, "Options a runner moved to its runtime
    are refused with the move"; ollama-uses-runtime design D5)."""
    built_in = interim.MOVED_TO_RUNTIME.get(runner)
    options = actor.get("options")
    if built_in is None or not isinstance(options, Mapping):
        return []
    held = [key for key in interim.MOVED_OPTIONS if key in options]
    if not held:
        return []
    fix = _move_fix(base, actor, options, built_in, known)
    return [
        Problem(
            (*base, "options", key),
            f"{key} moved to the actor's runtime: the {runner} runner takes its endpoint and "
            "model from a runtime now, not from its options",
            fix,
        )
        for key in held
    ]


def _move_fix(
    base: tuple[str, ...],
    actor: Mapping[str, Any],
    options: Mapping[str, Any],
    built_in: str,
    known: Sequence[str],
) -> str:
    """The config set that moves the actor's endpoint and model to a runtime, changing no runtime
    that exists. An endpoint that isn't the built-in runtime's needs a runtime of its own, whose
    name the person chooses, whatever runtime the actor already names, so the endpoint is never
    lost. Otherwise the actor keeps a runtime it names that exists, else gets the built-in one."""
    assignments: list[str] = []
    note = ""
    endpoint = options.get("endpoint")
    default = str(defaults.RUNTIMES[built_in]["endpoint"])
    named = actor.get("runtime")
    if endpoint is None or (
        isinstance(endpoint, str) and endpoint.rstrip("/") == default.rstrip("/")
    ):
        runtime = named if isinstance(named, str) and named in known else built_in
    else:
        runtime = "<name>"
        # Never repeat an endpoint with user info (it may hold a password) or one that isn't
        # plain text: the person gives the URL again.
        url = (
            endpoint
            if isinstance(endpoint, str) and "@" not in endpoint and endpoint.isprintable()
            else "<url>"
        )
        assignments.append(f"{shown((RUNTIMES, '<name>', 'endpoint'))}={url}")
        note = ", choosing a <name> for that Ollama, such as gpu-box"
    assignments.append(f"{shown((*base, 'runtime'))}={runtime}")
    # The actor's own model wins at run time; a model that isn't text is left for the person.
    model = actor.get("model") if isinstance(actor.get("model"), str) else options.get("model")
    if isinstance(model, str) and model and model.isprintable():
        assignments.append(f"{shown((*base, 'model'))}={model}")
    rest = {k: v for k, v in options.items() if k not in interim.MOVED_OPTIONS}
    assignments.append(
        f"{shown((*base, 'options'))}={json.dumps(rest, separators=(',', ':'), sort_keys=True)}"
    )
    command = " ".join(["troupe", "config", "set", *(shlex.quote(a) for a in assignments)])
    return f"Move it in one change{note}: {command}"


def _runtime_problems(
    base: tuple[str, ...], actor: Mapping[str, Any], known: Shapes
) -> list[Problem]:
    """Whether the actor's runtime exists and fits its runner, and its model has a runtime (spec:
    runtimes, "An actor names its runtime and may set its model", "An actor's runtime fits its
    runner"). A runtime it could name is listed only when it fits its runner."""
    at = (*base, "runtime")
    runtime = actor.get("runtime")
    runner = actor.get("runner")
    entry = interim.RUNNERS.get(runner) if isinstance(runner, str) else None
    takes = entry.runtime if entry is not None else None
    fit = entry.fit if entry is not None else interim.RuntimeFit()
    # A runtime with problems of its own (no shape) is never offered: config would refuse it.
    fits = [
        name
        for name, shape in sorted(known.items())
        if shape is not None
        and not runtimes.unfit(fit, shape.endpoint.value, shape.credential is not None)
    ]
    define = (
        f"troupe config set {shown((RUNTIMES, '<name>', 'endpoint'))}=<url>, with "
        f"{runtimes.fitting(fit)}"
    )
    if runtime is None:
        if takes == "required":
            if not fits:
                return [
                    Problem(
                        at,
                        f"the {runner} runner needs a runtime, and no runtime there is fits the "
                        f"{runner} runner",
                        f"Define one that fits with {define}, then set {shown(at)} to it.",
                    )
                ]
            return [
                Problem(
                    at,
                    f"the {runner} runner needs a runtime (these fit it: {', '.join(fits)})",
                    f"Set {shown(at)} to one of: {', '.join(fits)}.",
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
        there_are = (
            "there are"
            if fit == interim.RuntimeFit()
            else f"there are, that fit the {runner} runner"
        )
        listed = ", ".join(fits) or "none"
        return [
            Problem(
                at,
                f"there's no runtime named {runtime!r} ({there_are}: {listed})",
                (
                    f"Set it to one of: {', '.join(fits)}, or define it with "
                    if fits
                    else "Define it with "
                )
                + f"troupe config set {shown((RUNTIMES, str(runtime), 'endpoint'))}=<url>.",
                related=((RUNTIMES, str(runtime)),),
            )
        ]
    shape = known[runtime]
    if shape is None:
        return []  # the runtime's own problems are reported
    reasons = runtimes.unfit(fit, shape.endpoint.value, shape.credential is not None)
    if not reasons:
        return []
    why = "; and ".join(runtimes.unfit_words(str(runner), runtime, reason) for reason in reasons)
    fix = (
        f"Set {shown(at)} to one that fits: {', '.join(fits)}, or define one with {define}."
        if fits
        else f"Define one that fits with {define}, then set {shown(at)} to it."
    )
    return [Problem(at, why, fix, related=((RUNTIMES, runtime),))]


def _schema_problems(
    base: tuple[str, ...],
    value: object,
    validator: jsonschema.Draft202012Validator,
    *,
    runner: str | None = None,
    against: str = "actor",
    typed: Typed = None,
    known: Collection[str] = (),
) -> list[Problem]:
    against = f"the {runner} runner's options schema" if runner else f"the {against} schema"
    found: list[Problem] = []
    for error in sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path)):
        path = (*base, *(str(part) for part in error.absolute_path))
        if error.validator == "additionalProperties" and isinstance(error.instance, Mapping):
            allowed = set(error.schema.get("properties", {}))
            extras = sorted(set(error.instance) - allowed)
            # A key troupe itself names (an option a runner moved) is its words, not the person's.
            hidden = [
                extra for extra in extras if extra not in known and _in_value((*path, extra), typed)
            ]
            if hidden:
                # Keys from inside the value: named by where the value was set, never themselves.
                fields = ", ".join(sorted(allowed)) or "none"
                found.append(
                    Problem(
                        path,
                        f"it holds {len(hidden)} field{'' if len(hidden) == 1 else 's'} {against} "
                        f"doesn't define (it defines: {fields})",
                        f"Set {shown(path)} with only the fields {against} defines.",
                    )
                )
            for extra in (extra for extra in extras if extra not in hidden):
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
    be meant is refused"): the list it's in, its position and the rule, never the pattern, which is
    refused for its shape and may hold a password (config-set-json-redacts design D5)."""
    if error.validator not in ("pattern", "minLength") or not isinstance(error.instance, str):
        return None
    if len(path) < 5 or path[2] != EFFECTS:
        return None
    where = shown(path[:4])
    item = f"item {int(path[4]) + 1}" if path[4].isdigit() else "a pattern"
    try:
        pattern_regex(error.instance, where)
    except PatternError as refused:
        rule = f"{item} {refused.rule}"
    else:  # the schema refused what the SDK accepts: a bug, but say what's known
        rule = f"{item} isn't a pattern the actor schema accepts"
    if error.instance.startswith("/"):
        rule += ". Runs get a scratch directory for temporary files without declaring it"
    return Problem(path[:4], rule, f"Change or remove {item} of {where}.")


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
    """What ``error`` says, in words: the schema's own description where it has one. Never the
    value refused: jsonschema's own messages start with it, and it may hold a password (spec:
    config, "A refused config value is repeated nowhere"; config-set-json-redacts design D4)."""
    if error.validator == "type":
        wanted: object = error.validator_value
        if isinstance(wanted, str):
            names = [wanted]
        else:
            names = [str(n) for n in wanted] if isinstance(wanted, list) else []
        actual = JSON_TYPES.get(type(error.instance), "a value")
        return f"it must be {' or '.join(_article(n) for n in names)}, not {actual} ({against})"
    description = error.schema.get("description") if isinstance(error.schema, Mapping) else None
    if error.validator in ("pattern", "oneOf", "anyOf", "const", "not") and description:
        return f"it doesn't fit {against}: {description}"
    return f"{_words(str(error.validator), error.validator_value)} ({against})"


WORDED = frozenset(
    {
        "type",
        "enum",
        "const",
        "minLength",
        "maxLength",
        "minimum",
        "exclusiveMinimum",
        "maximum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
        "uniqueItems",
        "pattern",
        "not",
        "oneOf",
        "anyOf",
        "dependentRequired",
    }
)
"""The validators ``_rule`` has words of its own for. Any other gives "it breaks the schema's
<validator> rule", which says less; a test fails when a config or options schema uses one that
isn't here, or isn't handled before ``_rule`` (additionalProperties, required)."""


def _words(validator: str, value: object) -> str:
    """``validator``'s rule, from the schema's value for it: never the instance."""
    number = value if isinstance(value, int | float) and not isinstance(value, bool) else None
    match validator:
        case "enum" if isinstance(value, list):
            return f"it must be one of {', '.join(repr(v) for v in value)}"
        case "const":
            return f"it must be {value!r}"
        case "minLength" if number == 1:
            return "it can't be empty"
        case "minLength" if number is not None:
            return f"it must be at least {number} characters"
        case "maxLength" if number is not None:
            return f"it must be at most {number} characters"
        case "minimum" if number is not None:
            return f"it must be at least {number}"
        case "exclusiveMinimum" if number is not None:
            return f"it must be more than {number}"
        case "maximum" if number is not None:
            return f"it must be at most {number}"
        case "exclusiveMaximum" if number is not None:
            return f"it must be less than {number}"
        case "minItems" if number is not None:
            return f"it must hold at least {number} item{'' if number == 1 else 's'}"
        case "maxItems" if number is not None:
            return f"it must hold at most {number} item{'' if number == 1 else 's'}"
        case "minProperties" if number is not None:
            return f"it must hold at least {number} field{'' if number == 1 else 's'}"
        case "maxProperties" if number is not None:
            return f"it must hold at most {number} field{'' if number == 1 else 's'}"
        case "uniqueItems":
            return "its items must all differ"
        case "pattern":
            return f"it must match the pattern {value}"
        case "not" if isinstance(value, Mapping) and isinstance(value.get("required"), list):
            return f"it can't have {' and '.join(str(k) for k in value['required'])} together"
        case "dependentRequired" if isinstance(value, Mapping):
            needs = "; ".join(
                f"{key} needs {', '.join(str(n) for n in needed)}"
                for key, needed in value.items()
                if isinstance(needed, list)
            )
            return f"some fields need others with them: {needs}"
        case "not" | "oneOf" | "anyOf":
            return "it doesn't fit any shape the schema allows"
    return f"it breaks the schema's {validator} rule"


def _article(json_type: str) -> str:
    return {"object": "a group", "array": "a list", "integer": "a whole number"}.get(
        json_type, f"a {json_type}"
    )


def check(config: Mapping[str, Any], touched: Collection[str] = (), typed: Typed = None) -> None:
    """Refuse ``config`` with ``config.invalid`` when it breaks any rule, naming the first, and with
    runner.not-installed when a ``touched`` actor's runner isn't installed (see ``problems``).
    ``typed`` are the paths the change's person typed: a key from inside a value isn't repeated."""
    _refuse(problems(config, touched, typed))


def check_actor(name: str, config: Mapping[str, Any]) -> None:
    """Refuse the actor ``name`` in ``config`` with ``config.invalid`` when it breaks any rule,
    naming the first: what perform checks, so an actor recorded before a rule was tightened can't
    run (spec: effects, "Every expected file is covered by the declaration")."""
    _refuse(actor_problems(name, config[ACTORS][name], runtime_shapes(config)))


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

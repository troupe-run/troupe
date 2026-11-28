"""Reading a config file's values (spec: config-hand-edits; hand-edit-sweep design D2, D4).

Each kind of config file owns part of config: an actor's ``.yaml`` every field of
``actors.<name>`` but its character, its ``.md`` the character (the whole text), and a runtime's
``.yaml`` every field of ``runtimes.<name>``. Reading gives those values, or refuses the file with
``config.file-invalid``: a file that doesn't parse, that YAML could read in more than one way
(anchors, aliases, tags, merge keys), that holds something config never holds (a null, a date, a
number JSON can't write), or that is present and holds no values. A present file with no values is
never a removal (the mid-save guard): removal is only by deleting the file.

A refusal names the file and the rule, and never repeats a value from the file.
"""

import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from troupe.core import defaults
from troupe.core.config.kinds import ACTORS, CHARACTER, FLOWS, RUNTIMES, file_kind
from troupe.core.config_paths import shown as shown_path
from troupe.core.errors import TroupeError
from troupe.core.files import read_file
from troupe.core.theatre import THEATRE_DIR
from troupe.platform.files import FileStamp, file_stamp

if TYPE_CHECKING:  # loaded only where a file is read: it's slow to load (cli-starts-fast)
    from ruamel.yaml import YAML

SCHEMA_KEY = "$schema"


@dataclass(frozen=True)
class FileValues:
    """What a config file holds: the group it belongs to, the part of it the file owns, and the
    values."""

    path: str
    """The file, relative to .troupe/."""
    group: tuple[str, str]
    """The group the file belongs to, such as ``("actors", "tester")``."""
    owns: Literal["fields", "character"]
    values: dict[str, Any]
    """The values the file owns, by key: every field for a ``fields`` file, and ``character``
    alone for a character file."""


def owner(path: str) -> tuple[tuple[str, str], Literal["fields", "character"]] | None:
    """The group and part a config file at ``path`` owns, or None when it isn't a config file."""
    kind = file_kind(path)
    if kind is None:
        return None
    name = path.rsplit("/", 1)[1].rsplit(".", 1)[0]
    holds: Literal["fields", "character"] = "character" if kind.holds == CHARACTER else "fields"
    return (kind.kind, name), holds


def owned(path: str, group: Mapping[str, Any]) -> dict[str, Any]:
    """The values of ``group`` (an actor or a runtime as config holds it) that the file at
    ``path`` owns."""
    found = owner(path)
    if found is None:
        raise ValueError(f"{path} is no kind of config file")
    _, holds = found
    if holds == "character":
        return {CHARACTER: group[CHARACTER]} if CHARACTER in group else {}
    return {key: value for key, value in group.items() if key != CHARACTER}


def read_values(path: str, data: bytes, where: Path | None = None) -> FileValues:
    """The values the config file at ``path`` (relative to .troupe/) holds, given its bytes.
    ``where`` is the file's absolute path, named in a refusal. Refuses the file with
    ``config.file-invalid`` (see the module's docstring)."""
    try:
        return _read(path, data)
    except TroupeError as error:
        if where is not None and error.code == "config.file-invalid":
            error.path = str(where)
        raise


def _read(path: str, data: bytes) -> FileValues:
    found = owner(path)
    if found is None:
        raise ValueError(f"{path} is no kind of config file")
    group, holds = found
    if not data:
        what = "the character" if holds == "character" else _removes(group)
        raise invalid(
            path,
            "empty",
            "it's empty, so troupe can't tell an edit from a file part-way through being saved",
            f"Finish saving it, or delete the file to remove {what}.",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise invalid(
            path,
            "not-utf-8",
            f"it isn't UTF-8 text (byte {error.start + 1} can't be read)",
            "Save it as UTF-8.",
        ) from error
    if holds == "character":
        return FileValues(path, group, holds, {CHARACTER: text})
    values = _yaml_values(path, text, group)
    return FileValues(path, group, holds, values)


_KIND_WORD = {ACTORS: "actor", RUNTIMES: "runtime", FLOWS: "flow"}
"""Each kind of config file by the word for one of its entities, as a refusal names it."""


def _removes(group: tuple[str, str]) -> str:
    kind, name = group
    return f"the {_KIND_WORD[kind]} {name}"


def invalid(
    path: str,
    rule: str,
    problem: str,
    fix: str,
    *,
    line: int | None = None,
    column: int | None = None,
    at: tuple[str, ...] | None = None,
) -> TroupeError:
    """``config.file-invalid`` for the config file at ``path``, breaking ``rule``."""
    shown = f"{THEATRE_DIR}/{path}"
    details: dict[str, Any] = {"file": shown, "rule": rule}
    if line is not None:
        details["line"] = line
    if column is not None:
        details["column"] = column
    if at is not None:
        details["path"] = list(at)
    where = f" (line {line}, column {column})" if line is not None and column is not None else ""
    return TroupeError(
        "config.file-invalid",
        problem=f"{shown}{where}: {problem}. Nothing was recorded from any config file.",
        fix=fix
        + " Or run troupe sync --force to replace it with what config says, keeping a copy.",
        details=details,
    )


@cache
def _yaml() -> "YAML":
    from ruamel.yaml import YAML

    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    return yaml


_SCHEMA_PATTERN = {
    ACTORS: re.compile(r"(^|/)config/actor\.schema\.json$"),
    RUNTIMES: re.compile(r"(^|/)config/runtime\.schema\.json$"),
    FLOWS: re.compile(r"(^|/)config/flow\.schema\.json$"),
}


def _yaml_values(path: str, text: str, group: tuple[str, str]) -> dict[str, Any]:
    from ruamel.yaml.error import MarkedYAMLError, YAMLError

    yaml = _yaml()
    try:
        _check_events(path, yaml, text)
        loaded = yaml.load(text)
    except TroupeError:
        raise
    except MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        rule = "duplicate-key" if type(error).__name__ == "DuplicateKeyError" else "syntax"
        problem = (
            "a key appears twice in one group"
            if rule == "duplicate-key"
            else f"it isn't valid YAML ({error.problem or 'it stopped making sense'})"
        )
        raise invalid(
            path,
            rule,
            problem,
            "Fix the YAML at that line.",
            line=mark.line + 1 if mark is not None else None,
            column=mark.column + 1 if mark is not None else None,
        ) from None
    except YAMLError:
        raise invalid(path, "syntax", "it isn't valid YAML", "Fix the YAML.") from None
    if loaded is None:
        raise invalid(
            path,
            "empty",
            "it holds no values, so troupe can't tell an edit from a file part-way through "
            "being saved",
            f"Finish saving it, or delete the file to remove {_removes(group)}.",
        )
    if not isinstance(loaded, dict):
        raise invalid(
            path,
            "not-a-mapping",
            "its top level must be a group of keys and values",
            "Write it as `key: value` lines.",
        )
    _check_values(path, loaded, ())
    kind = group[0]
    if SCHEMA_KEY in loaded:
        schema = loaded.pop(SCHEMA_KEY)
        if not isinstance(schema, str) or not _SCHEMA_PATTERN[kind].search(schema):
            wanted = _KIND_WORD[kind]
            raise invalid(
                path,
                "schema-url",
                f"its {SCHEMA_KEY} must name the {wanted} schema",
                f"Set {SCHEMA_KEY} to the {wanted} schema's URL, as troupe writes it, or remove "
                "the key.",
                at=(SCHEMA_KEY,),
            )
    if not loaded:
        raise invalid(
            path,
            "empty",
            "it holds no values, so troupe can't tell an edit from a file part-way through "
            "being saved",
            f"Finish saving it, or delete the file to remove {_removes(group)}.",
        )
    return loaded


def _check_events(path: str, yaml: "YAML", text: str) -> None:
    """Refuse YAML that could be read in more than one way: anchors, aliases, explicit tags and
    merge keys. Config is plain values, so each file has one reading."""
    from ruamel.yaml.events import (
        AliasEvent,
        CollectionStartEvent,
        NodeEvent,
        ScalarEvent,
    )

    for event in yaml.parse(text):
        mark = event.start_mark
        line, column = mark.line + 1, mark.column + 1
        if isinstance(event, AliasEvent) or (
            isinstance(event, NodeEvent) and event.anchor is not None
        ):
            raise invalid(
                path,
                "anchor",
                "it uses a YAML anchor or alias, which config files don't support",
                "Write each value out where it's used.",
                line=line,
                column=column,
            )
        explicit_tag = (
            isinstance(event, ScalarEvent) and event.tag is not None and not any(event.implicit)
        ) or (
            isinstance(event, CollectionStartEvent) and event.tag is not None and not event.implicit
        )
        if explicit_tag:
            raise invalid(
                path,
                "tag",
                "it uses a YAML tag, which config files don't support",
                "Remove the tag: each field's type comes from the schema.",
                line=line,
                column=column,
            )
        if isinstance(event, ScalarEvent) and event.value == "<<" and event.style is None:
            raise invalid(
                path,
                "merge-key",
                "it uses a YAML merge key (<<), which config files don't support",
                "Write each value out where it's used.",
                line=line,
                column=column,
            )


def _check_values(path: str, node: object, at: tuple[str, ...]) -> None:
    """Refuse what config never holds: a null, a key that isn't text, a date, or a number JSON
    can't write. Names where, never the value."""
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                raise invalid(
                    path,
                    "key-not-text",
                    f"a key under {_where(at)} isn't text",
                    "Quote the key.",
                    at=at,
                )
            _check_values(path, value, (*at, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _check_values(path, item, (*at, str(index)))
    elif node is None:
        raise invalid(
            path,
            "null",
            f"{_where(at)} is empty (null), and config never holds null",
            "Give it a value, or remove the key to unset it.",
            at=at,
        )
    elif isinstance(node, bool | int | str):
        return
    elif isinstance(node, float):
        if not math.isfinite(node):
            raise invalid(
                path,
                "not-json",
                f"{_where(at)} is a number JSON can't hold (infinite or not a number)",
                "Give it a finite number.",
                at=at,
            )
    else:
        raise invalid(
            path,
            "not-json",
            f"{_where(at)} is a {type(node).__name__}, which config doesn't hold",
            "Quote it, if it's meant as text.",
            at=at,
        )


def _where(at: tuple[str, ...]) -> str:
    return shown_path(at) if at else "the top level"


def _file_for(path: tuple[str, ...], reads: Sequence[FileValues]) -> FileValues | None:
    """The read file a problem at ``path`` lies in: the file that owns the value (the fields file
    for a problem with the whole group), or any read file of the group when that one wasn't
    read."""
    in_group = [r for r in reads if tuple(path[:2]) == r.group]
    if not in_group:
        return None
    holds = "character" if len(path) > 2 and path[2] == CHARACTER else "fields"
    return next((r for r in in_group if r.owns == holds), in_group[0])


def refuse_file_problems(
    reads: Sequence[FileValues], after: Mapping[str, Any], where: Path | None = None
) -> None:
    """Refuse with ``config.file-invalid`` when the config the read files make, ``after``, breaks
    a rule in a value one of them holds: the checks troupe config set runs, the kind's schema and
    an actor's runner's options schema (design D2). ``where`` is the theatre's .troupe/ directory.
    A problem elsewhere is left for the check every change gets."""
    from troupe.core.config.kinds import problems

    actors = after.get(ACTORS)
    touched = {r.group[1] for r in reads if r.group[0] == ACTORS}
    if isinstance(actors, Mapping):
        touched &= set(actors)
    for problem in problems(after, touched, None):
        read = _file_for(problem.path, reads)
        if read is None:
            continue
        error = invalid(
            read.path,
            "invalid",
            f"{shown_path(problem.path)}: {problem.rule}",
            "Correct it in the file.",
            at=problem.path,
        )
        if where is not None:
            error.path = str(where / read.path)
        raise error


def read_steady(
    troupe_dir: Path,
    path: str,
    *,
    attempts: int = defaults.CONFIG_READ_ATTEMPTS,
    pause: float = defaults.CONFIG_READ_RETRY_SECONDS,
    stamp: Callable[[Path], FileStamp | None] = file_stamp,
    read: Callable[[Path], bytes] = read_file,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes | None:
    """The bytes of the config file at ``path`` (relative to ``troupe_dir``), or None when there's
    no file, read so that the file was the same before and after (design D4). A file that changes
    while it's read is read again, up to ``attempts`` times, then refused with
    ``config.file-changing``."""
    target = troupe_dir / path
    for attempt in range(attempts):
        if attempt:
            sleep(pause)
        before = stamp(target)
        if before is None:
            return None
        try:
            data = read(target)
        except FileNotFoundError:
            continue
        if stamp(target) == before:
            return data
    raise changing(troupe_dir, path)


def changing(troupe_dir: Path, path: str) -> TroupeError:
    """``config.file-changing`` for the config file at ``path``."""
    shown = f"{THEATRE_DIR}/{path}"
    return TroupeError(
        "config.file-changing",
        problem=f"{shown} changed while troupe was reading or writing it, so troupe can't tell "
        "what it holds. Nothing was recorded.",
        fix="Finish saving the file, then run the command again.",
        path=str(troupe_dir / path),
        details={"file": shown},
    )

"""Config's files under .troupe/: rendering them, and making them what config says (spec:
config-files; config-model design D7, D8, D9).

troupe writes each config file whole from config and never reads one for its meaning. Before
replacing or removing a file, it checks that the file is one troupe wrote:

- what troupe would write now from config, or
- a version whose hash a ``Config.Changed`` recorded for that path, on any line of history, or
  this clone's own record of files flush wrote (``.troupe/local/config/written.jsonl``), or
- no file at all: a file deleted by hand is written again.

Anything else is a person's, and is refused (``config.file-not-troupes``) unless forced, when its
bytes are kept in the artifact store first. A new file is written whole beside its target as
``.<name>.troupe~`` and moved into place with an atomic replace, so a reader sees the old file or
the new one; a staged file an event vouches for is a write a crash cut short, and is finished.
"""

import hashlib
import io
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.resolver import VersionedResolver

from troupe.core import defaults, strict_json
from troupe.core.artifacts import load_store
from troupe.core.config.kinds import (
    ACTOR_SCHEMA_URL,
    ACTORS,
    CHARACTER,
    CONFIG_DIRECTORIES,
    OPERATING_SYSTEM_FILES,
    actor_files,
    file_kind,
    staged_name,
    staged_target,
)
from troupe.core.errors import TroupeError
from troupe.core.files import directory_lock, read_file, replace_file
from troupe.core.notices import Notice
from troupe.core.theatre import THEATRE_DIR, ensure_git_files
from troupe.platform.files import WaitCallback, append_bytes

FIELD_ORDER = ("$schema", "runner", "options", "expect")
"""The actor file's keys, in its schema's order."""

WRITTEN = "local/config/written.jsonl"
LOCK = "local/config"

_STRING = "tag:yaml.org,2002:str"
_YAML_1_1 = VersionedResolver(version=(1, 1))


def file_hash(data: bytes) -> str:
    """``sha256:`` and the SHA-256 of a file's bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


# Rendering.


def _represent_string(representer: RoundTripRepresenter, value: str) -> Any:  # noqa: ANN401
    # Every string reads back the same in every editor, not only under YAML 1.2: one holding a
    # character that isn't printable (a control character, or NEL, which YAML 1.1 reads as a line
    # break) is double-quoted, so it's escaped; one a YAML 1.1 reader would take as something else
    # (yes, on, ~, 012) is single-quoted.
    style: str | None = None
    if not value.isprintable():
        style = '"'
    elif _YAML_1_1.resolve(ScalarNode, value, (True, False)) != _STRING:
        style = "'"
    return representer.represent_scalar(_STRING, value, style=style)


def _represent_float(representer: RoundTripRepresenter, value: float) -> Any:  # noqa: ANN401
    # Python's shortest round-trip form, with a dot in the mantissa, since a YAML 1.1 float needs
    # one (1e-05 would read back as a string there). Config never holds NaN or Infinity.
    text = repr(value)
    mantissa, exponent, power = text.partition("e")
    if "." not in mantissa:
        mantissa += ".0"
    return representer.represent_scalar("tag:yaml.org,2002:float", mantissa + exponent + power)


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.representer.add_representer(str, _represent_string)
    yaml.representer.add_representer(float, _represent_float)
    return yaml


def _sorted(value: object) -> object:
    """``value`` with every group's keys sorted, so a file depends only on what config holds, never
    on the order its values were set in (replaying history sets them in another order)."""
    if isinstance(value, Mapping):
        return {key: _sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted(item) for item in value]
    return value


def render_actor(actor: Mapping[str, Any]) -> dict[str, bytes]:
    """An actor's files, by their names (``<name>.yaml``, and ``<name>.md`` for a character)."""
    fields: dict[str, Any] = {"$schema": ACTOR_SCHEMA_URL}
    for key in FIELD_ORDER[1:]:
        if key in actor:
            fields[key] = _sorted(actor[key])
    text = io.StringIO()
    text.write(f"# yaml-language-server: $schema={ACTOR_SCHEMA_URL}\n")
    _yaml().dump(fields, text)
    files = {"yaml": text.getvalue().encode("utf-8")}
    character = actor.get(CHARACTER)
    if isinstance(character, str):
        files["md"] = character.encode("utf-8")
    return files


def render(config: Mapping[str, Any]) -> dict[str, bytes]:
    """Every config file config makes, by its path relative to .troupe/."""
    files: dict[str, bytes] = {}
    actors = config.get(ACTORS, {})
    for name, actor in sorted(actors.items() if isinstance(actors, Mapping) else []):
        if not isinstance(actor, Mapping):
            continue
        yaml_path, md_path = actor_files(name)
        rendered = render_actor(actor)
        files[yaml_path] = rendered["yaml"]
        if "md" in rendered:
            files[md_path] = rendered["md"]
    return files


# What's on disk.


@dataclass(frozen=True)
class OnDisk:
    """The config directories' files, staged writes and anything else in them."""

    files: dict[str, bytes]
    staged: dict[str, bytes]
    unknown: tuple[str, ...]


def on_disk(troupe_dir: Path) -> OnDisk:
    files: dict[str, bytes] = {}
    staged: dict[str, bytes] = {}
    unknown: list[str] = []
    for directory in CONFIG_DIRECTORIES:
        root = troupe_dir / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_dir() or path.name in OPERATING_SYSTEM_FILES:
                continue
            relative = path.relative_to(troupe_dir).as_posix()
            if staged_target(relative) is not None:
                staged[relative] = read_file(path)
            elif file_kind(relative) is not None:
                files[relative] = read_file(path)
            else:
                unknown.append(relative)
    return OnDisk(files, staged, tuple(unknown))


def written_by_flush(troupe_dir: Path) -> dict[str, frozenset[str]]:
    """This clone's record of the files flush wrote with no event, by path. A torn last line, an
    interrupted append, is left out."""
    path = troupe_dir / WRITTEN
    if not path.is_file():
        return {}
    found: dict[str, set[str]] = {}
    lines = path.read_bytes().split(b"\n")
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = strict_json.loads(line)
            if not isinstance(record, dict):
                raise strict_json.StrictJSONError("not an object")
            found.setdefault(str(record["path"]), set()).add(str(record["hash"]))
        except (strict_json.StrictJSONError, KeyError) as error:
            if number == len(lines) or (number == len(lines) - 1 and not lines[-1]):
                continue  # the last line, torn by an interrupted append
            raise TroupeError(
                "config.local-malformed",
                problem=f"Line {number} of troupe's record of the config files it wrote is "
                f"malformed ({error}).",
                fix="Delete the file: it's this clone's own, and troupe starts it again.",
                path=str(path),
            ) from error
    return {key: frozenset(value) for key, value in found.items()}


# Is a file safe to replace? (design D8)


@dataclass(frozen=True)
class Action:
    """What flushing does to one file."""

    path: str
    action: str
    """``write``, ``remove``, ``finish`` (a staged write an event vouches for), ``discard`` (a
    staged write no event vouches for), or ``refuse``."""
    reason: str
    data: bytes | None = None
    forced: bool = False


@dataclass(frozen=True)
class Plan:
    actions: tuple[Action, ...] = ()
    unknown: tuple[str, ...] = ()

    @property
    def refused(self) -> tuple[Action, ...]:
        return tuple(a for a in self.actions if a.action == "refuse")

    @property
    def changes(self) -> tuple[Action, ...]:
        return tuple(a for a in self.actions if a.action != "refuse")


def _troupes(path: str, data: bytes, recorded: Mapping[str, frozenset[str]]) -> bool:
    return file_hash(data) in recorded.get(path, frozenset())


def plan(
    troupe_dir: Path,
    rendered: Mapping[str, bytes],
    recorded: Mapping[str, frozenset[str]],
    *,
    force: bool = False,
) -> Plan:
    """What making the files exactly ``rendered`` takes, and what it would have to refuse.
    ``recorded`` is every hash an event recorded for each path."""
    disk = on_disk(troupe_dir)
    known = {
        path: recorded.get(path, frozenset()) | written
        for path, written in written_by_flush(troupe_dir).items()
    }
    vouched = {**recorded, **known}
    actions: list[Action] = []
    for staged, data in sorted(disk.staged.items()):
        target = staged_target(staged) or staged
        if _troupes(target, data, vouched) and rendered.get(target) == data:
            actions.append(Action(staged, "finish", "a write troupe recorded and didn't finish"))
        else:
            actions.append(Action(staged, "discard", "a write troupe staged but never recorded"))
    finishing = {staged_target(a.path) for a in actions if a.action == "finish"}
    for path in sorted(rendered.keys() | disk.files.keys()):
        want, have = rendered.get(path), disk.files.get(path)
        if want == have or path in finishing:
            continue
        if have is None:
            reason = "config holds it, and it was missing" if path in vouched else "new"
            actions.append(Action(path, "write", reason, want))
            continue
        action = "write" if want is not None else "remove"
        if _troupes(path, have, vouched):
            actions.append(Action(path, action, "an older version troupe wrote", want))
        elif force:
            actions.append(
                Action(path, action, "forced past a file troupe didn't write", want, True)
            )
        elif _MARKERS.search(have):
            actions.append(Action(path, "refuse", CONFLICTED, want))
        else:
            actions.append(Action(path, "refuse", "troupe didn't write it", want))
    return Plan(tuple(actions), disk.unknown)


CONFLICTED = "git left it conflicted"
_MARKERS = re.compile(rb"^<<<<<<< .*^=======\r?$.*^>>>>>>> ", re.MULTILINE | re.DOTALL)
"""git's conflict markers, as a merge leaves them in a file both branches changed."""


def refuse(plan_: Plan) -> None:
    """Refuse a plan that would replace a file troupe didn't write, or that met unknown files."""
    if plan_.unknown:
        listed = ", ".join(f".troupe/{p}" for p in plan_.unknown)
        raise TroupeError(
            "config.unknown-file",
            problem=f"{listed}: no kind of config file is named like this, so troupe doesn't "
            "know what it is.",
            fix="Move it out of .troupe/, or delete it. Config files are written by troupe "
            "config set; an actor is actors/<name>.yaml, with actors/<name>.md for its character.",
            path=f"{THEATRE_DIR}/{plan_.unknown[0]}",
            details={"paths": [f"{THEATRE_DIR}/{p}" for p in plan_.unknown]},
        )
    conflicted = [a for a in plan_.refused if a.reason == CONFLICTED]
    if conflicted:
        listed = ", ".join(f".troupe/{a.path}" for a in conflicted)
        raise TroupeError(
            "config.file-not-troupes",
            problem=f"{listed} has git's conflict markers in it, from merging branches that "
            "changed it, so it isn't what troupe wrote and troupe won't replace it. troupe "
            "doesn't resolve this for you yet (#141).",
            fix=f"Take one side's file (git checkout --ours {listed}), then run troupe config "
            "get to see any config conflict and resolve it with one troupe config set. Then git "
            "add the file and commit the merge.",
            path=f"{THEATRE_DIR}/{conflicted[0].path}",
            details={"paths": [f"{THEATRE_DIR}/{a.path}" for a in conflicted]},
        )
    if plan_.refused:
        listed = ", ".join(f".troupe/{a.path}" for a in plan_.refused)
        raise TroupeError(
            "config.file-not-troupes",
            problem=f"{listed} isn't what troupe wrote, so troupe won't replace it: it can't read "
            "hand edits back yet (#119), and replacing it would lose them.",
            fix="Undo the edit (git restore the file), then make the change with troupe config "
            "set. Or run troupe flush --force to replace it, keeping a copy of what it held.",
            path=f"{THEATRE_DIR}/{plan_.refused[0].path}",
            details={"paths": [f"{THEATRE_DIR}/{a.path}" for a in plan_.refused]},
        )


# Writing (design D9).


@contextmanager
def locked(troupe_dir: Path, on_wait: WaitCallback | None = None) -> Iterator[None]:
    """Hold the config files' lock, so flushes and config writes in two terminals queue. A wait
    is announced through ``on_wait`` once it lasts, and gives up after the lock timeout."""
    lock = troupe_dir / LOCK
    lock.mkdir(parents=True, exist_ok=True)
    with directory_lock(lock, on_wait=on_wait):
        yield


def stage(troupe_dir: Path, path: str, data: bytes) -> None:
    """Write ``data`` whole beside ``path``'s target, ready to move into place."""
    target = troupe_dir / staged_name(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    replace_file(target, data)


def finish(troupe_dir: Path, path: str) -> None:
    """Move the staged ``path`` into place, atomically."""
    staged = troupe_dir / staged_name(path)
    replace_file(troupe_dir / path, staged.read_bytes())
    staged.unlink()


def remove(troupe_dir: Path, path: str) -> None:
    (troupe_dir / path).unlink(missing_ok=True)
    parent = (troupe_dir / path).parent
    if parent != troupe_dir and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()


@dataclass(frozen=True)
class Flushed:
    """What a flush did, or would do."""

    actions: tuple[Action, ...]
    kept: dict[str, str] = field(default_factory=dict)
    """Each file forced past, and the artifact its bytes were kept under."""

    def notices(self) -> list[Notice]:
        return [
            Notice(
                "config.file-rewritten",
                problem=f".troupe/{a.path}: {a.reason}, so troupe wrote it again from config.",
                fix="Nothing to do: config is unchanged.",
                path=f"{THEATRE_DIR}/{a.path}",
                details={"reason": a.reason},
            )
            for a in self.actions
            if a.action in ("write", "remove") and a.reason != "new" and not a.forced
        ]


def flush(
    theatre: Path,
    config: Mapping[str, Any],
    recorded: Mapping[str, frozenset[str]],
    *,
    force: bool = False,
    rehearse: bool = False,
    on_wait: WaitCallback | None = None,
) -> Flushed:
    """Make the config files exactly what ``config`` says. Refused, writing nothing, when it would
    replace a file troupe didn't write (unless ``force``), or meets an unknown file. With
    ``rehearse``, works out what it would do and does none of it."""
    troupe_dir = theatre / THEATRE_DIR
    rendered = render(config)
    plan_ = plan(troupe_dir, rendered, recorded, force=force)
    refuse(plan_)
    if rehearse or not plan_.changes:
        return Flushed(plan_.changes)
    with locked(troupe_dir, on_wait):
        plan_ = plan(troupe_dir, rendered, recorded, force=force)  # again, now nothing can move
        refuse(plan_)
        kept = execute(troupe_dir, plan_)
    return Flushed(plan_.changes, kept)


def execute(troupe_dir: Path, plan_: Plan) -> dict[str, str]:
    """Carry out ``plan_``, holding the lock: each new file staged then moved into place. Returns
    each file forced past, and the artifact its bytes were kept under."""
    ensure_git_files(troupe_dir)
    kept: dict[str, str] = {}
    written: list[dict[str, str]] = []
    for action in plan_.changes:
        target = troupe_dir / action.path
        if action.forced and target.exists():
            store = load_store(defaults.ARTIFACT_STORE, troupe_dir / "local" / "artifacts")
            kept[action.path] = store.put(target.read_bytes())
        if action.action == "finish":
            finish(troupe_dir, staged_target(action.path) or action.path)
        elif action.action == "discard":
            (troupe_dir / action.path).unlink(missing_ok=True)
        elif action.action == "write" and action.data is not None:
            stage(troupe_dir, action.path, action.data)
            finish(troupe_dir, action.path)
            written.append({"path": action.path, "hash": file_hash(action.data)})
        elif action.action == "remove":
            remove(troupe_dir, action.path)
    _record_written(troupe_dir, written)
    return kept


def _record_written(troupe_dir: Path, written: Sequence[dict[str, str]]) -> None:
    if not written:
        return
    path = troupe_dir / WRITTEN
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(strict_json.dumps(w) + "\n" for w in written)
    append_bytes(path, lines.encode("utf-8"))

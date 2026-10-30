"""Config's files under .troupe/: rendering them, and making them what config says (spec:
config-files; config-model design D7, D8, D9).

troupe writes each config file whole from config and never reads one for its meaning. Before
replacing or removing a file, it checks that the file is one troupe wrote:

- what troupe would write now from config, or
- a version whose hash a ``Config.Changed`` recorded for that path, on any line of history, or
  this clone's own record of files flush wrote (``.troupe/local/config/written.jsonl``), or
- no file at all: a file deleted by hand is written again.

A file git merged from versions troupe wrote also counts, when the VCS reports it conflicted or
cleanly merged and every side it came from is one of the above (config-projection-conflicts design
D4). Only a command that asks to resolve it (``resolve``: troupe flush, or the config set whose
change writes it) replaces it, keeping its bytes in the artifact store first; any other command
refuses it, naming troupe flush, so a file being resolved by hand never changes under its editor.
With the setting mark_merges_resolved on, each such file git left unmerged that a command rewrites
is also marked resolved in git's index, staging exactly what troupe wrote (mark-config-resolved
design D3, D6).

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
from typing import Any, Literal, Protocol

from ruamel.yaml import YAML
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.resolver import VersionedResolver

from troupe.core import defaults, policy, settings, strict_json
from troupe.core.artifacts import load_store
from troupe.core.config.kinds import (
    ACTORS,
    CHARACTER,
    CONFIG_DIRECTORIES,
    OPERATING_SYSTEM_FILES,
    actor_files,
    actor_schema_url,
    file_kind,
    staged_name,
    staged_target,
)
from troupe.core.errors import TroupeError
from troupe.core.files import directory_lock, read_file, replace_file
from troupe.core.notices import Notice
from troupe.core.settings import Marking
from troupe.core.theatre import THEATRE_DIR, ensure_git_files
from troupe.core.vcs import Marked, MergeSides, Resolve, Unmarked
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
    url = actor_schema_url()
    fields: dict[str, Any] = {"$schema": url}
    for key in FIELD_ORDER[1:]:
        if key in actor:
            fields[key] = _sorted(actor[key])
    text = io.StringIO()
    text.write(f"# yaml-language-server: $schema={url}\n")
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
    keep: bool = False
    """Whether the file's bytes are kept before it's replaced: a file git merged from troupe's
    versions (design D5)."""
    merge: str | None = None
    """``conflicted`` or ``clean``, for a file git merged."""
    not_troupes: tuple[str, ...] = ()
    """For a conflicted file refused: the sides (``ours``, ``theirs``) troupe didn't write."""
    mark: bool = False
    """Whether git's index holds this file unmerged from versions troupe wrote, so the setting
    mark_merges_resolved marks it resolved once it's written (mark-config-resolved design D3)."""


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


SIDES = ("ours", "theirs")


def _merged_from_troupes(
    path: str, have: bytes, merge: MergeSides, vouched: Mapping[str, frozenset[str]]
) -> bool:
    """Whether git made ``have`` only from versions troupe wrote: every side is troupe's, and a
    clean merge's file is still exactly what git merged (design D4 step 2)."""
    if merge.kind == "clean" and have != merge.merged:
        return False
    return all(side is None or _troupes(path, side, vouched) for side in merge.sides)


class MergeReader(Protocol):
    """The part of the VCS port config files need: what a merge combined (design D2), and marking a
    merged path resolved (mark-config-resolved design D4)."""

    def merge_sides_under(self, directory: str) -> Mapping[str, MergeSides]: ...

    def mark_resolved(self, paths: Mapping[str, Resolve]) -> Marked: ...


def _markable(path: str, merge: MergeSides | None, vouched: Mapping[str, frozenset[str]]) -> bool:
    """Whether git holds ``path`` unmerged from versions troupe wrote only (mark-config-resolved
    design D3): a side a person wrote is never resolved away."""
    return (
        merge is not None
        and merge.kind == "conflicted"
        and all(side is None or _troupes(path, side, vouched) for side in merge.sides)
    )


def merges(vcs: MergeReader) -> dict[str, MergeSides]:
    """Each config file a merge combined, by its path relative to .troupe/ (design D7)."""
    found: dict[str, MergeSides] = {}
    for directory in CONFIG_DIRECTORIES:
        for path, sides in vcs.merge_sides_under(f"{THEATRE_DIR}/{directory}").items():
            found[path.removeprefix(f"{THEATRE_DIR}/")] = sides
    return found


def plan(
    troupe_dir: Path,
    rendered: Mapping[str, bytes],
    recorded: Mapping[str, frozenset[str]],
    *,
    force: bool = False,
    merged: Mapping[str, MergeSides] | None = None,
    resolve: frozenset[str] = frozenset(),
) -> Plan:
    """What making the files exactly ``rendered`` takes, and what it would have to refuse.
    ``recorded`` is every hash an event recorded for each path. ``merged`` is what the VCS says
    a merge combined into each path, and ``resolve`` the paths this command may rewrite from a
    merge (design D4, D7)."""
    merged = merged or {}
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
            reason = "a write troupe recorded and didn't finish"
            have, merge = disk.files.get(target), merged.get(target)
            if (
                have is not None
                and have != data
                and merge is not None
                and not _troupes(target, have, vouched)
                and _merged_from_troupes(target, have, merge, vouched)
            ):
                # Moving the staged file into place replaces a file git merged: keep it (D5).
                if target not in resolve:
                    actions.append(Action(target, "refuse", MERGED, data, merge=merge.kind))
                    continue
                actions.append(
                    Action(
                        staged,
                        "finish",
                        reason,
                        data,
                        keep=True,
                        merge=merge.kind,
                        mark=_markable(target, merge, vouched),
                    )
                )
                continue
            mark = _markable(target, merged.get(target), vouched)
            actions.append(Action(staged, "finish", reason, data, mark=mark))
        else:
            actions.append(Action(staged, "discard", "a write troupe staged but never recorded"))
    finishing = {staged_target(a.path) for a in actions if a.action == "finish"}
    finishing |= {a.path for a in actions if a.action == "refuse"}  # a staged write refused
    for path in sorted(rendered.keys() | disk.files.keys()):
        want, have = rendered.get(path), disk.files.get(path)
        if want == have or path in finishing:
            continue
        merge = merged.get(path)
        mark = _markable(path, merge, vouched)
        if have is None:
            reason = "config holds it, and it was missing" if path in vouched else "new"
            actions.append(Action(path, "write", reason, want, mark=mark))
            continue
        action = "write" if want is not None else "remove"
        if _troupes(path, have, vouched):
            actions.append(Action(path, action, "an older version troupe wrote", want, mark=mark))
        elif merge is not None and _merged_from_troupes(path, have, merge, vouched):
            if path in resolve:
                reason = MERGE_REASONS[merge.kind]
                actions.append(
                    Action(path, action, reason, want, keep=True, merge=merge.kind, mark=mark)
                )
            else:
                actions.append(Action(path, "refuse", MERGED, want, merge=merge.kind))
        elif force:
            actions.append(
                Action(path, action, "forced past a file troupe didn't write", want, True)
            )
        elif (merge is not None and merge.kind == "conflicted") or _MARKERS.search(have):
            not_troupes: tuple[str, ...] = ()
            if merge is not None and merge.kind == "conflicted":
                not_troupes = tuple(
                    name
                    for name, side in zip(SIDES, merge.sides, strict=True)
                    if side is not None and not _troupes(path, side, vouched)
                )
            actions.append(Action(path, "refuse", CONFLICTED, want, not_troupes=not_troupes))
        else:
            actions.append(Action(path, "refuse", "troupe didn't write it", want))
    return Plan(tuple(actions), disk.unknown)


CONFLICTED = "git left it conflicted"
MERGED = "git merged it from versions troupe wrote"
"""A file this command may not rewrite from a merge: troupe flush does (design D7)."""
MERGE_REASONS = {
    "conflicted": "git left it conflicted, from versions troupe wrote",
    "clean": "git merged it from versions troupe wrote",
}
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
        raise _conflicted(conflicted)
    merged = [a for a in plan_.refused if a.reason == MERGED]
    if merged:
        listed = ", ".join(f".troupe/{a.path}" for a in merged)
        raise TroupeError(
            "config.file-not-troupes",
            problem=f"{listed}: git merged it from versions troupe wrote, so troupe can write it "
            "again from the merged config, but only when you ask, in case you're resolving it.",
            fix="Run troupe flush to write it from the merged config (or, if config has a "
            "conflict, the troupe config set that resolves it). troupe keeps a copy of what it "
            "holds now. Then git add it and commit the merge.",
            path=f"{THEATRE_DIR}/{merged[0].path}",
            details={"paths": [f"{THEATRE_DIR}/{a.path}" for a in merged]},
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


def _conflicted(refused: Sequence[Action]) -> TroupeError:
    """config.file-not-troupes for files with git's conflict markers in them that troupe can't
    tell were made only from its own versions."""
    listed = ", ".join(f".troupe/{a.path}" for a in refused)
    first = refused[0]
    named = f".troupe/{first.path}"
    if len(first.not_troupes) == 1:
        side = first.not_troupes[0]
        other = "theirs" if side == "ours" else "ours"
        problem = (
            f"{listed} has git's conflict markers in it, and {side} isn't a version troupe "
            "wrote, so troupe won't replace it: that side may hold a hand edit."
        )
        fix = (
            f"Take the side troupe wrote (git checkout --{other} {named}) and run troupe flush, "
            "or run troupe flush --force to replace it, keeping a copy of what it holds."
        )
    elif first.not_troupes:
        problem = (
            f"{listed} has git's conflict markers in it, and neither side is a version troupe "
            "wrote, so troupe won't replace it: they may hold hand edits."
        )
        fix = (
            "Resolve the file by hand and make the change with troupe config set, or run troupe "
            "flush --force to replace it, keeping a copy of what it holds."
        )
    else:
        problem = (
            f"{listed} has git's conflict markers in it, but git isn't merging it now, so troupe "
            "can't tell which versions it came from and won't replace it."
        )
        fix = (
            f"If a merge is part-way through, take one side (git checkout --ours {named}) and "
            "run troupe flush. Otherwise remove the markers, or run troupe flush --force to "
            "replace it, keeping a copy of what it holds."
        )
    return TroupeError(
        "config.file-not-troupes",
        problem=problem,
        fix=fix,
        path=f"{THEATRE_DIR}/{first.path}",
        details={"paths": [f"{THEATRE_DIR}/{a.path}" for a in refused]},
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
    resolved: "Resolved" = field(default_factory=lambda: Resolved({}))
    """What marking each file git left unmerged resolved did, or would do."""

    def notices(self) -> list[Notice]:
        rewritten = []
        for a in self.actions:
            if a.action not in ("write", "remove") or a.reason == "new" or a.forced or a.keep:
                continue
            details: dict[str, object] = {"reason": a.reason}
            if a.path in self.resolved.paths and self.resolved.paths[a.path] is None:
                details["resolved"] = True
            rewritten.append(
                Notice(
                    "config.file-rewritten",
                    problem=f".troupe/{a.path}: {a.reason}, so troupe wrote it again from config"
                    + (", and marked it resolved in git." if "resolved" in details else "."),
                    fix="Nothing to do: config is unchanged.",
                    path=f"{THEATRE_DIR}/{a.path}",
                    details=details,
                )
            )
        return [*rewritten, *merge_notices(self.actions, self.kept, self.resolved)]


Unresolved = Unmarked | Literal["setting", "policy"]
"""Why a file git left unmerged that troupe rewrote wasn't marked resolved: the setting is off,
policy forbids it, or the VCS didn't mark it (mark-config-resolved design D6)."""


@dataclass(frozen=True)
class Resolved:
    """For each file git left unmerged from troupe's versions that a command rewrote, by path
    relative to .troupe/: None when it was (or, rehearsed, would be) marked resolved, else why
    not; and git's message when marking failed."""

    paths: Mapping[str, Unresolved | None]
    message: str | None = None


def resolutions(plan_: Plan, merged: Mapping[str, MergeSides]) -> dict[str, Resolve]:
    """What marking resolved the files ``plan_`` rewrites from versions troupe wrote takes, by path
    relative to .troupe/ (mark-config-resolved design D3). A file forced past is never marked."""
    found: dict[str, Resolve] = {}
    for a in plan_.changes:
        if a.mark and not a.forced and a.action in ("write", "remove", "finish"):
            path = staged_target(a.path) or a.path
            found[path] = Resolve(merged[path], None if a.action == "remove" else a.data)
    return found


def mark_resolved(
    vcs: MergeReader | None,
    plan_: Plan,
    merged: Mapping[str, MergeSides],
    marking: Marking,
    *,
    rehearse: bool = False,
) -> Resolved:
    """Mark the files ``plan_`` rewrote from git's unmerged versions resolved, when ``marking`` is
    on; a rehearsal marks nothing and says what it would do (mark-config-resolved design D6)."""
    due = resolutions(plan_, merged)
    if not due:
        return Resolved({})
    if not marking.on:
        return Resolved(dict.fromkeys(due, marking.off_because))
    if rehearse or vcs is None:
        return Resolved(dict.fromkeys(due))
    marked = vcs.mark_resolved({f"{THEATRE_DIR}/{path}": r for path, r in due.items()})
    return Resolved({path: marked.paths[f"{THEATRE_DIR}/{path}"] for path in due}, marked.message)


def _index_fix(path: str, merge: str, resolved: Resolved) -> tuple[str, dict[str, object]]:
    """config.merge-rewritten's fix, and its details about git's index (mark-config-resolved
    design D6)."""
    add = f"git add .troupe/{path} and commit the merge."
    if merge != "conflicted" or path not in resolved.paths:
        return add, {"resolved": False}
    why = resolved.paths[path]
    if why is None:
        return f"Commit the merge: troupe marked .troupe/{path} resolved in git.", {
            "resolved": True
        }
    fixes = {
        "setting": f"{add} Or set {settings.env_name(settings.MARK_MERGES_RESOLVED)}=true to "
        "have troupe mark it resolved for you.",
        "policy": f"{add} troupe didn't mark it resolved because policy forbids it "
        f"({policy.env_name(policy.ALLOW_MARK_MERGES_RESOLVED)}=false).",
        "index-changed": f"git's index changed after troupe read it, so troupe left it as it "
        f"is. Check git status, then {add}",
        "failed": f"troupe couldn't mark it resolved ({resolved.message}). {add}",
        "no-index": add,
    }
    return fixes[why], {"resolved": False, "unresolved": why}


def merge_notices(
    actions: Sequence[Action], kept: Mapping[str, str], resolved: Resolved | None = None
) -> list[Notice]:
    """config.merge-rewritten for each file git merged that troupe replaced (design D6), saying
    whether troupe marked it resolved (mark-config-resolved design D6)."""
    resolved = resolved or Resolved({})
    notices = []
    for a in actions:
        if not a.keep or a.merge is None:
            continue
        path = staged_target(a.path) or a.path
        action = "remove" if a.action == "remove" else "write"
        done = "removed it" if action == "remove" else "wrote it again from the merged config"
        fix, index = _index_fix(path, a.merge, resolved)
        notices.append(
            Notice(
                "config.merge-rewritten",
                problem=f".troupe/{path}: {MERGE_REASONS[a.merge]}, so troupe {done}. What it "
                f"held is kept in the artifact store as {kept[path]}.",
                fix=fix,
                path=f"{THEATRE_DIR}/{path}",
                details={"merge": a.merge, "action": action, "kept": kept[path], **index},
            )
        )
    return notices


def flush(
    theatre: Path,
    config: Mapping[str, Any],
    recorded: Mapping[str, frozenset[str]],
    *,
    force: bool = False,
    rehearse: bool = False,
    on_wait: WaitCallback | None = None,
    vcs: MergeReader | None = None,
    resolve: bool = False,
    marking: Marking = settings.OFF,
) -> Flushed:
    """Make the config files exactly what ``config`` says. Refused, writing nothing, when it would
    replace a file troupe didn't write (unless ``force``), or meets an unknown file. With
    ``rehearse``, works out what it would do and does none of it. With ``vcs``, a file git merged
    from troupe's versions counts as troupe's, and with ``resolve`` it's replaced, keeping a copy;
    without, it's refused, naming troupe flush (design D4, D7). With ``marking`` on, each file it
    rewrites that git left unmerged from troupe's versions is marked resolved (mark-config-resolved
    design D6)."""
    troupe_dir = theatre / THEATRE_DIR
    rendered = render(config)

    def again() -> tuple[Plan, dict[str, MergeSides]]:
        merged = merges(vcs) if vcs is not None else {}
        allowed = frozenset(merged) if resolve else frozenset()
        made = plan(troupe_dir, rendered, recorded, force=force, merged=merged, resolve=allowed)
        return made, merged

    plan_, merged = again()
    refuse(plan_)
    if rehearse or not plan_.changes:
        return Flushed(
            plan_.changes, resolved=mark_resolved(vcs, plan_, merged, marking, rehearse=True)
        )
    with locked(troupe_dir, on_wait):
        plan_, merged = again()  # again, now nothing can move
        refuse(plan_)
        kept = execute(troupe_dir, plan_)
        resolved = mark_resolved(vcs, plan_, merged, marking)
    return Flushed(plan_.changes, kept, resolved)


def execute(troupe_dir: Path, plan_: Plan) -> dict[str, str]:
    """Carry out ``plan_``, holding the lock: each new file staged then moved into place. Returns
    each file forced past, and the artifact its bytes were kept under."""
    ensure_git_files(troupe_dir)
    kept: dict[str, str] = {}
    written: list[dict[str, str]] = []
    for action in plan_.changes:
        path = staged_target(action.path) or action.path
        target = troupe_dir / path
        if (action.forced or action.keep) and target.exists():
            store = load_store(defaults.ARTIFACT_STORE, troupe_dir / "local" / "artifacts")
            kept[path] = store.put(target.read_bytes())
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

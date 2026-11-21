"""Syncing config with its files: the sweep, a command's own change, and the write, as one step
every command that uses config takes (spec: config-hand-edits, config-files; hand-edit-sweep
design D1, D7, D8, D10, D11).

Holding the config files' lock (except in a rehearsal, which writes nothing), a sync:

1. sweeps the files (``troupe.core.config.sweep``): each meaningful hand edit, file by file;
2. works out the command's own change, if it has one, on the config the sweep leaves;
3. checks conflicts across both: they're recorded together only when they resolve every one, and
   ``config get`` records nothing short of that, saying so;
4. works out every file's target: a person's file written back surgically, troupe's rendered
   whole (``troupe.core.config.writeback``), and plans the write, refusing a file it can't
   replace;
5. stages the command's new files, records the hand edits and the change in one batch, and moves
   the staged files into place, checking each file is still what the sweep read.

Each recorded hand edit is reported as ``config.hand-edit-recorded``, and each conflicting value a
hand edit resolved as ``config.conflict-resolved``, so nothing is resolved without the person
seeing it (owner, 2026-11-21).
"""

from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from troupe.core.config.changes import apply, change
from troupe.core.config.kinds import staged_name, staged_target
from troupe.core.config.merge import Merged
from troupe.core.config.projection import (
    Action,
    Flushed,
    Resolved,
    execute,
    file_hash,
    locked,
    mark_resolved,
    merge_notices,
    merges,
    plan,
    refuse,
    stage,
)
from troupe.core.config.stream import read, record_with_edits, refuse_conflicts
from troupe.core.config.sweep import Edit, Swept, remember_present, sweep
from troupe.core.config.writeback import targets
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.events.lineage import Actor
from troupe.core.notices import Notice
from troupe.core.settings import OFF, Marking
from troupe.core.theatre import THEATRE_DIR
from troupe.core.vcs import MergeSides
from troupe.platform.files import WaitCallback

Operation = tuple[Sequence[str], object]


@dataclass(frozen=True)
class Synced:
    """What a sync did, or in a rehearsal would do."""

    merged: Merged
    """Config as the sync leaves it (in a rehearsal, as it would)."""
    edits: tuple[Edit, ...] = ()
    """The hand edits recorded (in a rehearsal, that would be)."""
    sweep_change: str | None = None
    """The change id the recorded hand edits share."""
    change: str | None = None
    """The command's own change id, when it recorded one."""
    entries: list[dict[str, Any]] = field(default_factory=list)
    """The command's own change's entries."""
    actions: tuple[Action, ...] = ()
    own: frozenset[str] = frozenset()
    """The files the command's own change wrote or removed."""
    kept: dict[str, str] = field(default_factory=dict)
    resolved: Resolved = field(default_factory=lambda: Resolved({}))
    notices: list[Notice] = field(default_factory=list)


@dataclass(frozen=True)
class Request:
    """How a command syncs: its own change (``operations``), and what it may do."""

    operations: Sequence[Operation] = ()
    reason: str | None = None
    actor: Actor | None = None
    force: bool = False
    rehearse: bool = False
    query: bool = False
    """``config get``: sweeps and records, but writes no file and records nothing short of
    resolving every conflict."""
    resolve_all: bool = False
    """``troupe sync``: may rewrite every file git merged from troupe's versions (design D7 of
    config-projection-conflicts)."""
    marking: Marking | None = None
    on_wait: WaitCallback | None = None


def sync_config(theatre: Path, store: EventStore, request: Request) -> Synced:
    """Sweep, record and write, as ``request`` asks (see the module's docstring)."""
    troupe_dir = theatre / THEATRE_DIR
    guard: AbstractContextManager[None] = (
        nullcontext() if request.rehearse else locked(troupe_dir, request.on_wait)
    )
    with guard:
        return _sync(troupe_dir, store, request)


@dataclass(frozen=True)
class _Work:
    """What a sync worked out before writing anything."""

    merged: Merged
    found: Mapping[str, MergeSides]
    swept: Swept
    entries: list[dict[str, Any]]
    after: dict[str, Any]
    typed: set[tuple[str, ...]] | None
    vouched: dict[str, frozenset[str]]
    files: dict[str, bytes]
    """Every config file's target: a person's written back surgically, troupe's whole."""
    own: frozenset[str]
    """The files the command's own change writes or removes."""
    resolve: frozenset[str]
    notices: list[Notice]


def _sync(troupe_dir: Path, store: EventStore, request: Request) -> Synced:
    merged = read(store)
    found = merges(store.vcs)
    swept = sweep(troupe_dir, merged.config, merged.files, found, force=request.force)
    after_edits = apply(merged.config, swept.entries)
    entries = change(after_edits, request.operations) if request.operations else []
    after = apply(after_edits, entries) if entries else after_edits
    if merged.conflicts and request.query and not _resolves(store, merged, swept, entries):
        return Synced(merged, notices=[*swept.notices, *_unrecorded(merged, swept)])
    if merged.conflicts and not (swept.edits or entries):
        refuse_conflicts(merged)
    resolved_notices = _resolved_notices(merged, swept, request.rehearse)
    if request.query:
        return _record_only(store, merged, swept, after, resolved_notices, request.rehearse)
    work = _work(request, merged, found, swept, after_edits, entries, after, resolved_notices)
    first = plan(
        troupe_dir,
        work.files,
        work.vouched,
        force=request.force,
        merged=found,
        resolve=work.resolve,
    )
    refuse(first)
    if swept.edits or entries:
        record_check(store, merged, swept, entries, work.typed)  # before anything is staged
    if request.rehearse:
        marks = mark_resolved(store.vcs, first, found, request.marking or OFF, rehearse=True)
        return Synced(
            replace(merged, config=after),
            swept.edits,
            entries=entries,
            actions=first.changes,
            own=work.own,
            resolved=marks,
            notices=[
                *swept.notices,
                *_edit_notices(swept.edits, None, rehearse=True),
                *resolved_notices,
            ],
        )
    return _record_and_write(troupe_dir, store, request, work)


def _work(
    request: Request,
    merged: Merged,
    found: Mapping[str, MergeSides],
    swept: Swept,
    after_edits: dict[str, Any],
    entries: list[dict[str, Any]],
    after: dict[str, Any],
    notices: list[Notice],
) -> _Work:
    """The files a sync makes, and which of them may be replaced (design D6, D7)."""
    readable = swept.read - swept.refused
    vouched = dict(merged.files)
    for path in readable:
        data = swept.seen.get(path)
        if data is not None:
            vouched[path] = vouched.get(path, frozenset()) | {file_hash(data)}
    before_files = targets(after_edits, swept.seen, readable)
    files = targets(after, swept.seen, readable)
    changed = {p for p in before_files.keys() | files.keys() if before_files.get(p) != files.get(p)}
    own = frozenset(changed) if entries else frozenset()
    return _Work(
        merged,
        found,
        swept,
        entries,
        after,
        {tuple(path) for path, _ in request.operations} or None,
        vouched,
        files,
        own,
        _resolve(request, merged, set(own), found),
        notices,
    )


def _record_and_write(troupe_dir: Path, store: EventStore, request: Request, work: _Work) -> Synced:
    """Stage the command's files, record the hand edits and its change in one batch, then move
    every file into place, checking each is still what the sweep read (design D9, D10)."""
    own_files = [
        {"path": p, "hash": file_hash(work.files[p])} if p in work.files else {"path": p}
        for p in sorted(work.own)
    ]
    for written in own_files:
        if "hash" in written:
            stage(troupe_dir, written["path"], work.files[written["path"]])
    command = (
        store.command(via="cli", reason=request.reason, actor=request.actor)
        if work.entries
        else None
    )
    try:
        recorded = record_with_edits(
            store,
            work.merged,
            work.swept.edits,
            (command, work.entries, own_files) if command is not None else None,
            work.typed,
        )
    except BaseException:
        for written in own_files:
            (troupe_dir / staged_name(written["path"])).unlink(missing_ok=True)
        raise
    vouched = dict(work.vouched)
    for written in own_files:
        if "hash" in written:
            vouched[written["path"]] = vouched.get(written["path"], frozenset()) | {written["hash"]}
    done = plan(
        troupe_dir,
        work.files,
        vouched,
        force=request.force,
        merged=work.found,
        resolve=work.resolve,
    )
    refuse(done)
    swept = work.swept
    expect = {p: d for p, d in swept.seen.items() if p not in swept.refused or not request.force}
    kept = execute(troupe_dir, done, expect)
    remember_present(troupe_dir)
    marks = mark_resolved(store.vcs, done, work.found, request.marking or OFF)
    sweep_change = _sweep_change(store, recorded, len(swept.edits), len(work.merged.heads) > 1)
    return Synced(
        read(store),
        swept.edits,
        sweep_change,
        command.change if command is not None else None,
        work.entries,
        done.changes,
        work.own,
        kept,
        marks,
        [*swept.notices, *_edit_notices(swept.edits, sweep_change), *work.notices],
    )


def record_check(
    store: EventStore,
    merged: Merged,
    swept: Swept,
    entries: Sequence[dict[str, Any]],
    typed: Collection[tuple[str, ...]] | None,
) -> None:
    """Every check recording the sweep's edits and the command's change would make: a rule broken,
    or a conflict left (for a rehearsal, which records nothing)."""
    from troupe.core.config.stream import refuse_unrecordable

    refuse_unrecordable(store, merged, [*swept.entries, *entries], typed)


def _record_only(
    store: EventStore,
    merged: Merged,
    swept: Swept,
    after: Mapping[str, Any],
    resolved_notices: list[Notice],
    rehearse: bool,
) -> Synced:
    """``config get``'s sync: the hand edits recorded, and no file written."""
    if not swept.edits:
        return Synced(merged, notices=list(swept.notices))
    if rehearse:
        record_check(store, merged, swept, [], None)
        return Synced(
            replace(merged, config=dict(after)),
            swept.edits,
            notices=[
                *swept.notices,
                *_edit_notices(swept.edits, None, rehearse=True),
                *resolved_notices,
            ],
        )
    recorded = record_with_edits(store, merged, swept.edits)
    remember_present(store.theatre / THEATRE_DIR)
    sweep_change = _sweep_change(store, recorded, len(swept.edits), len(merged.heads) > 1)
    return Synced(
        read(store),
        swept.edits,
        sweep_change,
        notices=[*swept.notices, *_edit_notices(swept.edits, sweep_change), *resolved_notices],
    )


def _sweep_change(
    store: EventStore, recorded: Sequence[Any], edits: int, settled: bool
) -> str | None:
    """The change id the recorded hand edits share: the lineage of the first of them."""
    if not edits:
        return None
    first = recorded[1 if settled else 0]
    lineage = store.recorder.event(first.event_id)
    if lineage is None or lineage.lineage is None:
        return None
    found = lineage.lineage.get("change")
    return found if isinstance(found, str) else None


def _resolve(
    request: Request, merged: Merged, own: set[str], found: Mapping[str, MergeSides]
) -> frozenset[str]:
    """The files git merged that this sync may rewrite: every one for troupe sync, or for a change
    recorded while config has conflicts; those the command's own change writes; else none."""
    if request.resolve_all or merged.conflicts:
        return frozenset(found)
    return frozenset(own & found.keys())


def _resolves(
    store: EventStore, merged: Merged, swept: Swept, entries: Sequence[dict[str, Any]]
) -> bool:
    """Whether the sweep's edits and the command's change together resolve every conflict."""
    if not (swept.edits or entries):
        return False
    try:
        record_check(store, merged, swept, entries, None)
    except TroupeError as error:
        if error.code == "config.conflict":
            return False
        raise
    return True


def _left(merged: Merged, swept: Swept) -> list[list[str]]:
    """The conflicting paths no hand edit sets or unsets."""
    set_by_edits = [tuple(entry["path"]) for entry in swept.entries]
    return [
        list(path)
        for conflict in merged.conflicts
        for path in conflict.paths
        if not any(path[: len(p)] == p or p[: len(path)] == path for p in set_by_edits)
    ]


def _unrecorded(merged: Merged, swept: Swept) -> list[Notice]:
    """config get's notice that hand edits weren't recorded, since they leave conflicts."""
    if not swept.edits:
        return []
    files = [f"{THEATRE_DIR}/{edit.path}" for edit in swept.edits]
    left = _left(merged, swept)
    return [
        Notice(
            "config.hand-edit-unrecorded",
            problem=f"Edits to {', '.join(files)} aren't recorded yet: config has conflicts, and "
            f"they leave {', '.join(shown(p) for p in left) or 'some'} unresolved.",
            fix="Set every conflicting value, in the files or with troupe config set; config get "
            "shows both sides.",
            details={"files": files, "left": left},
        )
    ]


def _resolved_notices(merged: Merged, swept: Swept, rehearse: bool) -> list[Notice]:
    """A config.conflict-resolved notice for each conflicting value a hand edit sets or unsets."""
    found: list[Notice] = []
    for conflict in merged.conflicts:
        for path in conflict.paths:
            for edit in swept.edits:
                entry = next(
                    (e for e in edit.entries if tuple(e["path"]) == path[: len(e["path"])]),
                    None,
                )
                if entry is None:
                    continue
                found.append(_resolved_notice(path, edit, entry, conflict.changes, rehearse))
    return found


def _resolved_notice(
    path: tuple[str, ...],
    edit: Edit,
    entry: Mapping[str, Any],
    changes: Sequence[Any],
    rehearse: bool,
) -> Notice:
    file = f"{THEATRE_DIR}/{edit.path}"
    details: dict[str, Any] = {
        "path": list(path),
        "file": file,
        "changes": [c.change for c in changes],
    }
    unset = "after" not in entry or tuple(entry["path"]) != path
    took = "unset it" if unset else f"took {_shown_value(entry['after'])}"
    if unset:
        details["unset"] = True
    else:
        details["value"] = entry["after"]
    if rehearse:
        details["rehearsal"] = True
    verb = "would resolve" if rehearse else "resolved"
    return Notice(
        "config.conflict-resolved",
        problem=f"The edit to {file} {verb} the conflict on {shown(path)}: it {took}, over the "
        f"changes {', '.join(details['changes'])}.",
        fix="Nothing to do if that's what you meant; otherwise set the value again.",
        details=details,
    )


def _shown_value(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _edit_notices(
    edits: Sequence[Edit], change_id: str | None, *, rehearse: bool = False
) -> list[Notice]:
    """A config.hand-edit-recorded notice for each hand edit."""
    found: list[Notice] = []
    for edit in edits:
        file = f"{THEATRE_DIR}/{edit.path}"
        details: dict[str, Any] = {"file": file, "entries": len(edit.entries)}
        if change_id is not None:
            details["change"] = change_id
        if rehearse:
            details["rehearsal"] = True
        verb = "would record" if rehearse else "recorded"
        values = f"{len(edit.entries)} value{'s' if len(edit.entries) != 1 else ''}"
        what = (
            f"{file} going missing as removing what it held"
            if edit.after is None
            else f"the edit to {file}"
        )
        if edit.after is None:
            details["removed"] = True
        found.append(
            Notice(
                "config.hand-edit-recorded",
                problem=f"troupe {verb} {what}, as a change by an unknown author ({values}).",
                fix="Nothing to do: the file is what config says now.",
                details=details,
            )
        )
    return found


def file_notices(synced: Synced) -> list[Notice]:
    """The notices of the files a sync changed: those its own change didn't write as rewrites, and
    merge notices for all of them."""

    def target(action: Action) -> str:
        return staged_target(action.path) or action.path

    others = tuple(a for a in synced.actions if target(a) not in synced.own)
    own = tuple(a for a in synced.actions if target(a) in synced.own)
    return [
        *Flushed(others, synced.kept, synced.resolved).notices(),
        *merge_notices(own, synced.kept, synced.resolved),
    ]

"""config-set, config-get and flush behind the client protocol (spec: config, config-files;
config-model design D9, D10).

Every command that uses config flushes first, so the files are right before anything reads
config, and a file troupe didn't write stops the command before it does anything. A change is
written in the order design D9 gives, holding the config files' lock throughout: check every file
it touches is troupe's, stage each new file beside its target, record the ``Config.Changed`` with
each file's hash, then move the staged files into place. A crash between recording and moving is
finished by the next flush, since the event vouches for the staged files.

A file git merged from versions troupe wrote is rewritten only by troupe flush, or by a config set
whose change writes it; the flush every other command runs first refuses it, naming troupe flush
(config-projection-conflicts design D7).
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from troupe.core.client import messages as m
from troupe.core.client.dispatch import Method, Send
from troupe.core.client.session import Session
from troupe.core.config.changes import UNSET, apply, change, get
from troupe.core.config.kinds import staged_name, staged_target
from troupe.core.config.merge import Merged
from troupe.core.config.projection import (
    Action,
    Flushed,
    execute,
    file_hash,
    flush,
    locked,
    merge_notices,
    merges,
    plan,
    refuse,
    render,
    stage,
)
from troupe.core.config.stream import read, record, refuse_conflicts, refuse_unrecordable
from troupe.core.events import EventStore
from troupe.core.messages import Message
from troupe.core.notices import Notice
from troupe.core.stores import open_event_store
from troupe.core.theatre import THEATRE_DIR
from troupe.platform.files import WaitCallback


def _waiting(send: Send) -> WaitCallback:
    def on_wait(path: Path, waited: float) -> None:
        notice = Notice(
            "config.waiting",
            problem=f"Another troupe command is writing config files; waiting for it "
            f"({waited:.0f}s so far).",
            fix="Nothing to do: this command goes on once the other finishes.",
            path=str(path),
            details={"waitedSeconds": round(waited, 3)},
        )
        send(m.NoticeUpdate(m.NoticeData.of(notice)))

    return on_wait


def _files(
    actions: tuple[Action, ...], kept: Mapping[str, str], *, finished: str | None = None
) -> list[m.FileAction]:
    """Each file a command changed. With ``finished``, a staged write moved into place is
    reported as the write of its target, for that reason: what the person's change wrote."""
    reported: list[m.FileAction] = []
    for a in actions:
        path, action, reason = a.path, a.action, a.reason
        if finished is not None and action == "finish":
            path, action, reason = staged_target(a.path) or a.path, "write", finished
        reported.append(
            m.FileAction(
                path=f"{THEATRE_DIR}/{path}",
                action=action,  # type: ignore[arg-type]  # the four actions a plan holds
                reason=reason,
                kept=kept.get(staged_target(a.path) or a.path),
            )
        )
    return reported


def _notices(*groups: list[Notice]) -> list[m.NoticeData]:
    return [m.NoticeData.of(notice) for group in groups for notice in group]


def sync_files(session: Session, store: EventStore, merged: Merged, send: Send) -> list[Notice]:
    """Flush before a command uses config: refused when config has conflicts, or when a file
    troupe didn't write is in the way. Returns the notices of what was written again."""
    refuse_conflicts(merged)
    flushed = flush(
        session.theatre, merged.config, merged.files, on_wait=_waiting(send), vcs=store.vcs
    )
    return [*flushed.notices(), *store.notices()]


def _writes(before: Mapping[str, bytes], after: Mapping[str, bytes]) -> frozenset[str]:
    """The files a change writes or removes: those its config renders differently."""
    return frozenset(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


async def config_set(request: m.ConfigSetRequest, session: Session, send: Send) -> Message:
    store = open_event_store(session)
    troupe_dir = session.theatre / THEATRE_DIR
    operations = [(op.path, UNSET if op.unset else op.value) for op in request.operations]
    if request.rehearse:
        merged = read(store)
        entries = change(merged.config, operations)
        if entries:
            refuse_unrecordable(store, merged, entries)
        rendered_after = render(apply(merged.config, entries))
        found = merges(store.vcs)
        resolve = _writes(render(merged.config), rendered_after) & found.keys()
        would = plan(troupe_dir, rendered_after, merged.files, merged=found, resolve=resolve)
        refuse(would)
        return m.ConfigSetResult(entries=entries, files=_files(would.changes, {}), notices=[])
    with locked(troupe_dir, _waiting(send)):
        merged = read(store)
        entries = change(merged.config, operations)
        after = apply(merged.config, entries) if entries else merged.config
        rendered_before, rendered_after = render(merged.config), render(after)
        # A file git merged may be rewritten only when this change writes it (design D7).
        found = merges(store.vcs)
        resolve = _writes(rendered_before, rendered_after) & found.keys()
        before: list[Notice] = []
        if not merged.conflicts:
            # Files right before the change, so the change's own files are written over troupe's.
            first = plan(troupe_dir, rendered_before, merged.files, merged=found, resolve=resolve)
            refuse(first)
            first_kept = execute(troupe_dir, first)
            before = Flushed(first.changes, first_kept).notices()
        if not entries:
            return m.ConfigSetResult(entries=[], files=[], notices=_notices(before))
        refuse_unrecordable(store, merged, entries)
        files: list[dict[str, Any]] = []
        for path in sorted(rendered_before.keys() | rendered_after.keys()):
            new = rendered_after.get(path)
            if new == rendered_before.get(path):
                continue
            files.append({"path": path} if new is None else {"path": path, "hash": file_hash(new)})
        refuse(plan(troupe_dir, rendered_after, merged.files, merged=found, resolve=resolve))
        for written in files:
            if "hash" in written:
                stage(troupe_dir, written["path"], rendered_after[written["path"]])
        command = store.command(via="cli", reason=request.reason)
        try:
            record(command, merged, entries, files)
        except BaseException:
            for written in files:
                (troupe_dir / staged_name(written["path"])).unlink(missing_ok=True)
            raise
        vouched = dict(merged.files)
        for written in files:
            if "hash" in written:
                vouched[written["path"]] = vouched.get(written["path"], frozenset()) | {
                    written["hash"]
                }
        done = plan(troupe_dir, rendered_after, vouched, merged=found, resolve=resolve)
        refuse(done)
        kept = execute(troupe_dir, done)
    return m.ConfigSetResult(
        change=command.change,
        entries=entries,
        files=_files(done.changes, kept, finished="for this change"),
        notices=_notices(before, merge_notices(done.changes, kept), store.notices()),
    )


async def config_get(request: m.ConfigGetRequest, session: Session, send: Send) -> Message:
    del send
    store = open_event_store(session)
    merged = read(store)
    value = merged.config if request.path is None else get(merged.config, request.path)
    if value == {}:
        value = None
    return m.ConfigGetResult(
        value=value,
        conflicts=[
            m.ConflictData(
                paths=[list(path) for path in conflict.paths],
                rule=conflict.rule,
                changes=[
                    m.ConflictingChange(
                        change=c.change,
                        actor=m.ActorData.from_data(c.actor),
                        at=c.at,
                        entries=[dict(e) for e in c.entries],
                    )
                    for c in conflict.changes
                ],
            )
            for conflict in merged.conflicts
        ],
        heads=list(merged.heads),
        notices=_notices(store.notices()),
    )


async def flush_files(request: m.FlushRequest, session: Session, send: Send) -> Message:
    store = open_event_store(session)
    merged = read(store)
    refuse_conflicts(merged)
    flushed = flush(
        session.theatre,
        merged.config,
        merged.files,
        force=bool(request.force),
        rehearse=bool(request.rehearse),
        on_wait=_waiting(send),
        vcs=store.vcs,
        resolve=True,
    )
    return m.FlushResult(
        files=_files(flushed.actions, flushed.kept),
        notices=_notices(flushed.notices() if not request.rehearse else [], store.notices()),
    )


async def _config_set(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await config_set(request, session, send)


async def _config_get(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await config_get(request, session, send)


async def _flush(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await flush_files(request, session, send)


def methods() -> Mapping[str, Method]:
    """The commands and queries config offers through the client protocol, by name."""
    return {
        "config-set": Method(m.ConfigSetRequest, _config_set),
        "config-get": Method(m.ConfigGetRequest, _config_get),
        "flush": Method(m.FlushRequest, _flush),
    }

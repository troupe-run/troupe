"""config-set, config-get, sync, config-drop and config-keep behind the client protocol (spec:
config, config-files, config-hand-edits; config-model design D9, D10; hand-edit-sweep design D1,
D11; abandoned-edits design D6).

Every command that uses config syncs first (``troupe.core.config.syncing``): it sweeps the files,
recording each meaningful hand edit by the unknown author, then works out its own change, and
writes the files, a person's surgically and troupe's whole, in design D9's order: stage each new
file, record, then move the staged files into place. A crash between recording and moving is
finished by the next sync, since the event vouches for the staged files.

A file git merged from versions troupe wrote is rewritten only by troupe sync, or by a config set
whose change writes it or resolves config's conflicts; the sync every other command runs first
refuses it, naming troupe sync (config-projection-conflicts design D7).
"""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

from troupe.core import runtimes
from troupe.core.client import messages as m
from troupe.core.client.dispatch import Method, Send
from troupe.core.client.session import Session
from troupe.core.config import abandoned, aggregate
from troupe.core.config.changes import UNSET, get
from troupe.core.config.kinds import staged_target
from troupe.core.config.projection import Action, Resolved, locked
from troupe.core.config.syncing import Request, Synced, file_notices, sync_config
from troupe.core.config_paths import shown
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.events.lineage import Actor
from troupe.core.notices import Notice
from troupe.core.settings import marking
from troupe.core.stores import open_event_store
from troupe.core.theatre import THEATRE_DIR
from troupe.platform.files import WaitCallback
from troupe_plugin_sdk.messages import Message


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
    actions: tuple[Action, ...],
    kept: Mapping[str, str],
    resolved: Resolved,
    *,
    finished: str | None = None,
) -> list[m.FileAction]:
    """Each file a command changed. With ``finished``, a staged write moved into place is
    reported as the write of its target, for that reason: what the person's change wrote. A file
    git left unmerged from troupe's versions says whether it was (or would be) marked resolved."""
    reported: list[m.FileAction] = []
    for a in actions:
        path, action, reason = a.path, a.action, a.reason
        target = staged_target(a.path) or a.path
        if finished is not None and action == "finish":
            path, action, reason = target, "write", finished
        reported.append(
            m.FileAction(
                path=f"{THEATRE_DIR}/{path}",
                action=action,  # type: ignore[arg-type]  # the four actions a plan holds
                reason=reason,
                kept=kept.get(target),
                resolve=resolved.paths[target] is None if target in resolved.paths else None,
            )
        )
    return reported


def _notices(*groups: list[Notice]) -> list[m.NoticeData]:
    return [m.NoticeData.of(notice) for group in groups for notice in group]


def _request(session: Session, send: Send, **fields: Any) -> Request:  # noqa: ANN401
    return Request(marking=marking(session.env), on_wait=_waiting(send), **fields)


def sync_files(
    session: Session, store: EventStore, send: Send, *, rehearse: bool = False
) -> Synced:
    """Sync before perform uses config: sweep hand edits and record them, then make the files
    what config says (spec: config-hand-edits, config-files). Refused when config has conflicts
    the hand edits don't resolve, or when a file troupe can't read is in the way. Each notice is
    sent as it's known."""
    synced = sync_config(
        session.theatre, store, _request(session, send, rehearse=rehearse, runs_now=True)
    )
    for notice in [*synced.notices, *file_notices(synced), *store.notices()]:
        send(m.NoticeUpdate(m.NoticeData.of(notice)))
    return synced


async def config_set(request: m.ConfigSetRequest, session: Session, send: Send) -> Message:
    store = open_event_store(session)
    operations = [(op.path, UNSET if op.unset else op.value) for op in request.operations]
    if request.rehearse:
        synced = sync_config(
            session.theatre, store, _request(session, send, operations=operations, rehearse=True)
        )
        return m.ConfigSetResult(
            entries=synced.entries,
            files=_files(synced.actions, {}, synced.resolved),
            notices=_notices(synced.notices),
        )
    return record_change(session, store, operations, reason=request.reason, send=send)


def _target(action: Action) -> str:
    return staged_target(action.path) or action.path


def record_change(
    session: Session,
    store: EventStore,
    operations: Sequence[tuple[Sequence[str], object]],
    *,
    reason: str | None,
    send: Send,
    actor: Actor | None = None,
) -> m.ConfigSetResult:
    """Sweep, then record one change of ``operations`` and write its files, in design D9's order
    (stage, record, replace), holding the config files' lock throughout. ``actor`` is who made it
    when the caller resolved that already (troupe init does, before it makes anything;
    init-and-audition design D2), else the store's identity chain is asked. config-set and init
    both record through here, so an audition's change is exactly what config-set would record
    (init-and-audition design D3)."""
    synced = sync_config(
        session.theatre,
        store,
        _request(session, send, operations=operations, reason=reason, actor=actor),
    )
    own = tuple(a for a in synced.actions if _target(a) in synced.own)
    others = tuple(a for a in synced.actions if _target(a) not in synced.own)
    return m.ConfigSetResult(
        change=synced.change,
        entries=synced.entries,
        files=[
            *_files(others, synced.kept, synced.resolved),
            *_files(own, synced.kept, synced.resolved, finished="for this change"),
        ],
        notices=_notices(synced.notices, file_notices(synced), store.notices()),
    )


async def config_get(request: m.ConfigGetRequest, session: Session, send: Send) -> Message:
    store = open_event_store(session)
    synced = sync_config(session.theatre, store, _request(session, send, query=True))
    merged = synced.merged
    value = merged.config if request.path is None else get(merged.config, request.path)
    if value == {}:
        value = None
    resolved = _resolved(request.path, merged.config, session.env) if request.resolved else None
    return m.ConfigGetResult(
        value=value,
        runtimes=resolved,
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
        notices=_notices(synced.notices, store.notices()),
    )


def _resolved(
    path: Sequence[str] | None, config: Mapping[str, Any], env: Mapping[str, str]
) -> dict[str, m.ResolvedRuntime]:
    """The runtimes ``path`` covers, as troupe resolves them now (spec: runtimes, "Config get
    shows a runtime's resolved values and their sources"). Only runtimes have resolved values."""
    if path is None or list(path) == [runtimes.RUNTIMES]:
        chosen = runtimes.names(config)
    elif len(path) == 2 and path[0] == runtimes.RUNTIMES:
        chosen = [path[1]]
    else:
        where = shown(path)
        raise TroupeError(
            "config.not-resolvable",
            problem=f"{where} has no resolved values: only runtimes do.",
            fix="Run troupe config get --resolved with no path, runtimes, or runtimes.<name>; "
            f"or troupe config get {where} without --resolved.",
            details={"path": list(path)},
        )
    return {
        name: m.ResolvedRuntime.from_data(runtimes.resolve(name, config, env).to_data(env))
        for name in chosen
    }


async def sync_files_method(request: m.SyncRequest, session: Session, send: Send) -> Message:
    """troupe sync: sweep hand edits into config, then make every file what config says, rewriting
    files git merged from troupe's versions (spec: config-files, "Sync makes the files say what
    config says")."""
    store = open_event_store(session)
    synced = sync_config(
        session.theatre,
        store,
        _request(
            session,
            send,
            force=bool(request.force),
            rehearse=bool(request.rehearse),
            resolve_all=True,
        ),
    )
    return m.SyncResult(
        edits=[
            m.HandEdit(
                path=f"{THEATRE_DIR}/{edit.path}",
                change=synced.sweep_change,
                entries=[dict(e) for e in edit.entries],
            )
            for edit in synced.edits
        ],
        files=_files(synced.actions, synced.kept, synced.resolved),
        notices=_notices(
            synced.notices,
            file_notices(synced) if not request.rehearse else [],
            store.notices(),
        ),
    )


def _round_trip(store: EventStore, change: str) -> abandoned.RoundTrip:
    """The round trip the sweep ``change`` closed, or refused with ``config.no-round-trip``."""
    trip = abandoned.round_trip(store.history(aggregate.STREAM), change)
    if trip is None:
        raise TroupeError(
            "config.no-round-trip",
            problem=f"Change {change} put no config file back to what it was, so there's nothing "
            "to drop or keep.",
            fix="Use the change id the notice about the abandoned edit names; troupe sync repeats "
            "it while the edit can be dropped.",
            details={"change": change},
        )
    return trip


def _kept_error(change: str, block: abandoned.Blocked) -> TroupeError:
    details: dict[str, Any] = {"change": change, "reason": block.reason}
    if block.blocker is not None:
        details["blocker"] = block.blocker
    return TroupeError(
        "config.round-trip-kept",
        problem=f"The changes of {change} can't be dropped: {block.describe()}.",
        fix=f"Nothing to do: they stay in history. troupe config keep {change} stops troupe "
        "asking about them.",
        details=details,
    )


def _in_stream(store: EventStore) -> frozenset[str]:
    """Every change id in the config stream: what the keep record may still name."""
    return frozenset(
        str((r.lineage or {}).get("change", "")) for r in store.history(aggregate.STREAM)
    )


def _guard(session: Session, send: Send, rehearse: bool) -> AbstractContextManager[None]:
    troupe_dir = session.theatre / THEATRE_DIR
    return nullcontext() if rehearse else locked(troupe_dir, _waiting(send))


async def config_drop(request: m.ConfigDropRequest, session: Session, send: Send) -> Message:
    """Drop an abandoned edit: remove its round trip's events, only while that's safe (spec:
    config-hand-edits, "A person drops or keeps an abandoned edit"; abandoned-edits design D6).
    Holding the config files' lock, so no sweep runs meanwhile; the store re-checks runs and
    later changes holding its own lock, so none can be recorded between the check and the
    removal. No config file is written: each already holds what config goes back to."""
    store = open_event_store(session)
    troupe_dir = session.theatre / THEATRE_DIR
    rehearse = bool(request.rehearse)
    with _guard(session, send, rehearse):
        trip = _round_trip(store, request.change)
        block = abandoned.blocked(store, trip)
        if block is not None:
            raise _kept_error(request.change, block)
        if rehearse:
            paths = sorted({r.path for e in trip.events for r in store.recorder.recordings(e)})
        else:

            def check() -> None:
                again = abandoned.referred(store, trip)
                if again is not None:
                    raise _kept_error(request.change, again)

            paths = list(store.recorder.drop(trip.events, check))
        held, notices = abandoned.kept(troupe_dir)
        if not rehearse and request.change in held:
            abandoned.write_kept(troupe_dir, held - {request.change}, _in_stream(store))
    return m.ConfigDropResult(
        change=request.change,
        changes=list(trip.changes),
        segments=[
            Path(p).resolve().relative_to(session.theatre.resolve()).as_posix() for p in paths
        ],
        rehearsed=rehearse,
        notices=_notices(notices, store.notices()),
    )


async def config_keep(request: m.ConfigKeepRequest, session: Session, send: Send) -> Message:
    """Keep an abandoned edit, and stop troupe asking about it: recorded in this clone only
    (abandoned-edits design D6, D7)."""
    store = open_event_store(session)
    troupe_dir = session.theatre / THEATRE_DIR
    rehearse = bool(request.rehearse)
    with _guard(session, send, rehearse):
        _round_trip(store, request.change)
        held, notices = abandoned.kept(troupe_dir)
        if not rehearse:
            abandoned.write_kept(troupe_dir, held | {request.change}, _in_stream(store))
    return m.ConfigKeepResult(change=request.change, rehearsed=rehearse, notices=_notices(notices))


async def _config_drop(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await config_drop(request, session, send)


async def _config_keep(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await config_keep(request, session, send)


async def _config_set(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await config_set(request, session, send)


async def _config_get(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await config_get(request, session, send)


async def _sync(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await sync_files_method(request, session, send)


def methods() -> Mapping[str, Method]:
    """The commands and queries config offers through the client protocol, by name."""
    return {
        "config-set": Method(m.ConfigSetRequest, _config_set),
        "config-get": Method(m.ConfigGetRequest, _config_get),
        "sync": Method(m.SyncRequest, _sync),
        "config-drop": Method(m.ConfigDropRequest, _config_drop),
        "config-keep": Method(m.ConfigKeepRequest, _config_keep),
    }

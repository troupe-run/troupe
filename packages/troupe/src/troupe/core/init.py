"""troupe init: make a theatre, and with an audition, a working example actor in it (spec: cli,
config, client-protocol; init-and-audition design D1, D2, D8).

The session's theatre is the directory to make the theatre in: there is none yet, so no surface can
find one. Everything is checked before anything is made (design D2): a theatre here or above, a
repository to hold it, the audition's runner and config, and who is acting. Then ``.troupe/`` is
made with the git files every write keeps, and the audition is recorded through config-set's own
path, so its change is exactly what ``troupe config set`` would record (design D3).

If making or recording fails before anything is recorded, the ``.troupe/`` this command made is
removed, so trying again isn't blocked by a half-made theatre. Once the change is recorded, the
theatre stays, and the next command's flush finishes any file not yet in place (config-model
design D9).
"""

import shutil
from collections.abc import Mapping
from typing import Any

from troupe.core import defaults, interim
from troupe.core.audition import ACTOR, Audition, audition
from troupe.core.client import messages as m
from troupe.core.client.dispatch import Method, Send
from troupe.core.client.session import Session
from troupe.core.config.changes import apply, change
from troupe.core.config.commands import record_change
from troupe.core.config.kinds import check
from troupe.core.config.projection import render
from troupe.core.events.lineage import Actor
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, env_name, read_unenforced_local_stage
from troupe.core.stores import open_event_store
from troupe.core.theatre import GIT_FILES, THEATRE_DIR, ensure_git_files, refuse_existing
from troupe.core.vcs import load_vcs
from troupe_plugin_sdk.messages import Message

MADE = "made by troupe init"
"""The reason each file init writes is reported with."""

EVENTS_DIR = "events"
"""Where a theatre's events are recorded (reserved in .troupe/; spec: config-files): a failed init
removes its theatre only while nothing is recorded there."""


def _git_files() -> list[m.FileAction]:
    return [
        m.FileAction(path=f"{THEATRE_DIR}/{name}", action="write", reason=MADE)
        for name, _patterns in GIT_FILES
    ]


def _steps(session: Session, chosen: Audition) -> list[m.InitStep]:
    """What to do next, as data (design D8): commit, allow the local stage when the session's policy
    doesn't (a malformed policy value fails here, as it would fail perform), then perform."""
    steps: list[m.InitStep] = [m.CommitStep(paths=[THEATRE_DIR])]
    if not read_unenforced_local_stage(session.env).value:
        steps.append(
            m.AllowLocalStageStep(variable=env_name(ALLOW_UNENFORCED_LOCAL_STAGE), value="true")
        )
    # The extra a runner comes with is its own name (runner-extras design D1, D8).
    extra = chosen.runner if interim.RUNNERS[chosen.runner].in_extra else None
    steps.append(
        m.PerformStep(actor=ACTOR, runner=chosen.runner, direction=chosen.direction, extra=extra)
    )
    return steps


async def init(request: m.InitRequest, session: Session, send: Send) -> Message:
    directory = session.theatre.absolute()
    troupe_dir = directory / THEATRE_DIR
    # 1. No theatre here or above; 2. a repository to hold one.
    refuse_existing(directory)
    load_vcs(defaults.VCS, directory).check_repository()
    # 3. The audition's runner is known, and its actor is valid config.
    chosen = None if request.audition is None else audition(request.audition.runner)
    operations = [] if chosen is None else chosen.operations()
    entries = change({}, operations)
    after = apply({}, entries)
    check(after)
    # 4. Who is acting, before anything is made. Opening the store writes nothing.
    store = open_event_store(session)
    actor: Actor | None = None if chosen is None else store.identify()
    steps = [] if chosen is None else _steps(session, chosen)
    named = None if chosen is None else m.InitActor(name=ACTOR, runner=chosen.runner)
    if request.rehearse:
        would = _git_files() + [
            m.FileAction(path=f"{THEATRE_DIR}/{path}", action="write", reason=MADE)
            for path in sorted(render(after))
        ]
        return m.InitResult(
            rehearsed=True, files=would, actor=named, entries=entries, steps=steps, notices=[]
        )
    # 5. Make the theatre. mkdir refuses a .troupe made since step 1, as theatre.exists does.
    try:
        troupe_dir.mkdir()
    except FileExistsError:
        refuse_existing(directory)
        raise
    try:
        ensure_git_files(troupe_dir)
        if chosen is None:
            return m.InitResult(
                rehearsed=False, files=_git_files(), entries=[], steps=[], notices=[]
            )
        # 6. Record the audition, as config set would.
        recorded = record_change(session, store, operations, reason=None, send=send, actor=actor)
    except BaseException:
        events = troupe_dir / EVENTS_DIR
        if not (events.is_dir() and any(events.iterdir())):
            shutil.rmtree(troupe_dir, ignore_errors=True)
        raise
    return m.InitResult(
        rehearsed=False,
        files=_git_files() + recorded.files,
        actor=named,
        change=recorded.change,
        entries=recorded.entries,
        steps=steps,
        notices=recorded.notices,
    )


async def _init(request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
    return await init(request, session, send)


def methods() -> Mapping[str, Method]:
    """The command init offers through the client protocol."""
    return {"init": Method(m.InitRequest, _init)}

"""The client protocol's messages as Python types (spec: client-protocol; perform-status-logs
design D2).

The JSON Schemas in protocol/schemas/client/ are the source of truth (decision #7). These types
mirror them by hand, and the tests check every type against the schemas. ``from_data`` is strict:
anything a schema refuses raises ProtocolError, which the dispatcher reports as
client.invalid-request, naming where.
"""

import re
from dataclasses import dataclass
from typing import ClassVar, Literal

from troupe.core.messages import Message, ProtocolError, decode, fail, json_field
from troupe.core.notices import CODES as NOTICE_CODES
from troupe.core.notices import Notice
from troupe.core.runners import protocol as p

ACTOR_NAME = re.compile(r"\A[a-z][a-z0-9-]{0,63}\Z")
RUNNER_NAME = ACTOR_NAME
RUN_REF = re.compile(r"\A[0-9a-f]{8}[0-9a-f-]{0,28}\Z")
THEATRE_PATH = re.compile(r"\A(?![/\\])(?![A-Za-z]:)(?!.*\\)(?!(.*/)?\.\.(/|\Z)).+\Z")
TIME = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z")
SETTING = re.compile(r"\A[a-z][a-z0-9_]*\Z")
STAGE_NAME = re.compile(r"\A[a-z][a-z0-9-]*\Z")
CODE = re.compile(r"\A[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+\Z")
STATUS_LIMIT_MAX = 10000
"""The schema's upper bound on status's limit."""

State = Literal["running", "ended", "interrupted", "unfinished-elsewhere"]
OutcomeName = Literal["succeeded", "failed", "cancelled", "timed-out", "crashed", "could-not-start"]


class Tagged(Message):
    """A client message that is one of several kinds, told apart by ``kind``."""

    TYPE_FIELD: ClassVar[str] = "kind"


# What perform is asked to run.


@dataclass(frozen=True)
class NoEffectCheck(Tagged):
    TYPE: ClassVar[str | None] = "none"


@dataclass(frozen=True)
class FilesEffectCheck(Tagged):
    """Each file must exist after the run and differ from before it."""

    TYPE: ClassVar[str | None] = "files"
    paths: list[str] = json_field("paths", min_items=1, unique=True)

    def _check(self, where: str) -> None:
        for index, path in enumerate(self.paths):
            if not THEATRE_PATH.match(path):
                raise fail(
                    f"{where}.paths[{index}]",
                    f"{path!r} must be relative to the theatre, with / separators, and stay in it",
                )


EffectCheck = NoEffectCheck | FilesEffectCheck


@dataclass(frozen=True)
class PerformRequest(Message):
    """Run an actor as config defines it: the request names only the actor, the run's direction
    and whether to rehearse (config-model design D14)."""

    actor: str = json_field("actor", pattern=ACTOR_NAME)
    direction: str | None = json_field("direction", default=None)
    rehearse: bool | None = json_field("rehearse", default=None)


# A run as status and logs report it.


@dataclass(frozen=True)
class ActorData(Message):
    """An actor, as lineage records it (lineage.schema.json#/$defs/actor)."""

    kind: Literal["human", "agent", "unknown"] = json_field("kind")
    id: str | None = json_field("id", default=None, min_length=1)
    source: str | None = json_field("source", default=None, min_length=1)

    def _check(self, where: str) -> None:
        if (self.kind == "unknown") != (self.id is None and self.source is None):
            raise fail(where, "an unknown actor has only a kind; any other has an id and source")
        if self.kind != "unknown" and (self.id is None or self.source is None):
            raise fail(where, "a human or agent actor has an id and a source")


@dataclass(frozen=True)
class AllowanceData(Message):
    setting: str = json_field("setting", pattern=SETTING)
    source: str = json_field("source", min_length=1)


@dataclass(frozen=True)
class StageData(Message):
    """Where a run's actor ran, as lineage records it (lineage.schema.json#/$defs/stage)."""

    name: str = json_field("name", pattern=STAGE_NAME)
    effects: Literal["enforced", "unenforced"] = json_field("effects")
    allowed_by: AllowanceData | None = json_field("allowedBy", default=None)

    def _check(self, where: str) -> None:
        if (self.effects == "unenforced") != (self.allowed_by is not None):
            raise fail(where, "allowedBy names what allowed it exactly when effects are unenforced")


@dataclass(frozen=True)
class ReportedRunner(Message):
    name: str = json_field("name", min_length=1)
    version: str = json_field("version", min_length=1)


@dataclass(frozen=True)
class RunnerData(Message):
    requested: str = json_field("requested", pattern=RUNNER_NAME)
    reported: ReportedRunner | None = json_field("reported", default=None)


@dataclass(frozen=True)
class RecordingFailure(Message):
    failed_at: int = json_field("failedAt", minimum=0)
    error: p.ErrorData = json_field("error")


COMMIT = re.compile(r"\A[0-9a-f]{40}([0-9a-f]{24})?\Z")
PREFIX = re.compile(r"\A(?![/\\])(?!.*\\)(?!(.*/)?\.\.(/|\Z)).+/\Z")
CloneMechanism = Literal["clonefile", "ficlone", "copyfile2", "copy", "symlink"]


@dataclass(frozen=True)
class TheatreWorkspace(Tagged):
    """A run that worked in the theatre itself."""

    TYPE: ClassVar[str | None] = "theatre"


@dataclass(frozen=True)
class WorktreeWorkspace(Tagged):
    """A run that works in its own worktree (worktree-stage design D7). ``clones`` is None until
    the worktree is made (account-for-every-worktree design D4)."""

    TYPE: ClassVar[str | None] = "worktree"
    path: str = json_field("path", pattern=THEATRE_PATH)
    base: str = json_field("base", pattern=COMMIT)
    dirty: bool = json_field("dirty")
    prefix: str | None = json_field("prefix", default=None, pattern=PREFIX)
    clones: list[CloneMechanism] | None = json_field("clones", default=None, unique=True)


Workspace = TheatreWorkspace | WorktreeWorkspace


@dataclass(frozen=True)
class SharedChangeData(Message):
    name: str = json_field("name", min_length=1)
    change: Literal["added", "changed", "removed"] = json_field("change")


@dataclass(frozen=True)
class SharedData(Message):
    """What changed during a run in the state the repository's worktrees share."""

    refs: list[SharedChangeData] | None = json_field("refs", default=None, min_items=1)
    config: list[SharedChangeData] | None = json_field("config", default=None, min_items=1)
    hooks: list[SharedChangeData] | None = json_field("hooks", default=None, min_items=1)

    def _check(self, where: str) -> None:
        if self.refs is None and self.config is None and self.hooks is None:
            raise fail(where, "names at least one of refs, config and hooks")


ChangesState = Literal["pending", "accepted", "discarded", "none", "uncaptured"]


@dataclass(frozen=True, kw_only=True)
class ChangesData(Message):
    """A worktree run's changes, and what has been done with them."""

    state: ChangesState = json_field("state")
    diff: str | None = json_field("diff", default=None, pattern=p.REF_PATTERN)
    added: int | None = json_field("added", default=None, minimum=0)
    modified: int | None = json_field("modified", default=None, minimum=0)
    deleted: int | None = json_field("deleted", default=None, minimum=0)
    left_out: int | None = json_field("leftOut", default=None, minimum=0)
    shared: SharedData | None = json_field("shared", default=None)
    error: p.ErrorData | None = json_field("error", default=None)
    settled_at: str | None = json_field("settledAt", default=None, pattern=TIME)
    worktree: str | None = json_field("worktree", default=None, pattern=THEATRE_PATH)

    def _check(self, where: str) -> None:
        if self.state == "pending" and (self.diff is None or self.worktree is None):
            raise fail(where, "pending changes have a diff and a worktree")
        if self.state in ("none", "uncaptured") and (self.diff is not None or not self.worktree):
            raise fail(where, f"{self.state} changes have a worktree and no diff")
        settled = self.state in ("accepted", "discarded")
        if settled != (self.settled_at is not None):
            raise fail(where, "settledAt is present exactly when state is accepted or discarded")
        if settled and self.worktree is not None:
            raise fail(where, "settled changes have no worktree")


@dataclass(frozen=True, kw_only=True)
class RunSummary(Message):
    """A run as status, logs and perform report it. A field with nothing to say is left out; an
    ended run, and only an ended one, has an outcome and an end time."""

    run_id: str = json_field("runId", pattern=p.RUN_ID_PATTERN)
    actor: str = json_field("actor", pattern=ACTOR_NAME)
    started_by: ActorData = json_field("startedBy")
    runner: RunnerData = json_field("runner")
    stage: StageData = json_field("stage")
    effect_check: EffectCheck = json_field("effectCheck")
    workspace: Workspace = json_field("workspace")
    state: State = json_field("state")
    outcome: OutcomeName | None = json_field("outcome", default=None)
    error: p.ErrorData | None = json_field("error", default=None)
    events: int = json_field("events", minimum=0)
    started_at: str = json_field("startedAt", pattern=TIME)
    ended_at: str | None = json_field("endedAt", default=None, pattern=TIME)
    transcript: str | None = json_field("transcript", default=None, pattern=p.REF_PATTERN)
    stderr: str | None = json_field("stderr", default=None, pattern=p.REF_PATTERN)
    recording: RecordingFailure | None = json_field("recording", default=None)
    changes: ChangesData | None = json_field("changes", default=None)

    def _check(self, where: str) -> None:
        ended = self.state == "ended"
        if ended != (self.outcome is not None) or ended != (self.ended_at is not None):
            raise fail(where, "outcome and endedAt are present exactly when state is ended")
        if isinstance(self.workspace, WorktreeWorkspace) != (self.changes is not None):
            raise fail(where, "changes are present exactly when the workspace is a worktree")


HostEvent = (
    p.InitEvent
    | p.TurnEvent
    | p.ToolCallEvent
    | p.ToolResultEvent
    | p.RetryEvent
    | p.LogEvent
    | p.ResultEvent
    | p.OversizedEvent
)
"""A run event as troupe passes it on: the runner's, or the oversized stand-in for one."""


@dataclass(frozen=True)
class LoggedEvent(Tagged):
    """One run event as recorded, and when troupe recorded it."""

    TYPE: ClassVar[str | None] = "event"
    run_id: str = json_field("runId", pattern=p.RUN_ID_PATTERN)
    seq: int = json_field("seq", minimum=0)
    at: str = json_field("at", pattern=TIME)
    event: HostEvent = json_field("event")

    def _check(self, where: str) -> None:
        if self.event.run_id != self.run_id or self.event.seq != self.seq:
            raise fail(where, "the event's runId and seq must be the logged event's own")


@dataclass(frozen=True)
class NoticeData(Message):
    """A notice (notice.schema.json)."""

    code: str = json_field("code", pattern=CODE)
    problem: str = json_field("problem", min_length=1)
    fix: str = json_field("fix", min_length=1)
    path: str | None = json_field("path", default=None, min_length=1)
    details: dict[str, object] | None = json_field("details", default=None)

    @classmethod
    def of(cls, notice: Notice) -> "NoticeData":
        return cls.from_data(notice.to_data())

    def to_notice(self) -> Notice:
        if self.code not in NOTICE_CODES:
            raise ProtocolError(f"notice: {self.code!r} isn't a notice code troupe declares")
        return Notice(self.code, self.problem, self.fix, self.path, dict(self.details or {}))


# Updates.


@dataclass(frozen=True)
class Started(Tagged):
    TYPE: ClassVar[str | None] = "started"
    run_id: str = json_field("runId", pattern=p.RUN_ID_PATTERN)
    worktree: str | None = json_field("worktree", default=None, pattern=THEATRE_PATH)


@dataclass(frozen=True)
class NoticeUpdate(Tagged):
    TYPE: ClassVar[str | None] = "notice"
    notice: NoticeData = json_field("notice")


PerformUpdate = Started | LoggedEvent | NoticeUpdate
LogsUpdate = LoggedEvent | NoticeUpdate


# Results and the queries' requests.


@dataclass(frozen=True)
class TextSummary(Message):
    """Text a rehearsal names without showing: its hash and length."""

    hash: str = json_field("hash", pattern=p.REF_PATTERN)
    length: int = json_field("length", minimum=0)


@dataclass(frozen=True)
class RehearsedWorkspace(Message):
    """Where a rehearsed perform would work: its own worktree made at ``base``, or the theatre."""

    kind: Literal["worktree", "theatre"] = json_field("kind")
    base: str | None = json_field("base", default=None, pattern=COMMIT)

    def _check(self, where: str) -> None:
        if (self.kind == "worktree") != (self.base is not None):
            raise fail(where, "base is present exactly when kind is worktree")


@dataclass(frozen=True, kw_only=True)
class Rehearsal(Message):
    """What a perform would run, after every check it makes before starting the runner."""

    actor: str = json_field("actor", pattern=ACTOR_NAME)
    runner: str = json_field("runner", pattern=RUNNER_NAME)
    stage: StageData = json_field("stage")
    effect_check: EffectCheck = json_field("effectCheck")
    config: list[str] = json_field("config", min_items=1)
    character: TextSummary | None = json_field("character", default=None)
    direction: TextSummary | None = json_field("direction", default=None)
    workspace: RehearsedWorkspace = json_field("workspace")


@dataclass(frozen=True)
class PerformResult(Message):
    """The run as recorded, or, for a rehearsal, what would run: exactly one."""

    run: RunSummary | None = json_field("run", default=None)
    rehearsal: Rehearsal | None = json_field("rehearsal", default=None)

    def _check(self, where: str) -> None:
        if (self.run is None) == (self.rehearsal is None):
            raise fail(where, "has exactly one of run and rehearsal")


@dataclass(frozen=True)
class StatusRequest(Message):
    run: str | None = json_field("run", default=None, pattern=RUN_REF)
    limit: int | None = json_field("limit", default=None, minimum=1)

    def _check(self, where: str) -> None:
        if self.run is not None and self.limit is not None:
            raise fail(where, "give a run or a limit, not both: a limit is for a list")
        if self.limit is not None and self.limit > STATUS_LIMIT_MAX:
            raise fail(f"{where}.limit", f"must be at most {STATUS_LIMIT_MAX}")


@dataclass(frozen=True)
class StatusResult(Message):
    runs: list[RunSummary] = json_field("runs")
    notices: list[NoticeData] = json_field("notices")


@dataclass(frozen=True)
class LogsRequest(Message):
    run: str = json_field("run", pattern=RUN_REF)
    follow: bool | None = json_field("follow", default=None)


@dataclass(frozen=True)
class LogsResult(Message):
    run: RunSummary = json_field("run")
    events: list[LoggedEvent] = json_field("events")
    notices: list[NoticeData] = json_field("notices")


# Config (spec: config, config-files; config-model design D10).

ULID = re.compile(r"\A[0-9A-HJKMNP-TV-Z]{26}\Z")
HASH = re.compile(r"\Asha256:[0-9a-f]{64}\Z")


def _check_path(path: list[str], where: str) -> None:
    if not path:
        raise fail(where, "must name at least one key")
    for index, key in enumerate(path):
        if not key:
            raise fail(f"{where}[{index}]", "must not be empty")


@dataclass(frozen=True)
class ConfigOperation(Message):
    """Set the value or group at ``path``, or unset it: exactly one of ``value`` and ``unset``."""

    path: list[str] = json_field("path", min_items=1)
    value: object | None = json_field("value", default=None)
    unset: bool | None = json_field("unset", default=None)

    def _check(self, where: str) -> None:
        _check_path(self.path, f"{where}.path")
        if self.unset is False:
            raise fail(f"{where}.unset", "must be true: to set a value, give value instead")
        if (self.value is None) == (self.unset is None):
            raise fail(where, "give exactly one of value and unset")


@dataclass(frozen=True)
class ConfigSetRequest(Message):
    operations: list[ConfigOperation] = json_field("operations", min_items=1)
    reason: str | None = json_field("reason", default=None, min_length=1)
    rehearse: bool | None = json_field("rehearse", default=None)


@dataclass(frozen=True)
class FileAction(Message):
    path: str = json_field("path", pattern=THEATRE_PATH)
    action: Literal["write", "remove", "finish", "discard"] = json_field("action")
    reason: str = json_field("reason", min_length=1)
    kept: str | None = json_field("kept", default=None, pattern=HASH)


@dataclass(frozen=True)
class ConfigSetResult(Message):
    entries: list[dict[str, object]] = json_field("entries")
    files: list[FileAction] = json_field("files")
    notices: list[NoticeData] = json_field("notices")
    change: str | None = json_field("change", default=None, pattern=ULID)


@dataclass(frozen=True)
class ConfigGetRequest(Message):
    path: list[str] | None = json_field("path", default=None, min_items=1)

    def _check(self, where: str) -> None:
        if self.path is not None:
            _check_path(self.path, f"{where}.path")


@dataclass(frozen=True)
class ConflictingChange(Message):
    change: str = json_field("change", pattern=ULID)
    actor: ActorData = json_field("actor")
    at: str = json_field("at", pattern=TIME)
    entries: list[dict[str, object]] = json_field("entries")


@dataclass(frozen=True)
class ConflictData(Message):
    paths: list[list[str]] = json_field("paths", min_items=1)
    changes: list[ConflictingChange] = json_field("changes", min_items=2)
    rule: str | None = json_field("rule", default=None, min_length=1)


@dataclass(frozen=True)
class ConfigGetResult(Message):
    conflicts: list[ConflictData] = json_field("conflicts")
    heads: list[str] = json_field("heads")
    notices: list[NoticeData] = json_field("notices")
    value: object | None = json_field("value", default=None)


@dataclass(frozen=True)
class FlushRequest(Message):
    force: bool | None = json_field("force", default=None)
    rehearse: bool | None = json_field("rehearse", default=None)


@dataclass(frozen=True)
class FlushResult(Message):
    files: list[FileAction] = json_field("files")
    notices: list[NoticeData] = json_field("notices")


ConfigUpdate = NoticeUpdate


def parse_update(kind: object, data: object) -> Message:
    """An update for a method whose updates are ``kind`` (PerformUpdate or LogsUpdate)."""
    message = decode(kind, data, "update")
    if not isinstance(message, Message):
        raise TypeError(f"{kind!r} isn't a union of tagged messages")
    return message


# A worktree run's changes: diff, accept and discard (worktree-stage design D6).


@dataclass(frozen=True)
class DiffRequest(Message):
    run: str = json_field("run", pattern=RUN_REF)


@dataclass(frozen=True, kw_only=True)
class DiffResult(Message):
    """A worktree run's captured diff, as the artifact store holds it."""

    run: str = json_field("run", pattern=p.RUN_ID_PATTERN)
    base: str = json_field("base", pattern=COMMIT)
    changes: ChangesData = json_field("changes")
    patch: str | None = json_field("patch", default=None)
    encoding: Literal["utf-8", "base64"] | None = json_field("encoding", default=None)

    def _check(self, where: str) -> None:
        if (self.patch is None) != (self.encoding is None):
            raise fail(where, "encoding is present exactly when patch is")


@dataclass(frozen=True)
class AcceptRequest(Message):
    run: str = json_field("run", pattern=RUN_REF)
    reason: str | None = json_field("reason", default=None, min_length=1)
    rehearse: bool | None = json_field("rehearse", default=None)


@dataclass(frozen=True)
class AcceptResult(Message):
    run: str = json_field("run", pattern=p.RUN_ID_PATTERN)
    files: list[str] = json_field("files", min_items=1)
    rehearsed: bool = json_field("rehearsed")
    notices: list[NoticeData] = json_field("notices")


@dataclass(frozen=True)
class DiscardRequest(Message):
    run: str = json_field("run", pattern=RUN_REF)
    reason: str | None = json_field("reason", default=None, min_length=1)
    rehearse: bool | None = json_field("rehearse", default=None)


@dataclass(frozen=True)
class DiscardResult(Message):
    run: str = json_field("run", pattern=p.RUN_ID_PATTERN)
    worktree: str = json_field("worktree", pattern=THEATRE_PATH)
    rehearsed: bool = json_field("rehearsed")
    notices: list[NoticeData] = json_field("notices")

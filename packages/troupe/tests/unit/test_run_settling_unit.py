"""diff, accept and discard of a worktree run's changes, in this process: runs recorded in a theatre
with no version control, the diff in an in-memory artifact store, and a stand-in for the git work
(checking and applying a diff, removing a worktree) that records what it's asked (spec:
run-workspaces; worktree-stage design D6, D7).

The same commands against a git theatre are in integration/test_run_changes.py, and the schema
checks of a run's changes in test_run_changes_unit.py."""

import asyncio
import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from runtesting import STAGE, outcome
from storetesting import ADA, Counter
from troupe.core.artifacts import MemoryArtifactStore
from troupe.core.client import messages as m
from troupe.core.client.session import Session
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.identity import Identity
from troupe.core.runs import changes
from troupe.core.runs.aggregate import Run
from troupe.core.runs.backends import Backends, lease_dir
from troupe.core.vcs import Applicability
from troupe.core.workspaces import worktree_path
from troupe_plugin_sdk.messages import Message
from troupe_store_text.store import TextStore
from troupe_vcs_files import FilesAdapter

BASE = "c0ffee" + "0" * 34
PATCH = b"--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
WORKTREE = ".troupe/local/worktrees/"
BRIEF = {
    "actor": "tester",
    "outcome": "succeeded",
    "diff": "sha256:" + "d" * 64,
    "added": 1,
    "modified": 0,
    "deleted": 0,
}


class Git(FilesAdapter):
    """The files adapter, with git's diff and worktree work stood in for: each call is recorded,
    and what it answers is set by the test."""

    def __init__(self, theatre: Path) -> None:
        super().__init__(theatre)
        self.calls: list[tuple[str, Any]] = []
        self.failing: tuple[str, ...] = ()
        self.applied: tuple[str, ...] = ("a.txt",)
        self.remove_error: TroupeError | None = None
        self.consume = False
        """Remove the diff file while applying it, as nothing troupe runs does, but might."""

    def check_apply(self, diff: Path) -> Applicability:
        self.calls.append(("check_apply", diff.read_bytes()))
        return Applicability(files=("a.txt", "b.txt"), failing=self.failing)

    def apply(self, diff: Path) -> tuple[str, ...]:
        self.calls.append(("apply", diff.read_bytes()))
        if self.consume:
            diff.unlink()
        return self.applied

    def remove_worktree(self, path: Path) -> None:
        self.calls.append(("remove_worktree", path))
        if self.remove_error is not None:
            raise self.remove_error


class Theatre:
    """A theatre with recorded runs, its artifact store and the updates a command sent."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.git = Git(path)
        self.store = EventStore(
            path,
            vcs=self.git,
            recorder=TextStore(path, self.git),
            env=ADA,
        )
        self.artifacts = MemoryArtifactStore()
        self.sent: list[Any] = []
        self.backends = Backends(event_store=self._event_store, artifact_store=self._artifact_store)

    def _event_store(self, session: Session) -> EventStore:
        assert session.theatre == self.path
        return self.store

    def _artifact_store(self, session: Session) -> MemoryArtifactStore:
        assert session.theatre == self.path
        return self.artifacts

    def run(
        self,
        captured: dict[str, Any] | None = None,
        *,
        kind: str = "worktree",
        ended: bool = True,
        patch: bytes = PATCH,
    ) -> Run:
        workspace: dict[str, Any] = {"kind": kind}
        run_id = str(uuid4())
        if kind == "worktree":
            workspace |= {"path": WORKTREE + run_id, "base": BASE, "dirty": False}
            worktree_path(self.path, run_id).mkdir(parents=True)  # as perform made it
        made = Run(
            run_id=run_id,
            actor="tester",
            runner_requested="scripted",
            stage=STAGE,
            effect_check={"kind": "none"},
            direction="sha256:" + "a" * 64,
            config=["sha256:" + "b" * 64],
            workspace=workspace,
            on_context_full={"value": "fail", "source": "default"},
            approvers=(
                {"value": ["troupe", "director"], "source": "default"}
                if kind == "worktree"
                else None
            ),
        )
        if ended:
            if captured is None and kind == "worktree":
                captured = {
                    "diff": self.artifacts.put(patch),
                    "added": 1,
                    "modified": 1,
                    "deleted": 0,
                    "leftOut": 0,
                }
            made.end(outcome("succeeded"), None, captured)
        self.record(made)
        return made

    def record(self, run: Run) -> None:
        self.store.command(via="cli").record(run.collect_events())

    def call(self, command: Callable[..., Any], request: Message) -> Any:  # noqa: ANN401
        session = Session(theatre=self.path, env=dict(ADA))
        return asyncio.run(command(request, session, self.sent.append, backends=self.backends))

    def topics(self, run: Run) -> list[str]:
        return [e.topic.split(":")[1] for e in self.store.history(UUID(run.run_id))]

    def last(self, run: Run) -> Any:  # noqa: ANN401
        return self.store.history(UUID(run.run_id))[-1]


@pytest.fixture
def theatre(tmp_path: Path) -> Theatre:
    return Theatre(tmp_path)


def _refusal(theatre: Theatre, command: Callable[..., Any], request: Message) -> TroupeError:
    with pytest.raises(TroupeError) as caught:
        theatre.call(command, request)
    return caught.value


def _ref(run: Run) -> str:
    return run.run_id[:8]


def _worktree(run: Run) -> str:
    return WORKTREE + run.run_id


# diff


def test_diff_shows_a_utf8_patch_as_text(theatre: Theatre) -> None:
    run = theatre.run()
    result = theatre.call(changes.diff, m.DiffRequest(_ref(run)))
    assert result.run == run.run_id
    assert result.base == BASE
    assert result.patch == PATCH.decode("utf-8")
    assert result.encoding == "utf-8"
    assert result.changes.to_data() == {
        "state": "pending",
        "diff": theatre.artifacts.put(PATCH),
        "added": 1,
        "modified": 1,
        "deleted": 0,
        "leftOut": 0,
        "worktree": _worktree(run),
    }
    assert theatre.sent == []


def test_diff_shows_a_patch_that_isnt_utf8_as_base64(theatre: Theatre) -> None:
    binary = b"\xff\xfe binary"
    run = theatre.run(patch=binary)
    result = theatre.call(changes.diff, m.DiffRequest(_ref(run)))
    assert result.encoding == "base64"
    assert result.patch == base64.b64encode(binary).decode("ascii")


def test_diff_of_a_run_that_changed_nothing_has_no_patch(theatre: Theatre) -> None:
    run = theatre.run({"added": 0, "modified": 0, "deleted": 0, "leftOut": 0})
    result = theatre.call(changes.diff, m.DiffRequest(_ref(run)))
    assert result.run == run.run_id
    assert result.base == BASE
    assert result.patch is None
    assert result.encoding is None
    assert result.changes.to_data()["state"] == "none"


def test_diff_of_accepted_changes_still_shows_them(theatre: Theatre) -> None:
    run = theatre.run()
    theatre.call(changes.accept, m.AcceptRequest(_ref(run)))
    result = theatre.call(changes.diff, m.DiffRequest(_ref(run)))
    assert result.patch == PATCH.decode("utf-8")
    assert result.changes.to_data()["state"] == "accepted"


def test_diff_of_an_interrupted_run_that_was_discarded_has_no_patch(theatre: Theatre) -> None:
    run = theatre.run(ended=False)
    lease_dir(theatre.path, run.run_id).mkdir(parents=True)
    theatre.call(changes.discard, m.DiscardRequest(_ref(run)))
    result = theatre.call(changes.diff, m.DiffRequest(_ref(run)))
    assert result.patch is None
    assert result.changes.to_data()["state"] == "discarded"


def test_diff_of_a_theatre_run_is_refused_as_not_a_worktree(theatre: Theatre) -> None:
    run = theatre.run(kind="theatre")
    error = _refusal(theatre, changes.diff, m.DiffRequest(_ref(run)))
    assert error.code == "run.not-a-worktree"
    assert error.problem == (
        f"Run {run.run_id} worked in the theatre, so its changes are already among your files: "
        "there is nothing to show, accept or discard."
    )
    assert error.fix == "Use git to see what it changed: git status, git diff."
    assert error.details == {"run": run.run_id}


def test_diff_of_a_run_with_no_end_is_refused_as_not_ended(theatre: Theatre) -> None:
    run = theatre.run(ended=False)
    error = _refusal(theatre, changes.diff, m.DiffRequest(_ref(run)))
    assert error.code == "run.not-ended"
    assert error.problem == (
        f"Run {run.run_id} is unfinished-elsewhere: it has no recorded end, so its changes aren't "
        "captured."
    )
    assert error.fix == (
        f"Wait for it to end (troupe logs {_ref(run)} --follow), or discard it if it was "
        "interrupted."
    )
    assert error.details == {"run": run.run_id, "state": "unfinished-elsewhere"}


def test_diff_of_uncaptured_changes_is_refused_naming_the_worktree(theatre: Theatre) -> None:
    error_data = {
        "code": "vcs.failed",
        "problem": "p",
        "fix": "f",
        "details": {"command": "git diff", "exitStatus": 128},
    }
    run = theatre.run({"error": error_data})
    error = _refusal(theatre, changes.diff, m.DiffRequest(_ref(run)))
    assert error.code == "run.changes-uncaptured"
    assert (
        error.problem == f"Run {run.run_id}'s changes weren't captured, so they can't be accepted."
    )
    assert error.fix == (
        f"Look at what it wrote in {_worktree(run)}, then discard it: troupe discard {_ref(run)}"
    )
    assert error.path == _worktree(run)
    assert error.details == {"run": run.run_id, "worktree": _worktree(run), "error": error_data}


# accept


def test_accept_applies_the_diff_records_it_and_removes_the_worktree(theatre: Theatre) -> None:
    run = theatre.run()
    theatre.git.applied = ("a.txt", "c.txt")
    result = theatre.call(changes.accept, m.AcceptRequest(_ref(run), reason="looks right"))
    assert result == m.AcceptResult(
        run=run.run_id, files=["a.txt", "c.txt"], rehearsed=False, notices=[]
    )
    assert theatre.git.calls == [
        ("check_apply", PATCH),
        ("apply", PATCH),
        ("remove_worktree", worktree_path(theatre.path, run.run_id)),
    ]
    assert theatre.topics(run)[-1] == "Run.ChangesAccepted"
    accepted = theatre.last(run)
    assert accepted.lineage["reason"] == "looks right"
    assert accepted.lineage["via"] == "cli"
    actor = theatre.store.identify()
    assert isinstance(actor, Identity)
    assert accepted.lineage["actor"]["id"] == actor.id
    assert "approvals" not in accepted.lineage or accepted.lineage["approvals"] == []
    assert not list(worktree_path(theatre.path, run.run_id).parent.glob("*.accept.diff"))
    assert [p.name for p in lease_dir(theatre.path, run.run_id).iterdir()] == ["settle"]


def test_a_rehearsed_accept_checks_the_diff_and_changes_nothing(theatre: Theatre) -> None:
    run = theatre.run()
    result = theatre.call(changes.accept, m.AcceptRequest(_ref(run), rehearse=True))
    assert result == m.AcceptResult(
        run=run.run_id, files=["a.txt", "b.txt"], rehearsed=True, notices=[]
    )
    assert theatre.git.calls == [("check_apply", PATCH)]
    assert theatre.topics(run) == ["Run.Started", "Run.Ended"]
    assert not list(worktree_path(theatre.path, run.run_id).parent.glob("*.accept.diff"))


def test_a_diff_that_doesnt_apply_is_refused_changing_nothing(theatre: Theatre) -> None:
    run = theatre.run()
    theatre.git.failing = ("a.txt", "b.txt")
    error = _refusal(theatre, changes.accept, m.AcceptRequest(_ref(run)))
    assert error.code == "run.changes-conflict"
    assert error.problem == (
        f"Run {run.run_id}'s diff doesn't apply cleanly to your working tree: a.txt, b.txt changed "
        "since the run started. Nothing was changed."
    )
    assert error.fix == (
        f"See the diff with troupe diff {_ref(run)}, and the run's files in {_worktree(run)}. To "
        f"merge by hand: troupe diff {_ref(run)} | git apply --3way"
    )
    assert error.path == _worktree(run)
    assert error.details == {
        "run": run.run_id,
        "diff": theatre.artifacts.put(PATCH),
        "files": ["a.txt", "b.txt"],
        "worktree": _worktree(run),
    }
    assert theatre.git.calls == [("check_apply", PATCH)]
    assert theatre.topics(run) == ["Run.Started", "Run.Ended"]
    assert not list(worktree_path(theatre.path, run.run_id).parent.glob("*.accept.diff"))


def test_a_worktree_that_cant_be_removed_is_a_notice_after_accepting(theatre: Theatre) -> None:
    run = theatre.run()
    theatre.git.remove_error = TroupeError(
        "vcs.failed",
        problem="no",
        fix="f",
        details={"command": "git worktree remove", "exitStatus": 1},
    )
    result = theatre.call(changes.accept, m.AcceptRequest(_ref(run)))
    notice = m.NoticeData(
        code="workspace.not-removed",
        problem=f"Run {run.run_id}'s changes were accepted, and its worktree at {_worktree(run)} "
        "couldn't be removed.",
        fix=f"Remove it with git worktree remove --force {_worktree(run)}. Nothing in it is needed "
        "now.",
        path=str(theatre.path / _worktree(run)),
        details={"worktree": _worktree(run)},
    )
    assert result.notices == [notice]
    assert theatre.sent == [m.NoticeUpdate(notice=notice)]
    assert theatre.topics(run)[-1] == "Run.ChangesAccepted"


def test_accept_of_a_theatre_run_is_refused(theatre: Theatre) -> None:
    run = theatre.run(kind="theatre")
    assert _refusal(theatre, changes.accept, m.AcceptRequest(_ref(run))).code == (
        "run.not-a-worktree"
    )
    assert theatre.git.calls == []


def test_accept_of_a_run_with_no_end_is_refused(theatre: Theatre) -> None:
    run = theatre.run(ended=False)
    lease_dir(theatre.path, run.run_id).mkdir(parents=True)
    error = _refusal(theatre, changes.accept, m.AcceptRequest(_ref(run)))
    assert error.code == "run.not-ended"
    assert error.details == {"run": run.run_id, "state": "interrupted"}


def test_accepting_twice_is_refused_naming_the_first(theatre: Theatre) -> None:
    run = theatre.run()
    theatre.call(changes.accept, m.AcceptRequest(_ref(run)))
    at = theatre.store.history(UUID(run.run_id))[-1]
    error = _refusal(theatre, changes.accept, m.AcceptRequest(_ref(run)))
    assert error.code == "run.changes-settled"
    settled_at = error.details["at"]
    assert error.problem == f"Run {run.run_id}'s changes were already accepted, at {settled_at}."
    assert error.fix == "Nothing more can be done with them: settling a run's changes is final."
    assert error.details == {"run": run.run_id, "settled": "accepted", "at": settled_at}
    assert at.topic.endswith("Run.ChangesAccepted")


def test_accept_of_a_run_waiting_at_its_gate_is_refused(theatre: Theatre) -> None:
    run = theatre.run()
    run.raise_cue("director", BRIEF)
    theatre.record(run)
    error = _refusal(theatre, changes.accept, m.AcceptRequest(_ref(run)))
    assert error.code == "run.waiting-at-gate"
    assert error.details["command"] == f"troupe approve {_ref(run)}"
    assert theatre.git.calls == []


def test_accept_of_a_run_that_changed_nothing_is_refused(theatre: Theatre) -> None:
    run = theatre.run({"added": 0, "modified": 0, "deleted": 0, "leftOut": 0})
    error = _refusal(theatre, changes.accept, m.AcceptRequest(_ref(run)))
    assert error.code == "run.no-changes"
    assert error.problem == (
        f"Run {run.run_id} changed nothing in its worktree, so there is nothing to accept."
    )
    assert error.fix == f"Discard it to remove its worktree: troupe discard {_ref(run)}"
    assert error.details == {"run": run.run_id, "worktree": _worktree(run)}


def test_accept_of_uncaptured_changes_with_no_error_names_none(theatre: Theatre) -> None:
    run = theatre.run(ended=False)
    run.end(outcome("succeeded"), None, None)
    theatre.record(run)
    error = _refusal(theatre, changes.accept, m.AcceptRequest(_ref(run)))
    assert error.code == "run.changes-uncaptured"
    assert error.details == {"run": run.run_id, "worktree": _worktree(run)}


# discard


def test_discard_removes_the_worktree_and_records_it(theatre: Theatre) -> None:
    run = theatre.run()
    result = theatre.call(changes.discard, m.DiscardRequest(_ref(run), reason="not needed"))
    assert result == m.DiscardResult(
        run=run.run_id, worktree=_worktree(run), rehearsed=False, notices=[]
    )
    assert theatre.git.calls == [("remove_worktree", worktree_path(theatre.path, run.run_id))]
    assert theatre.topics(run)[-1] == "Run.ChangesDiscarded"
    assert theatre.last(run).lineage["reason"] == "not needed"
    assert [p.name for p in lease_dir(theatre.path, run.run_id).iterdir()] == ["settle"]


def test_a_rehearsed_discard_changes_nothing(theatre: Theatre) -> None:
    run = theatre.run()
    result = theatre.call(changes.discard, m.DiscardRequest(_ref(run), rehearse=True))
    assert result.rehearsed is True
    assert result.worktree == _worktree(run)
    assert theatre.git.calls == []
    assert theatre.topics(run) == ["Run.Started", "Run.Ended"]


def test_an_interrupted_run_can_be_discarded(theatre: Theatre) -> None:
    run = theatre.run(ended=False)
    lease_dir(theatre.path, run.run_id).mkdir(parents=True)
    result = theatre.call(changes.discard, m.DiscardRequest(_ref(run)))
    assert result.worktree == _worktree(run)
    assert theatre.topics(run) == ["Run.Started", "Run.ChangesDiscarded"]


def test_discard_of_a_run_unfinished_elsewhere_is_refused(theatre: Theatre) -> None:
    run = theatre.run(ended=False)
    error = _refusal(theatre, changes.discard, m.DiscardRequest(_ref(run)))
    assert error.code == "run.not-ended"
    assert error.details == {"run": run.run_id, "state": "unfinished-elsewhere"}
    assert theatre.git.calls == []


def test_discarding_after_accepting_is_refused(theatre: Theatre) -> None:
    run = theatre.run()
    theatre.call(changes.accept, m.AcceptRequest(_ref(run)))
    error = _refusal(theatre, changes.discard, m.DiscardRequest(_ref(run)))
    assert error.code == "run.changes-settled"
    assert error.details["settled"] == "accepted"


def test_discard_of_a_run_waiting_at_its_gate_is_refused(theatre: Theatre) -> None:
    run = theatre.run()
    run.raise_cue("director", BRIEF)
    theatre.record(run)
    error = _refusal(theatre, changes.discard, m.DiscardRequest(_ref(run)))
    assert error.code == "run.waiting-at-gate"
    assert error.details["command"] == f"troupe reject {_ref(run)}"
    assert theatre.git.calls == []


def test_discard_of_a_theatre_run_is_refused(theatre: Theatre) -> None:
    run = theatre.run(kind="theatre")
    error = _refusal(theatre, changes.discard, m.DiscardRequest(_ref(run)))
    assert error.code == "run.not-a-worktree"


# Recording a settling


def test_a_settling_approved_in_a_role_carries_that_approval(theatre: Theatre) -> None:
    run = theatre.run()
    run.raise_cue("director", BRIEF)
    theatre.record(run)
    diff = theatre.artifacts.put(PATCH)
    changes.record_settling(
        theatre.store,
        run.run_id,
        "approved",
        lambda r: r.accept_changes(diff, ["a.txt"], approved_as="director"),
        approved_as="director",
    )
    accepted = theatre.last(run)
    (approval,) = accepted.lineage["approvals"]
    assert approval["role"] == "director"
    assert approval["actor"] == accepted.lineage["actor"]
    assert accepted.lineage["reason"] == "approved"


def test_a_settling_recorded_as_a_given_command_is_that_commands(theatre: Theatre) -> None:
    run = theatre.run()
    command = theatre.store.command(via="server", reason="kept at the gate")
    changes.record_settling(
        theatre.store, run.run_id, "ignored", lambda r: r.discard_changes(), command=command
    )
    discarded = theatre.last(run)
    assert discarded.lineage["via"] == "server"
    assert discarded.lineage["reason"] == "kept at the gate"


def test_settling_a_stream_that_isnt_a_run_is_a_type_error(theatre: Theatre) -> None:
    counter = Counter(value=1)
    theatre.store.command(via="cli").record(counter.collect_events())
    stream = str(counter.id)
    with pytest.raises(TypeError, match=f"run {stream}'s stream doesn't hold a run"):
        changes.record_settling(theatre.store, stream, None, lambda r: None)


def test_a_settle_lock_an_earlier_settling_left_is_reused(theatre: Theatre) -> None:
    run = theatre.run()
    lease = lease_dir(theatre.path, run.run_id)
    theatre.call(changes.discard, m.DiscardRequest(_ref(run), rehearse=True))
    assert [p.name for p in lease.iterdir()] == ["settle"]
    theatre.call(changes.discard, m.DiscardRequest(_ref(run)))
    assert [p.name for p in lease.iterdir()] == ["settle"]
    assert theatre.topics(run)[-1] == "Run.ChangesDiscarded"


def test_accept_doesnt_mind_a_diff_file_already_gone(theatre: Theatre) -> None:
    run = theatre.run()
    theatre.git.consume = True
    result = theatre.call(changes.accept, m.AcceptRequest(_ref(run)))
    assert result.files == ["a.txt"]
    assert theatre.topics(run)[-1] == "Run.ChangesAccepted"


def test_keeping_at_a_gate_records_the_command_and_its_approval(theatre: Theatre) -> None:
    run = theatre.run()
    run.raise_cue("director", BRIEF)
    theatre.record(run)
    view = changes.view_of(theatre.store, run.run_id)
    pending = view.changes()
    assert pending is not None
    command = theatre.store.command(via="server", reason="approved at the gate")
    result = changes.keep(
        theatre.store,
        theatre.path,
        view,
        pending,
        PATCH,
        rehearse=False,
        reason="ignored",
        announce=theatre.sent.append,
        command=command,
        approved_as="director",
    )
    assert result.files == ["a.txt"]
    accepted = theatre.last(run)
    assert accepted.topic.endswith("Run.ChangesAccepted")
    assert accepted.lineage["via"] == "server"
    assert accepted.lineage["reason"] == "approved at the gate"
    assert [a["role"] for a in accepted.lineage["approvals"]] == ["director"]

"""A worktree run's gate, and approving or rejecting its cue, in process against a real git theatre
(spec: gates, runs, run-workspaces, lineage; manual-gates design D1 to D8)."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from gitrepo import Repo
from run_changes_shared import call_discard
from run_workspaces_shared import Recording, configured, write
from runtesting import ADA, ALLOW, INIT, OK, Harness, committed
from troupe.core import gates
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError
from troupe.core.runs import gate
from troupe.core.runs.changes import accept
from troupe.core.runs.queries import status
from troupe.core.workspaces import worktree_path

TESTS_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "tests")
CHILD = TESTS_ROOT / "settle_child.py"
FAIL = {"event": {"type": "result", "status": "error", "reason": "other", "message": "no"}}
EVERYWHERE = {"write": ["**"]}


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return committed(tmp_path)


def gated(
    made: Harness, *steps: dict[str, Any], approvers: list[str] | None = None
) -> m.RunSummary:
    """A worktree run that may write anything, with ``approvers`` (the default when None)."""
    fields: dict[str, Any] = {"effects": EVERYWHERE}
    if approvers is not None:
        fields["approvers"] = approvers
    asked = configured(made, INIT, *steps, **fields)
    return made.perform(asked).run


def changing(made: Harness, approvers: list[str] | None = None) -> m.RunSummary:
    return gated(made, write("src/a.txt", "two\n"), OK, approvers=approvers)


def history(made: Harness, run_id: str) -> list[tuple[str, dict[str, Any]]]:
    store = made.backends().event_store(made.session())
    return [
        (event.topic.split(":")[1], {**json.loads(event.state), "_lineage": event.lineage})
        for event in store.history(UUID(run_id))
    ]


def call(made: Harness, handler: Any, request: Any) -> Any:  # noqa: ANN401
    return asyncio.run(handler(request, made.session(), made.send, backends=made.backends()))


def approve(made: Harness, run: str, **fields: Any) -> m.AcceptResult:  # noqa: ANN401
    result = call(made, gate.approve, m.ApproveRequest.from_data({"run": run, **fields}))
    assert isinstance(result, m.AcceptResult)
    return result


def reject(made: Harness, run: str, **fields: Any) -> m.DiscardResult:  # noqa: ANN401
    result = call(made, gate.reject, m.RejectRequest.from_data({"run": run, **fields}))
    assert isinstance(result, m.DiscardResult)
    return result


def conflicting(repo: Repo, approvers: list[str] | None = None) -> tuple[Recording, m.RunSummary]:
    """A run that changes src/a.txt while the person edits it too, so its diff won't apply."""
    made = Recording(repo)
    made.on_running = lambda: (repo.path / "src" / "a.txt").write_text("mine\n", encoding="utf-8")
    return made, changing(made, approvers)


def summary(made: Harness, run_id: str) -> m.RunSummary:
    result = call(made, status, m.StatusRequest(run=run_id))
    assert isinstance(result, m.StatusResult)
    [run] = result.runs
    return run


# Requirement: A worktree run's start records its approvers and where they came from


@pytest.mark.parametrize(
    ("approvers", "recorded"),
    [
        (None, {"value": ["troupe", "director"], "source": "default"}),
        (["director"], {"value": ["director"], "source": "actor"}),
    ],
    ids=["none set", "set by the actor"],
)
def test_a_worktree_runs_start_records_its_approvers_and_their_source(
    repo: Repo, approvers: list[str] | None, recorded: dict[str, Any]
) -> None:
    made = Harness(repo)
    run = gated(made, OK, approvers=approvers)
    [(topic, started), *_] = history(made, run.run_id)
    assert topic == "Run.Started"
    assert started["approvers"] == recorded
    assert run.approvers is not None
    assert run.approvers.to_data() == recorded


def test_a_run_in_the_theatre_records_no_approvers(repo: Repo) -> None:
    from runtesting import request, script

    made = Harness(repo)
    asked = request(script(INIT, OK))
    made.configure(asked)
    run = made.perform(asked).run
    [(_, started), *_] = history(made, run.run_id)
    assert "approvers" not in started
    assert run.approvers is None


def test_a_rehearsal_shows_the_approvers_it_would_use(repo: Repo) -> None:
    made = Harness(repo)
    asked = configured(made, INIT, OK, effects=EVERYWHERE)
    result = made.perform_result({**asked, "rehearse": True})
    assert result.rehearsal is not None
    assert result.rehearsal.approvers is not None
    assert result.rehearsal.approvers.to_data() == {
        "value": ["troupe", "director"],
        "source": "default",
    }


# Requirement: A worktree run that succeeds with changes passes a gate
# Requirement: troupe approves clean changes by itself


def test_troupe_keeps_clean_changes_with_its_own_approval_and_raises_no_cue(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made)
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert not worktree_path(repo.path, run.run_id).exists()
    assert run.changes is not None
    assert run.changes.state == "accepted"
    topics = [topic for topic, _ in history(made, run.run_id)]
    assert "Run.CueRaised" not in topics
    assert "Run.GatePassed" not in topics
    [(_, accepted)] = [(t, e) for t, e in history(made, run.run_id) if t == "Run.ChangesAccepted"]
    lineage = accepted["_lineage"]
    troupe = {"kind": "system", "id": gates.troupe_actor().id}
    assert lineage["actor"] == troupe
    assert lineage["via"] == "cli"
    assert "stage" not in lineage
    [approval] = lineage["approvals"]
    assert approval["actor"] == troupe
    assert approval["role"] == "troupe"
    [(_, started)] = [(t, e) for t, e in history(made, run.run_id) if t == "Run.Started"]
    assert lineage["change"] == started["_lineage"]["change"]


def test_a_kept_runs_summary_shows_troupes_approval(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made)
    assert run.gate is not None
    [step] = run.gate
    assert isinstance(step, m.ApprovedStep)
    assert step.role == "troupe"
    assert step.actor.kind == "system"


def test_a_run_that_failed_with_changes_reaches_no_gate_and_is_pending(repo: Repo) -> None:
    made = Harness(repo)
    run = gated(made, write("out/partial.txt", "p\n"), FAIL)
    assert run.outcome == "failed"
    assert run.changes is not None
    assert run.changes.state == "pending"
    assert run.gate is None
    assert not (repo.path / "out" / "partial.txt").exists()


def test_a_run_that_changed_nothing_reaches_no_gate(repo: Repo) -> None:
    made = Harness(repo)
    run = gated(made, OK, approvers=["director"])
    assert run.changes is not None
    assert run.changes.state == "none"
    assert run.gate is None


# Requirement: A pass is recorded with its reason
# Requirement: Reaching director raises a cue


def test_a_conflict_passes_to_director_and_raises_a_cue_changing_nothing(repo: Repo) -> None:
    made, run = conflicting(repo)
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "mine\n"
    assert worktree_path(repo.path, run.run_id).exists()
    recorded = history(made, run.run_id)
    [(_, passed)] = [(t, e) for t, e in recorded if t == "Run.GatePassed"]
    assert (passed["approver"], passed["to"], passed["reason"], passed["files"]) == (
        "troupe",
        "director",
        "conflict",
        ["src/a.txt"],
    )
    [(_, cue)] = [(t, e) for t, e in recorded if t == "Run.CueRaised"]
    assert cue["role"] == "director"
    assert run.changes is not None
    assert cue["brief"] == {
        "actor": "tester",
        "outcome": "succeeded",
        "diff": run.changes.diff,
        "added": 0,
        "modified": 1,
        "deleted": 0,
        "after": {"approver": "troupe", "reason": "conflict", "files": ["src/a.txt"]},
    }
    assert cue["_lineage"]["actor"]["kind"] == "system"
    assert run.changes.state == "waiting"
    assert run.changes.cue is not None
    assert run.changes.cue.role == "director"
    assert [step.TYPE for step in run.gate or []] == ["passed", "cue"]


def test_a_person_first_gets_a_cue_recorded_with_the_runs_end(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    store = made.backends().event_store(made.session())
    events = store.history(UUID(run.run_id))
    topics = [e.topic.split(":")[1] for e in events]
    assert topics[-2:] == ["Run.Ended", "Run.CueRaised"]
    assert "Run.GatePassed" not in topics
    cue = json.loads(events[-1].state)
    assert "after" not in cue["brief"]
    assert run.changes is not None
    assert run.changes.state == "waiting"


def test_a_cue_first_in_the_list_is_in_one_batch_with_the_end(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec: gates, "A cue first in the list": recorded with the end, so a perform that stops after
    # the end can't leave the run unasked. One batch: the end and the cue reach the store together.
    batches: list[list[str]] = []
    made = Harness(repo)

    def wrap(store: Any) -> Any:  # noqa: ANN401
        original = store.record_with_lineages

        def record(events: Any, lineages: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            batches.append([type(e).__qualname__ for e in events])
            return original(events, lineages, **kwargs)

        store.record_with_lineages = record
        return store

    made.store_wrapper = wrap
    changing(made, approvers=["director"])
    assert ["Run.Ended", "Run.CueRaised"] in batches


def test_a_perform_that_stops_before_troupes_step_leaves_the_run_pending_for_accept(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Design D3's remaining window: only a list that starts with troupe has it.
    def stopped(*_: Any) -> None:  # noqa: ANN401
        raise KeyboardInterrupt

    monkeypatch.setattr(gate, "troupes_step", stopped)
    made = Harness(repo)
    with pytest.raises(KeyboardInterrupt):
        changing(made)
    [run_id] = [p.name for p in (repo.path / ".troupe" / "local" / "worktrees").iterdir()]
    assert summary(made, run_id).changes.state == "pending"  # type: ignore[union-attr]
    call(made, accept, m.AcceptRequest(run=run_id))
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"


# Requirement: Status lists every open cue


def test_status_lists_every_open_cue_whatever_the_limit(repo: Repo) -> None:
    made = Harness(repo)
    waiting = changing(made, approvers=["director"])
    gated(made, OK)
    result = call(made, status, m.StatusRequest(limit=1))
    assert [run.run_id for run in result.runs] != [waiting.run_id]
    [cue] = result.cues
    assert (cue.run, cue.actor, cue.role) == (waiting.run_id, "tester", "director")


def test_status_lists_no_cue_when_nothing_waits(repo: Repo) -> None:
    made = Harness(repo)
    changing(made)
    assert call(made, status, m.StatusRequest()).cues == []


# Requirement: Approving a cue keeps the work


def test_approving_after_fixing_a_conflict_keeps_the_work_with_the_persons_approval(
    repo: Repo,
) -> None:
    made, run = conflicting(repo)
    (repo.path / "src" / "a.txt").write_text("one\n", encoding="utf-8")
    result = approve(made, run.run_id[:8], reason="fine")
    assert result.files == ["src/a.txt"]
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert not worktree_path(repo.path, run.run_id).exists()
    [*_, (topic, accepted)] = history(made, run.run_id)
    assert topic == "Run.ChangesAccepted"
    lineage = accepted["_lineage"]
    assert lineage["actor"] == {"kind": "human", "id": "ada@example.com", "source": "env"}
    assert lineage["reason"] == "fine"
    [approval] = lineage["approvals"]
    assert (approval["actor"], approval["role"]) == (lineage["actor"], "director")
    after = summary(made, run.run_id)
    assert after.changes is not None
    assert after.changes.state == "accepted"
    assert [step.TYPE for step in after.gate or []] == ["passed", "cue", "approved"]


def test_approving_while_it_still_conflicts_is_refused_and_the_cue_stays_open(repo: Repo) -> None:
    made, run = conflicting(repo)
    with pytest.raises(TroupeError) as caught:
        approve(made, run.run_id)
    assert caught.value.code == "run.changes-conflict"
    assert caught.value.details["files"] == ["src/a.txt"]
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "mine\n"
    assert summary(made, run.run_id).changes.state == "waiting"  # type: ignore[union-attr]


def test_a_rehearsed_approve_names_the_files_and_changes_nothing(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    before = history(made, run.run_id)
    result = approve(made, run.run_id, rehearse=True)
    assert (result.files, result.rehearsed) == (["src/a.txt"], True)
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert history(made, run.run_id) == before


# Requirement: Rejecting a cue removes the worktree


def test_rejecting_removes_the_worktree_and_records_who_why_and_the_role(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    result = reject(made, run.run_id, reason="wrong file")
    assert result.worktree == f".troupe/local/worktrees/{run.run_id}"
    assert not worktree_path(repo.path, run.run_id).exists()
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    [*_, (topic, rejected)] = history(made, run.run_id)
    assert topic == "Run.ChangesRejected"
    assert rejected["role"] == "director"
    assert rejected["_lineage"]["actor"]["id"] == "ada@example.com"
    assert rejected["_lineage"]["reason"] == "wrong file"
    assert rejected["_lineage"]["approvals"] == []
    after = summary(made, run.run_id)
    assert after.changes is not None
    assert after.changes.state == "rejected"
    assert after.changes.worktree is None


def test_a_rehearsed_reject_names_the_worktree_and_changes_nothing(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    before = history(made, run.run_id)
    result = reject(made, run.run_id, rehearse=True)
    assert result.rehearsed
    assert worktree_path(repo.path, run.run_id).exists()
    assert history(made, run.run_id) == before


# Requirement: Accept and discard leave an open cue to its answer


@pytest.mark.parametrize("rehearse", [False, True], ids=["for real", "rehearsed"])
def test_accepting_a_waiting_run_is_refused_naming_director_and_approve(
    repo: Repo, rehearse: bool
) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    before = history(made, run.run_id)
    with pytest.raises(TroupeError) as caught:
        call(made, accept, m.AcceptRequest(run=run.run_id, rehearse=rehearse or None))
    assert caught.value.code == "run.waiting-at-gate"
    assert caught.value.details["role"] == "director"
    assert caught.value.details["command"] == f"troupe approve {run.run_id[:8]}"
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert history(made, run.run_id) == before


def test_discarding_a_waiting_run_is_refused_naming_reject_and_keeps_the_worktree(
    repo: Repo,
) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    with pytest.raises(TroupeError) as caught:
        call_discard(made, run.run_id)
    assert caught.value.code == "run.waiting-at-gate"
    assert caught.value.details["command"] == f"troupe reject {run.run_id[:8]}"
    assert worktree_path(repo.path, run.run_id).exists()


# Requirement: A cue is answered once
# Requirement: A run settled at a gate can't be settled again


def test_approving_a_run_that_never_reached_a_gate_names_accept_and_discard(repo: Repo) -> None:
    made = Harness(repo)
    run = gated(made, write("out/partial.txt", "p\n"), FAIL)
    with pytest.raises(TroupeError) as caught:
        approve(made, run.run_id)
    assert caught.value.code == "gate.no-cue"
    assert caught.value.details["state"] == "pending"
    assert "troupe accept" in caught.value.fix
    assert "troupe discard" in caught.value.fix


def test_approving_a_run_troupe_kept_is_refused_as_settled(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made)
    with pytest.raises(TroupeError) as caught:
        approve(made, run.run_id)
    assert caught.value.code == "run.changes-settled"
    assert caught.value.details["settled"] == "accepted"


def test_accepting_a_rejected_run_is_refused_naming_the_rejection(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    reject(made, run.run_id)
    with pytest.raises(TroupeError) as caught:
        call(made, accept, m.AcceptRequest(run=run.run_id))
    assert caught.value.code == "run.changes-settled"
    assert caught.value.details["settled"] == "rejected"


def test_two_approves_at_once_keep_the_work_once_and_refuse_the_other(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    env = json.dumps({**repo.env, **ADA, **ALLOW})
    children = [
        subprocess.Popen(
            [sys.executable, str(CHILD), str(repo.path), env, "approve", run.run_id],
            stdout=subprocess.PIPE,
            env={**repo.env, **ADA, **ALLOW},
        )
        for _ in range(2)
    ]
    outputs = sorted(child.communicate(timeout=120)[0].decode().strip() for child in children)
    assert outputs == ["OK", "run.changes-settled"]
    topics = [topic for topic, _ in history(made, run.run_id)]
    assert topics.count("Run.ChangesAccepted") == 1


# Requirement: Whoever runs troupe holds director


def test_another_person_on_the_same_clone_may_approve(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    bob = Harness(repo, env={"TROUPE_ACTOR": "human:bob@example.com", **ALLOW})
    approve(bob, run.run_id)
    [*_, (_, accepted)] = history(made, run.run_id)
    [approval] = accepted["_lineage"]["approvals"]
    assert approval["actor"]["id"] == "bob@example.com"
    assert approval["role"] == "director"


def test_an_agent_identity_is_refused_as_not_a_holder_and_the_cue_stays_open(repo: Repo) -> None:
    made = Harness(repo)
    run = changing(made, approvers=["director"])
    agent = Harness(repo, env={"TROUPE_ACTOR": "agent:bot", **ALLOW})
    for answer in (approve, reject):
        with pytest.raises(TroupeError) as caught:
            answer(agent, run.run_id)
        assert caught.value.code == "gate.not-a-holder"
        assert caught.value.details == {"role": "director", "kind": "agent"}
    assert summary(made, run.run_id).changes.state == "waiting"  # type: ignore[union-attr]

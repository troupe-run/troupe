"""diff, accept and discard: what a person does with a worktree run's changes (spec:
run-workspaces; worktree-stage design D6; account-for-every-worktree design D5, D6)."""

import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from gitrepo import Repo
from runtesting import ADA, ALLOW, INIT, OK, Harness, request, script, theatre
from test_run_workspaces import Recording, committed, configured, write
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError
from troupe.core.runs.changes import accept, diff, discard
from troupe.core.workspaces import worktree_path

CHILD = Path(__file__).with_name("settle_child.py")


def call_diff(made: Harness, run: str) -> m.DiffResult:
    return asyncio.run(
        diff(m.DiffRequest(run=run), made.session(), made.send, backends=made.backends())
    )


def call_accept(made: Harness, run: str, **fields: Any) -> m.AcceptResult:  # noqa: ANN401
    return asyncio.run(
        accept(
            m.AcceptRequest.from_data({"run": run, **fields}),
            made.session(),
            made.send,
            backends=made.backends(),
        )
    )


def call_discard(made: Harness, run: str, **fields: Any) -> m.DiscardResult:  # noqa: ANN401
    return asyncio.run(
        discard(
            m.DiscardRequest.from_data({"run": run, **fields}),
            made.session(),
            made.send,
            backends=made.backends(),
        )
    )


def last_event(made: Harness, run_id: str) -> tuple[str, dict[str, Any]]:
    [*_, event] = made.stores[-1].history(UUID(run_id))
    return event.topic.split(":")[1], json.loads(event.state)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return committed(tmp_path)


def changed_run(made: Harness) -> m.RunSummary:
    """A worktree run that modified src/a.txt and added out/hello.txt."""
    asked = configured(made, INIT, write("src/a.txt", "two\n"), write("out/hello.txt", "hi\n"), OK)
    return made.perform(asked).run


# Requirement: A run's changes can be shown


def test_the_diff_is_the_artifact_the_runs_end_references_byte_for_byte(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    shown = call_diff(made, run.run_id[:8])
    assert shown.encoding == "utf-8"
    assert run.changes is not None
    assert run.changes.diff is not None
    stored = made.backends().artifact_store(made.session()).read(run.changes.diff)
    assert (shown.patch or "").encode("utf-8") == stored
    assert shown.base == repo.git("rev-parse", "HEAD").strip()


def test_a_diff_that_isnt_utf_8_is_returned_as_base64_of_its_bytes(repo: Repo) -> None:
    made = Recording(repo)
    asked = configured(made, INIT, OK)
    # Latin-1 bytes written into the worktree while the run goes, as an actor's tool might.
    made.on_running = lambda: (
        worktree_path(repo.path, made.updates[-1]["runId"]) / "menu.txt"
    ).write_bytes(b"caf\xe9\n")
    run = made.perform(asked).run
    shown = call_diff(made, run.run_id)
    assert shown.encoding == "base64"
    assert run.changes is not None
    assert run.changes.diff is not None
    stored = made.backends().artifact_store(made.session()).read(run.changes.diff)
    assert b"caf\xe9" in stored
    assert base64.b64decode(shown.patch or "") == stored


def test_a_run_that_changed_nothing_has_no_diff_and_state_none(repo: Repo) -> None:
    made = Harness(repo)
    run = made.perform(configured(made, INIT, OK)).run
    shown = call_diff(made, run.run_id)
    assert shown.patch is None
    assert shown.changes.state == "none"


def test_a_run_in_the_theatre_has_no_diff_to_show(repo: Repo) -> None:
    made = Harness(repo)
    run = made.perform(request(script(INIT, OK))).run
    with pytest.raises(TroupeError) as caught:
        call_diff(made, run.run_id)
    assert caught.value.code == "run.not-a-worktree"


def test_a_run_with_no_end_is_refused_as_not_ended(repo: Repo) -> None:
    made = Harness(repo)
    asked = configured(made, INIT, OK)
    run = made.perform(asked).run
    store = made.stores[-1]
    # A run whose end isn't recorded and whose perform is gone: interrupted.
    from troupe.core.runs.aggregate import Run

    other = Run(
        run_id="0f8fad5b-d9cb-469f-a165-70867728950e",
        actor="tester",
        runner_requested="scripted",
        stage=json.loads(store.history(UUID(run.run_id))[0].state)["stage"],
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=json.loads(store.history(UUID(run.run_id))[0].state)["config"],
        workspace={
            **json.loads(store.history(UUID(run.run_id))[0].state)["workspace"],
            "path": ".troupe/local/worktrees/0f8fad5b-d9cb-469f-a165-70867728950e",
        },
    )
    store.command(via="cli").record(other.collect_events())
    with pytest.raises(TroupeError) as caught:
        call_diff(made, other.run_id)
    assert caught.value.code == "run.not-ended"
    assert caught.value.details["state"] == "unfinished-elsewhere"


# Requirement: Accepting applies the changes to the working tree, all or nothing


def test_a_clean_accept_writes_the_changes_unstaged_and_removes_the_worktree(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    head = repo.git("rev-parse", "HEAD").strip()
    result = call_accept(made, run.run_id)
    assert result.files == ["out/hello.txt", "src/a.txt"]
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert (repo.path / "out" / "hello.txt").read_text(encoding="utf-8") == "hi\n"
    assert repo.git("diff", "--cached", "--name-only") == ""
    assert repo.git("rev-parse", "HEAD").strip() == head
    assert not worktree_path(repo.path, run.run_id).exists()


def test_an_accept_that_conflicts_changes_nothing_and_keeps_the_worktree(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    repo.write("src/a.txt", "the person's own edit\n")
    with pytest.raises(TroupeError) as caught:
        call_accept(made, run.run_id)
    error = caught.value
    assert error.code == "run.changes-conflict"
    assert error.details["files"] == ["src/a.txt"]
    assert run.changes is not None
    assert error.details["diff"] == run.changes.diff
    assert error.details["worktree"] == f".troupe/local/worktrees/{run.run_id}"
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "the person's own edit\n"
    assert not (repo.path / "out" / "hello.txt").exists()
    assert worktree_path(repo.path, run.run_id).is_dir()
    assert last_event(made, run.run_id)[0] == "Run.Ended"


def test_a_rehearsed_accept_names_the_files_and_changes_nothing(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    result = call_accept(made, run.run_id, rehearse=True)
    assert result.rehearsed is True
    assert result.files == ["out/hello.txt", "src/a.txt"]
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert last_event(made, run.run_id)[0] == "Run.Ended"


def test_a_rehearsed_accept_that_would_conflict_is_refused_naming_the_files(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    repo.write("src/a.txt", "mine\n")
    with pytest.raises(TroupeError) as caught:
        call_accept(made, run.run_id, rehearse=True)
    assert caught.value.code == "run.changes-conflict"
    assert last_event(made, run.run_id)[0] == "Run.Ended"


def test_accepting_a_run_that_changed_nothing_is_refused_as_no_changes(repo: Repo) -> None:
    made = Harness(repo)
    run = made.perform(configured(made, INIT, OK)).run
    with pytest.raises(TroupeError) as caught:
        call_accept(made, run.run_id)
    assert caught.value.code == "run.no-changes"


def test_accepting_uncaptured_changes_is_refused_naming_the_worktree(repo: Repo) -> None:
    from test_run_workspaces import _replacing, _vcs_failed

    made = Harness(repo, store_wrapper=_replacing("capture", _vcs_failed))
    run = made.perform(configured(made, INIT, write("a.txt", "a\n"), OK)).run
    made.store_wrapper = None
    with pytest.raises(TroupeError) as caught:
        call_accept(made, run.run_id)
    assert caught.value.code == "run.changes-uncaptured"
    assert caught.value.details["worktree"] == f".troupe/local/worktrees/{run.run_id}"
    assert caught.value.details["error"]["code"] == "vcs.failed"


def test_accepting_a_run_in_another_clone_whose_diff_isnt_here_is_refused(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    store = made.backends().artifact_store(made.session())
    assert run.changes is not None
    assert run.changes.diff is not None
    stored = repo.path / ".troupe" / "local" / "artifacts"
    for path in stored.rglob("*"):
        if path.is_file() and run.changes.diff.removeprefix("sha256:") in path.name:
            path.unlink()
    assert not store.contains(run.changes.diff)
    with pytest.raises(TroupeError) as caught:
        call_accept(made, run.run_id)
    assert caught.value.code == "artifact.missing"


# Requirement: Discarding removes the worktree


def test_discarding_removes_the_worktree_and_leaves_the_theatre_as_it_was(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    result = call_discard(made, run.run_id)
    assert result.worktree == f".troupe/local/worktrees/{run.run_id}"
    assert not worktree_path(repo.path, run.run_id).exists()
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert last_event(made, run.run_id)[0] == "Run.ChangesDiscarded"
    assert run.changes is not None
    assert run.changes.diff is not None
    assert made.backends().artifact_store(made.session()).contains(run.changes.diff)


def test_a_rehearsed_discard_names_the_worktree_and_removes_nothing(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    result = call_discard(made, run.run_id, rehearse=True)
    assert result.rehearsed is True
    assert worktree_path(repo.path, run.run_id).is_dir()
    assert last_event(made, run.run_id)[0] == "Run.Ended"


def test_discarding_an_interrupted_run_removes_its_worktree_and_records_the_discard(
    repo: Repo,
) -> None:
    made = Harness(repo)
    run = made.perform(configured(made, INIT, write("a.txt", "a\n"), OK)).run
    store = made.stores[-1]
    # Take the end away, as if perform had been killed before recording it: its lease is free.
    from test_run_workspaces import history

    started = history(made, run.run_id)[0]
    from troupe.core.runs.aggregate import Run

    other_id = "0f8fad5b-d9cb-469f-a165-70867728950e"
    interrupted = Run(
        run_id=other_id,
        actor="tester",
        runner_requested="scripted",
        stage=started["stage"],
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=started["config"],
        workspace={**started["workspace"], "path": f".troupe/local/worktrees/{other_id}"},
    )
    store.command(via="cli").record(interrupted.collect_events())
    (repo.path / ".troupe" / "local" / "runs" / other_id).mkdir(parents=True)  # a free lease
    worktree = worktree_path(repo.path, other_id)
    store.vcs.add_worktree(worktree, started["workspace"]["base"])
    call_discard(made, other_id)
    assert not worktree.exists()
    assert last_event(made, other_id)[0] == "Run.ChangesDiscarded"


def test_discarding_a_run_that_couldnt_start_removes_the_worktree_it_left(repo: Repo) -> None:
    from test_run_workspaces import _replacing, _vcs_failed

    made = Harness(repo, store_wrapper=_replacing("shared_state", _vcs_failed))
    asked = configured(made, INIT, OK)
    with pytest.raises(TroupeError):
        made.perform(asked)
    [started] = [u for u in made.updates if u.get("kind") == "started"]
    run_id = started["runId"]
    assert worktree_path(repo.path, run_id).is_dir()
    call_discard(made, run_id)
    assert not worktree_path(repo.path, run_id).exists()
    assert f"worktrees/{run_id}" not in repo.git("worktree", "list", "--porcelain")
    assert last_event(made, run_id)[0] == "Run.ChangesDiscarded"


# Requirement: Accepting and discarding are recorded, and final


def test_an_accepts_lineage_is_the_person_through_the_cli_with_the_reason_and_no_stage(
    repo: Repo,
) -> None:
    made = Harness(repo)
    run = changed_run(made)
    call_accept(made, run.run_id, reason="looks right")
    topic, state = last_event(made, run.run_id)
    assert topic == "Run.ChangesAccepted"
    lineage = state["lineage"]
    assert lineage["actor"] == {"kind": "human", "id": "ada@example.com", "source": "env"}
    assert lineage["via"] == "cli"
    assert lineage["reason"] == "looks right"
    assert "stage" not in lineage
    assert run.changes is not None
    assert state["diff"] == run.changes.diff
    assert state["files"] == ["out/hello.txt", "src/a.txt"]


def test_accepting_after_a_discard_is_refused_naming_the_discard(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    call_discard(made, run.run_id)
    with pytest.raises(TroupeError) as caught:
        call_accept(made, run.run_id)
    assert caught.value.code == "run.changes-settled"
    assert caught.value.details["settled"] == "discarded"
    assert "at" in caught.value.details


def test_discarding_after_an_accept_is_refused(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    call_accept(made, run.run_id)
    with pytest.raises(TroupeError) as caught:
        call_discard(made, run.run_id)
    assert caught.value.code == "run.changes-settled"
    assert caught.value.details["settled"] == "accepted"


def test_two_accepts_at_once_apply_the_diff_once_and_refuse_the_other(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    env = json.dumps({**repo.env, **ADA, **ALLOW})
    children = [
        subprocess.Popen(
            [sys.executable, str(CHILD), str(repo.path), env, "accept", run.run_id],
            stdout=subprocess.PIPE,
            env={**repo.env, **ADA, **ALLOW},
        )
        for _ in range(2)
    ]
    outputs = sorted(child.communicate(timeout=120)[0].decode().strip() for child in children)
    assert outputs == ["OK", "run.changes-settled"]
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    topics = [
        e.topic.split(":")[1]
        for e in made.backends().event_store(made.session()).history(UUID(run.run_id))
    ]
    assert topics.count("Run.ChangesAccepted") == 1


def test_a_worktree_that_cant_be_removed_after_an_accept_is_a_notice_and_the_accept_stands(
    repo: Repo,
) -> None:
    from test_run_workspaces import _replacing

    def cannot(*_: object) -> None:
        raise TroupeError(
            "vcs.failed",
            problem="git worktree remove failed",
            fix="f",
            details={"command": "git worktree remove", "exitStatus": 128},
        )

    made = Harness(repo)
    run = changed_run(made)
    made.store_wrapper = _replacing("remove_worktree", cannot)
    result = call_accept(made, run.run_id)
    [notice] = result.notices
    assert notice.code == "workspace.not-removed"
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert last_event(made, run.run_id)[0] == "Run.ChangesAccepted"


def test_a_settled_runs_status_shows_when_and_no_worktree(repo: Repo) -> None:
    made = Harness(repo)
    run = changed_run(made)
    call_accept(made, run.run_id)
    [summary] = made.status(run=run.run_id).runs
    assert summary.changes is not None
    assert summary.changes.state == "accepted"
    assert summary.changes.settled_at is not None
    assert summary.changes.worktree is None


def test_a_theatre_with_no_commit_is_untouched_by_a_diff_query(tmp_path: Path) -> None:
    made = Harness(theatre(tmp_path))
    with pytest.raises(TroupeError) as caught:
        call_diff(made, "0f8fad5b")
    assert caught.value.code == "run.not-found"


# Requirement: Diff, accept and discard are protocol calls


def test_an_accept_request_that_names_a_diff_is_refused_naming_the_field(repo: Repo) -> None:
    from troupe.core.client.dispatch import call

    made = Harness(repo)
    with pytest.raises(TroupeError) as caught:
        asyncio.run(call("accept", {"run": "0f8fad5b", "diff": "x"}, made.session()))
    assert caught.value.code == "client.invalid-request"
    assert "'diff'" in caught.value.problem


def test_a_summary_in_the_theatre_with_changes_doesnt_validate() -> None:
    from client_schemas import is_valid
    from test_client_messages import ENDED_SUMMARY

    summary = {**ENDED_SUMMARY, "changes": {"state": "none", "worktree": ".troupe/local/w"}}
    assert not is_valid({"run": summary}, "perform-result.schema.json")
    with pytest.raises(ValueError, match="changes are present exactly when"):
        m.RunSummary.from_data(summary)


def test_pending_changes_without_a_diff_dont_validate() -> None:
    from client_schemas import is_valid

    changes = {"state": "pending", "worktree": ".troupe/local/w"}
    assert not is_valid(changes, "run.schema.json#/$defs/changes")
    with pytest.raises(ValueError, match="pending changes have a diff"):
        m.ChangesData.from_data(changes)

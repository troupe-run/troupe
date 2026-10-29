"""A run in its own worktree: made at HEAD, worked in, and its changes captured when it ends
(spec: run-workspaces, runs, stages; worktree-stage design D2, D7, D8, D10)."""

import importlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from gitrepo import Repo
from runtesting import ADA, ALLOW, INIT, OK, Harness, failing_at, request, script, theatre
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.messages import Message
from troupe.core.vcs import Vcs, load_vcs
from troupe.core.workspaces import worktree_path

perform_module = importlib.import_module("troupe.core.runs.perform")
FAIL = {"event": {"type": "result", "status": "error", "message": "it went wrong"}}


def write(path: str, content: str) -> dict[str, Any]:
    return {"writeFile": {"path": path, "content": content}}


def worktree_request(*steps: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return request(script(*steps), workspace="worktree", **fields)


class Recording(Harness):
    """A harness that runs ``on_running`` when the runner's first event arrives: its worktree is
    made and the shared state read, so what it does counts as done during the run."""

    on_running: Any = None

    def send(self, update: Message) -> None:
        super().send(update)
        data = update.to_data()
        if data.get("kind") == "event" and data["seq"] == 0 and self.on_running is not None:
            self.on_running()


def committed(tmp_path: Path) -> Repo:
    """A theatre whose HEAD has src/a.txt (one) and src/b.txt (bee), and ignores build/."""
    repo = theatre(tmp_path)
    for name, text in (("src/a.txt", "one\n"), ("src/b.txt", "bee\n"), (".gitignore", "build/\n")):
        (repo.path / name).parent.mkdir(parents=True, exist_ok=True)
        (repo.path / name).write_bytes(text.encode("utf-8"))  # LF on every OS, as committed
    repo.commit_all("base")
    return repo


def harness(repo: Repo, **options: Any) -> Recording:  # noqa: ANN401
    made = Recording(repo, **options)
    return made


def configured(made: Harness, *steps: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """Configure the actor and commit it, so the theatre's HEAD holds its config."""
    asked = worktree_request(*steps, **fields)
    made.configure(asked)
    made.repo.commit_all("config")
    return asked


def history(made: Harness, run_id: str) -> list[dict[str, Any]]:
    return [json.loads(event.state) for event in made.stores[-1].history(UUID(run_id))]


def notices(made: Harness, code: str) -> list[dict[str, Any]]:
    return [
        update["notice"]
        for update in made.updates
        if update.get("kind") == "notice" and update["notice"]["code"] == code
    ]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return committed(tmp_path)


# Requirement: A worktree run works in its own worktree at HEAD


def test_a_runs_files_land_in_its_worktree_and_the_theatre_is_untouched(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(
        made, INIT, write("out/hello.txt", "hello\n"), write("src/a.txt", "two\n"), OK
    )
    run = made.perform(asked).run
    path = worktree_path(repo.path, run.run_id)
    assert (path / "out" / "hello.txt").read_text(encoding="utf-8") == "hello\n"
    assert (path / "src" / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert not (repo.path / "out" / "hello.txt").exists()
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"


def test_two_runs_get_two_worktrees_and_neither_sees_the_others_files(repo: Repo) -> None:
    made = harness(repo)
    first = made.perform(configured(made, INIT, write("first.txt", "1\n"), OK)).run
    second = made.perform(configured(made, INIT, write("second.txt", "2\n"), OK)).run
    one, two = worktree_path(repo.path, first.run_id), worktree_path(repo.path, second.run_id)
    assert one != two
    assert (one / "first.txt").exists()
    assert not (one / "second.txt").exists()
    assert (two / "second.txt").exists()
    assert not (two / "first.txt").exists()


def test_the_worktree_holds_head_not_an_uncommitted_edit(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(made, INIT, OK)
    repo.write("src/a.txt", "edited, not committed\n")
    run = made.perform(asked).run
    path = worktree_path(repo.path, run.run_id)
    assert (path / "src" / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert (repo.path / "src" / "a.txt").read_text(encoding="utf-8") == "edited, not committed\n"


# Requirement: Uncommitted changes are left out, with a warning


def test_an_uncommitted_edit_is_warned_about_and_recorded_as_dirty(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(made, INIT, OK)
    repo.write("src/a.txt", "edited\n")
    run = made.perform(asked).run
    [notice] = notices(made, "workspace.uncommitted-unseen")
    assert notice["details"]["count"] == 1
    assert notice["details"]["paths"] == ["src/a.txt"]
    assert run.outcome == "succeeded"
    assert history(made, run.run_id)[0]["workspace"]["dirty"] is True


def test_a_clean_theatre_with_troupes_own_uncommitted_events_isnt_dirty(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(made, INIT, OK)
    made.perform(asked)  # its events are uncommitted, under .troupe/
    run = made.perform(asked).run
    assert notices(made, "workspace.uncommitted-unseen") == []
    assert history(made, run.run_id)[0]["workspace"]["dirty"] is False


# Requirement: Files that match HEAD are cloned copy-on-write


def test_the_start_names_the_worktree_and_worktree_made_records_its_clones(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(made, INIT, OK)
    head = repo.git("rev-parse", "HEAD").strip()
    run = made.perform(asked).run
    start, worktree_made = history(made, run.run_id)[:2]
    assert start["workspace"] == {
        "kind": "worktree",
        "path": f".troupe/local/worktrees/{run.run_id}",
        "base": head,
        "dirty": False,
    }
    clones = worktree_made["clones"]
    assert clones  # whatever this file system gave: clonefile, ficlone, copy...
    assert set(clones) <= {"clonefile", "ficlone", "copyfile2", "copy", "symlink"}
    assert run.to_data()["workspace"] == {**start["workspace"], "clones": clones}


# Requirement: A worktree needs git and a commit


def test_a_theatre_with_no_commit_is_refused_as_no_head_and_nothing_is_recorded(
    tmp_path: Path,
) -> None:
    made = harness(theatre(tmp_path))
    with pytest.raises(TroupeError) as caught:
        made.perform(worktree_request(INIT, OK))
    assert caught.value.code == "workspace.no-head"
    assert "actors.tester.workspace=theatre" in caught.value.fix
    assert not (tmp_path / "theatre" / ".troupe" / "local" / "worktrees").exists()


def _files_vcs(store: EventStore) -> EventStore:
    store.vcs = load_vcs("files", store.vcs.theatre if hasattr(store.vcs, "theatre") else Path())
    return store


def test_a_theatre_whose_vcs_cant_make_worktrees_is_refused_naming_the_fix(repo: Repo) -> None:
    made = harness(repo, store_wrapper=_files_vcs)
    asked = configured(made, INIT, OK)
    with pytest.raises(TroupeError) as caught:
        made.perform(asked)
    assert caught.value.code == "vcs.worktrees-unsupported"
    assert "actors.<name>.workspace=theatre" in caught.value.fix
    assert not (repo.path / ".troupe" / "local" / "worktrees").exists()


# Requirement: A stage admits an actor before it runs


def test_a_refused_perform_makes_no_worktree(repo: Repo) -> None:
    made = harness(repo, env=dict(ADA))
    asked = configured(made, INIT, OK)
    with pytest.raises(TroupeError) as caught:
        made.perform(asked)
    assert caught.value.code == "stage.effects-unenforced"
    assert not (repo.path / ".troupe" / "local" / "worktrees").exists()


# Requirement: A worktree is made only after every check passes


class _Wrapped:
    """A VCS adapter with one operation replaced."""

    def __init__(self, inner: Vcs, name: str, replacement: Any) -> None:  # noqa: ANN401
        self._inner, self._name, self._replacement = inner, name, replacement

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return self._replacement if name == self._name else getattr(self._inner, name)


def _replacing(name: str, replacement: Any) -> Any:  # noqa: ANN401
    def wrap(store: EventStore) -> EventStore:
        store.vcs = _Wrapped(store.vcs, name, replacement)
        return store

    return wrap


def _vcs_failed(*_: object) -> Any:  # noqa: ANN401
    raise TroupeError(
        "vcs.failed",
        problem="git checkout-index failed",
        fix="f",
        details={"command": "git checkout-index", "exitStatus": 128},
    )


def topics(made: Harness, run_id: str) -> list[str]:
    return [event.topic.rsplit(":", 1)[1] for event in made.stores[-1].history(UUID(run_id))]


def test_a_worktree_that_fails_to_fill_ends_the_run_could_not_start_and_leaves_no_worktree(
    repo: Repo,
) -> None:
    made = harness(repo, store_wrapper=_replacing("fill_worktree", _vcs_failed))
    asked = configured(made, INIT, OK)
    worktrees = repo.git("worktree", "list")
    with pytest.raises(TroupeError) as caught:
        made.perform(asked)
    assert caught.value.code == "vcs.failed"
    assert repo.git("worktree", "list") == worktrees
    assert list((repo.path / ".troupe" / "local" / "worktrees").iterdir()) == []
    [started] = [u for u in made.updates if u.get("kind") == "started"]
    run_id = started["runId"]
    assert topics(made, run_id) == ["Run.Started", "Run.Ended"]
    outcome = history(made, run_id)[-1]["outcome"]
    assert (outcome["outcome"], outcome["ending"]) == ("could-not-start", "never-started")
    assert outcome["error"]["code"] == "vcs.failed"
    assert "changes" not in history(made, run_id)[-1]


def failing_worktree_made(store: EventStore) -> EventStore:
    """A store whose write of Run.WorktreeMade fails as a full disk would."""
    original = store.record_with_lineage

    def record(events: Any, lineage: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if any(type(event).__qualname__ == "Run.WorktreeMade" for event in events):
            raise TroupeError("artifact.write-failed", problem="No space.", fix="Free some.")
        return original(events, lineage, **kwargs)

    store.record_with_lineage = record  # type: ignore[method-assign]
    return store


def test_a_worktree_made_that_cant_be_recorded_ends_the_run_could_not_start_with_that_error(
    repo: Repo,
) -> None:
    made = harness(repo, store_wrapper=failing_worktree_made)
    asked = configured(made, INIT, OK)
    with pytest.raises(TroupeError) as caught:
        made.perform(asked)
    assert caught.value.code == "artifact.write-failed"
    [started] = [u for u in made.updates if u.get("kind") == "started"]
    run_id = started["runId"]
    assert topics(made, run_id) == ["Run.Started", "Run.Ended"]
    # The end follows the start with no gap: the run was reloaded, not built on the version that
    # counted the unrecorded event.
    assert [e.version for e in made.stores[-1].history(UUID(run_id))] == [1, 2]
    outcome = history(made, run_id)[-1]["outcome"]
    assert (outcome["outcome"], outcome["error"]["code"]) == (
        "could-not-start",
        "artifact.write-failed",
    )
    assert (repo.path / started["worktree"]).is_dir()


def test_a_shared_state_that_cant_be_read_ends_the_run_and_keeps_its_worktree(
    repo: Repo,
) -> None:
    made = harness(repo, store_wrapper=_replacing("shared_state", _vcs_failed))
    asked = configured(made, INIT, OK)
    with pytest.raises(TroupeError) as caught:
        made.perform(asked)
    assert caught.value.code == "vcs.failed"
    [started] = [u for u in made.updates if u.get("kind") == "started"]
    run_id = started["runId"]
    assert topics(made, run_id) == ["Run.Started", "Run.WorktreeMade", "Run.Ended"]
    assert history(made, run_id)[-1]["outcome"]["outcome"] == "could-not-start"
    assert (repo.path / started["worktree"]).is_dir()
    [run] = made.status(run=run_id).runs
    changes = run.to_data()["changes"]
    assert (changes["state"], changes["worktree"]) == ("uncaptured", started["worktree"])


def test_a_worktree_failure_whose_end_cant_be_recorded_names_both_and_reads_interrupted(
    repo: Repo,
) -> None:
    fill_fails = _replacing("fill_worktree", _vcs_failed)
    end_fails = failing_at(-1, end_too=True)
    made = harness(repo, store_wrapper=lambda store: end_fails(fill_fails(store)))
    asked = configured(made, INIT, OK)
    with pytest.raises(TroupeError) as caught:
        made.perform(asked)
    assert caught.value.code == "run.recording-failed"
    details = caught.value.details
    assert details["error"]["code"] == "vcs.failed"
    assert details["endError"]["code"] == "artifact.write-failed"
    assert "failedAt" not in details
    [run] = harness(repo).status(run=details["run"]).runs
    assert run.state == "interrupted"


# Requirement: Every worktree troupe makes is named by an event


@pytest.mark.parametrize(
    ("stop", "steps", "made"),
    [
        ("before-worktree", [INIT, OK], False),
        ("worktree-added", [INIT, OK], True),
        ("before-init", [{"hang": True}], True),
    ],
)
def test_a_perform_killed_before_init_leaves_a_run_that_names_its_worktree_and_discards(
    repo: Repo, stop: str, steps: list[dict[str, Any]], made: bool
) -> None:
    from test_run_changes import call_discard
    from test_run_queries import Child

    configured(harness(repo), *steps)
    child = Child(repo, script(*steps), stop=stop, workspace="worktree")
    worktree = f".troupe/local/worktrees/{child.run_id}"
    assert (repo.path / worktree).is_dir() == made
    child.kill()
    reader = harness(repo)
    result = reader.status(run=child.run_id)
    [run] = result.runs
    assert run.state == "interrupted"
    assert [n.code for n in result.notices] == ["run.interrupted"]
    changes = run.to_data()["changes"]
    assert (changes["state"], changes["worktree"]) == ("uncaptured", worktree)
    call_discard(reader, child.run_id)
    assert not (repo.path / worktree).exists()
    assert worktree not in repo.git("worktree", "list", "--porcelain")
    assert topics(reader, child.run_id)[-1] == "Run.ChangesDiscarded"


# Requirement: The local stage's workspace is the theatre (a worktree is still unenforced)


def test_a_worktree_runs_lineage_still_says_its_effects_were_unenforced(repo: Repo) -> None:
    made = harness(repo)
    run = made.perform(configured(made, INIT, OK)).run
    for event in made.stores[-1].history(UUID(run.run_id)):
        stage = json.loads(event.state)["lineage"]["stage"]
        assert stage == {
            "name": "local",
            "effects": "unenforced",
            "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
        }


# Requirement: The effect check reads the run's workspace


def test_an_expected_file_in_the_worktree_passes_the_effect_check(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(
        made,
        INIT,
        write("out/hello.txt", "hello\n"),
        OK,
        effect={"kind": "files", "paths": ["out/hello.txt"]},
    )
    run = made.perform(asked).run
    assert run.outcome == "succeeded"
    assert not (repo.path / "out" / "hello.txt").exists()


# Requirement: A run's changes are captured when it ends


def test_a_runs_end_records_its_diff_by_reference_with_the_counts(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(
        made, INIT, write("out/hello.txt", "hello\n"), write("src/a.txt", "two\n"), OK
    )
    run = made.perform(asked).run
    changes = history(made, run.run_id)[-1]["changes"]
    assert (changes["added"], changes["modified"], changes["deleted"]) == (1, 1, 0)
    diff = made.backends().artifact_store(made.session()).read(changes["diff"])
    assert b"+hello" in diff
    assert b"+two" in diff
    assert run.changes is not None
    assert run.changes.state == "pending"


def test_a_failed_runs_changes_are_still_captured(repo: Repo) -> None:
    made = harness(repo)
    run = made.perform(configured(made, INIT, write("out/partial.txt", "x\n"), FAIL)).run
    assert run.outcome == "failed"
    assert history(made, run.run_id)[-1]["changes"]["added"] == 1


def test_a_run_that_changes_nothing_records_no_diff_and_state_none(repo: Repo) -> None:
    made = harness(repo)
    run = made.perform(configured(made, INIT, OK)).run
    assert "diff" not in history(made, run.run_id)[-1]["changes"]
    assert run.changes is not None
    assert run.changes.state == "none"


def test_a_worktree_run_whose_runner_never_started_still_records_its_changes(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(perform_module, "runner_command", lambda _: ["troupe-no-such-runner"])
    made = harness(repo)
    run = made.perform(configured(made, INIT, OK)).run
    assert run.outcome == "could-not-start"
    assert history(made, run.run_id)[-1]["changes"]["added"] == 0
    assert worktree_path(repo.path, run.run_id).is_dir()


# Requirement: Changes under .troupe/ are left out of the diff


def test_an_actor_writing_under_troupe_is_left_out_of_the_diff_and_counted(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(
        made, INIT, write(".troupe/events/forged.jsonl", "{}\n"), write("a.txt", "a\n"), OK
    )
    run = made.perform(asked).run
    changes = history(made, run.run_id)[-1]["changes"]
    assert (changes["added"], changes["leftOut"]) == (1, 1)
    diff = made.backends().artifact_store(made.session()).read(changes["diff"])
    assert b".troupe" not in diff


# Requirement: A capture that fails keeps the worktree and is recorded


def test_a_capture_that_fails_is_recorded_and_the_worktree_kept(repo: Repo) -> None:
    made = harness(repo, store_wrapper=_replacing("capture", _vcs_failed))
    run = made.perform(configured(made, INIT, write("a.txt", "a\n"), OK)).run
    changes = history(made, run.run_id)[-1]["changes"]
    assert changes["error"]["code"] == "vcs.failed"
    assert "diff" not in changes
    assert (worktree_path(repo.path, run.run_id) / "a.txt").is_file()
    assert run.changes is not None
    assert run.changes.state == "uncaptured"


# Requirement: The worktree is kept until the changes are accepted or discarded


def test_an_ignored_file_the_run_wrote_is_still_in_its_worktree(repo: Repo) -> None:
    made = harness(repo)
    run = made.perform(configured(made, INIT, write("build/out.bin", "built\n"), OK)).run
    assert (worktree_path(repo.path, run.run_id) / "build" / "out.bin").is_file()
    assert run.changes is not None
    assert run.changes.worktree == f".troupe/local/worktrees/{run.run_id}"


# Requirement: Changes to the shared repository during a run are reported


def test_a_branch_made_during_the_run_is_recorded_and_announced(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(made, INIT, OK)
    made.on_running = lambda: repo.git("branch", "scratch")
    run = made.perform(asked).run
    shared = history(made, run.run_id)[-1]["changes"]["shared"]
    assert shared == {"refs": [{"name": "refs/heads/scratch", "change": "added"}]}
    [notice] = notices(made, "workspace.shared-git-changed")
    assert "refs/heads/scratch added" in notice["problem"]
    assert "won't undo" in notice["problem"]


def test_a_hook_written_during_the_run_is_named_first(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(made, INIT, OK)

    def tag_and_hook() -> None:
        repo.git("tag", "v0")
        (repo.path / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")

    made.on_running = tag_and_hook
    made.perform(asked)
    [notice] = notices(made, "workspace.shared-git-changed")
    assert notice["problem"].index("hook pre-commit added") < notice["problem"].index("refs/tags")
    assert "next time git uses it" in notice["problem"]


def test_a_config_change_during_the_run_is_recorded(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(made, INIT, OK)
    made.on_running = lambda: repo.git("config", "core.hooksPath", "elsewhere-hooks")
    run = made.perform(asked).run
    assert history(made, run.run_id)[-1]["changes"]["shared"]["config"] == [
        {"name": "config", "change": "changed"}
    ]


def test_a_run_that_changes_nothing_shared_records_no_shared_and_sends_no_notice(
    repo: Repo,
) -> None:
    made = harness(repo)
    run = made.perform(configured(made, INIT, write("a.txt", "a\n"), OK)).run
    assert "shared" not in history(made, run.run_id)[-1]["changes"]
    assert notices(made, "workspace.shared-git-changed") == []


# Requirement: Perform says where a worktree run works; rehearsal


def test_the_started_update_names_the_worktree(repo: Repo) -> None:
    made = harness(repo)
    run = made.perform(configured(made, INIT, OK)).run
    [started] = [u for u in made.updates if u.get("kind") == "started"]
    assert started["worktree"] == f".troupe/local/worktrees/{run.run_id}"


def test_rehearsing_a_worktree_perform_names_the_base_and_makes_no_worktree(repo: Repo) -> None:
    made = harness(repo)
    asked = configured(made, INIT, OK, rehearse=True)
    result = made.perform_result(asked)
    assert result.rehearsal is not None
    assert result.rehearsal.workspace.kind == "worktree"
    assert result.rehearsal.workspace.base == repo.git("rev-parse", "HEAD").strip()
    assert not (repo.path / ".troupe" / "local" / "worktrees").exists()


def test_a_run_in_the_theatre_records_workspace_theatre_and_no_changes(repo: Repo) -> None:
    made = harness(repo, env={**ADA, **ALLOW})
    asked = request(script(INIT, write("out/hello.txt", "hello\n"), OK))
    run = made.perform(asked).run
    events = history(made, run.run_id)
    assert events[0]["workspace"] == {"kind": "theatre"}
    assert "changes" not in events[-1]
    assert run.changes is None
    assert (repo.path / "out" / "hello.txt").is_file()


# Requirement: Workspace settings are named (a slow operation is announced)


def test_a_slow_worktree_operation_is_announced_naming_it(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from troupe.core import defaults

    monkeypatch.setattr(defaults, "WORKSPACE_ANNOUNCE_AFTER_SECONDS", 0.05)
    made = harness(repo)
    asked = configured(made, INIT, OK)
    real: list[Any] = []

    def slow(*args: object) -> Any:  # noqa: ANN401
        time.sleep(0.5)
        return real[0](*args)

    def wrap(store: EventStore) -> EventStore:
        real[:] = [store.vcs.differing_from_head]
        store.vcs = _Wrapped(store.vcs, "differing_from_head", slow)
        return store

    made.store_wrapper = wrap
    made.perform(asked)
    operations = [notice["details"]["operation"] for notice in notices(made, "workspace.waiting")]
    assert operations.count("looking for changes the run won't see") == 1

"""The event-store service (spec: lineage, identity, event-store; design D8, D9; #1's rules on
abandoned edits).

Its tests that stay in their own process are in unit/test_event_service.py."""

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from event_service_shared import lineage_of
from gitrepo import make_repo, past_the_racy_window
from storetesting import ADA, Counter, git_service
from troupe.core import strict_json
from troupe.core.events import (
    EventStore,
    Unknown,
)
from troupe_store_text.store import TextStore
from troupe_vcs_git import GitAdapter


def test_an_event_recorded_on_a_git_branch_names_the_adapter_branch_and_head(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    head = repo.commit_all()
    [recorded] = git_service(repo).command(via="cli").record(Counter(value=1).collect_events())
    vcs = lineage_of(repo.path, recorded.event_id)["vcs"]
    assert vcs == {"adapter": "git", "branch": "main", "head": head}


def test_an_event_recorded_on_a_detached_head_names_the_adapter_and_head_and_no_branch(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    head = repo.commit_all()
    repo.git("switch", "-q", "--detach", head)
    [recorded] = git_service(repo).command(via="cli").record(Counter(value=1).collect_events())
    vcs = lineage_of(repo.path, recorded.event_id)["vcs"]
    assert vcs == {"adapter": "git", "head": head}


# What recording costs (spec: event-store, "Recording events runs no version-control command while
# nothing has moved"; cache-vcs-state #75).


def git_commands_to_record(root: Path, events: int) -> int:
    """How many git commands a session runs to record ``events`` events, each through its own
    command, in a fresh git theatre where nothing moves. The actor is known (ADA), so identity
    reads no git config, and the clock is past the racy window: the steady state."""
    repo = make_repo(root)
    repo.commit_all()
    vcs = GitAdapter(repo.path, source=repo.env, now=past_the_racy_window)
    service = EventStore(repo.path, vcs=vcs, recorder=TextStore(repo.path, vcs), env=ADA)
    for value in range(events):
        service.command(via="cli").record(Counter(value=value).collect_events())
    return vcs.commands_run


def test_recording_5_or_50_events_runs_the_same_number_of_git_commands(tmp_path: Path) -> None:
    assert git_commands_to_record(tmp_path / "five", 5) == git_commands_to_record(
        tmp_path / "fifty", 50
    )


GIT_OPERATIONS: dict[str, list[list[str]]] = {
    "commit": [["commit", "-q", "--allow-empty", "-m", "moved"]],
    "switch": [["switch", "-q", "-c", "other"]],
    "merge": [
        ["switch", "-q", "-c", "feature"],
        ["commit", "-q", "--allow-empty", "-m", "feature"],
        ["switch", "-q", "main"],
        ["merge", "-q", "--no-ff", "--no-edit", "feature"],
    ],
    "reset": [["reset", "-q", "--hard", "HEAD~"]],
}


@pytest.mark.parametrize("operation", GIT_OPERATIONS)
def test_lineage_names_the_branch_and_head_after_a_git_operation_within_one_session(
    tmp_path: Path, operation: str
) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all("one")
    repo.commit_all("two")
    service = git_service(repo)  # the real clock and the default racy windows
    service.command(via="cli").record(Counter(value=1).collect_events())
    for args in GIT_OPERATIONS[operation]:
        repo.git(*args)
    [recorded] = service.command(via="cli").record(Counter(value=2).collect_events())
    expected = {
        "adapter": "git",
        "branch": repo.git("symbolic-ref", "--short", "HEAD").strip(),
        "head": repo.git("rev-parse", "HEAD").strip(),
    }
    assert lineage_of(repo.path, recorded.event_id)["vcs"] == expected


RECORD_CHILD = Path(__file__).with_name("record_child.py")

CHILD_LINE_SECONDS = 30.0
"""How long the test waits for each line from record_child.py before failing, so a stuck child
fails the test instead of hanging it."""


def test_lineage_names_the_branch_and_head_when_another_process_moves_git_between_events(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all("one")
    repo.commit_all("two")
    child = subprocess.Popen(
        [sys.executable, str(RECORD_CHILD), str(repo.path), json.dumps(repo.env)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    stdin, stdout = child.stdin, child.stdout
    assert stdin is not None
    assert stdout is not None
    lines: queue.Queue[str] = queue.Queue()

    def read_lines() -> None:
        for line in stdout:
            lines.put(line)

    threading.Thread(target=read_lines, daemon=True).start()

    def next_line() -> str:
        try:
            return lines.get(timeout=CHILD_LINE_SECONDS).strip()
        except queue.Empty:
            raise AssertionError(
                f"record_child.py said nothing for {CHILD_LINE_SECONDS} s"
            ) from None

    def record() -> str:
        stdin.write("record\n")
        stdin.flush()
        word, event_id = next_line().split()
        assert word == "RECORDED"
        return event_id

    try:
        assert next_line() == "READY"
        steps: list[list[list[str]]] = [[], *GIT_OPERATIONS.values(), []]
        for step in steps:
            for args in step:
                repo.git(*args)
            event_id = record()
            branch = repo.git("symbolic-ref", "--short", "HEAD").strip()
            head = repo.git("rev-parse", "HEAD").strip()
            assert lineage_of(repo.path, event_id)["vcs"] == {
                "adapter": "git",
                "branch": branch,
                "head": head,
            }, step
    finally:
        child.kill()
        child.wait(timeout=CHILD_LINE_SECONDS)


def test_reads_return_the_stores_notices(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    git_service(repo).command(via="cli").record(Counter().collect_events())
    repo.git("switch", "-q", "-c", "other")
    assert [n.code for n in git_service(repo).notices()] == ["events.other-branch"]


def test_events_recorded_around_a_stash_and_pop_are_all_present_in_order(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("actors/tester.yaml", "workers: 3\n")
    repo.commit_all()
    counter = Counter(value=3)
    git_service(repo).command(via="cli").record(counter.collect_events())
    for value, git in ((5, ("stash",)), (3, ("stash", "pop")), (5, ())):
        repo.write("actors/tester.yaml", f"workers: {value}\n")
        service = git_service(repo)
        loaded = service.load(counter.id)
        assert isinstance(loaded, Counter)
        loaded.set(value)
        service.command(via="file", actor=Unknown()).record(loaded.collect_events())
        if git:
            repo.git(*git)
    history = git_service(repo).history(counter.id)
    assert [strict_json.loads(r.state)["value"] for r in history] == [3, 5, 3, 5]  # type: ignore[index]

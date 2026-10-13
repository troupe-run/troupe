"""The store in a real git theatre (spec: event-store; design D4, D5, D7)."""

import json
import time
from pathlib import Path
from uuid import uuid4

from event_schemas import is_valid
from gitrepo import Repo, make_repo
from storetesting import event, segments
from troupe_store_text.store import TextStore
from troupe_vcs_git import GitAdapter


def git_store(repo: Repo) -> tuple[TextStore, GitAdapter]:
    vcs = GitAdapter(repo.path, source=repo.env)
    return TextStore(repo.path, vcs), vcs


def test_a_session_runs_no_git_command_per_batch_while_the_branch_is_unchanged(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    store, vcs = git_store(repo)
    stream = uuid4()
    store.insert([event(stream, 1)])
    after_first = vcs.commands_run
    for version in range(2, 22):
        store.insert([event(stream, version)])
    assert vcs.commands_run == after_first


def test_switching_branches_mid_session_starts_a_new_segment(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.commit_all()
    store, _ = git_store(repo)
    store.insert([event(uuid4(), 1)])
    time.sleep(0.01)
    repo.git("switch", "-q", "-c", "feature")
    store.insert([event(uuid4(), 1)])
    branches = [
        json.loads(path.read_bytes().splitlines()[0])["segment"]["branch"]
        for path in segments(repo.path)
    ]
    assert sorted(branches) == ["feature", "main"]


def test_a_session_on_a_detached_head_writes_a_header_with_no_branch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    head = repo.commit_all()
    repo.git("switch", "-q", "--detach", head)
    store, _ = git_store(repo)
    store.insert([event(uuid4(), 1)])
    [segment] = segments(repo.path)
    header = json.loads(segment.read_bytes().splitlines()[0])
    assert header["segment"] == {"session": segment.stem, "vcs": "git"}
    assert is_valid(header, "event-record.schema.json")

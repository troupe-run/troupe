"""The git adapter marks merged paths resolved, against real repositories (spec: vcs, "The git
adapter stages exactly the given bytes" and "The git adapter leaves a path whose stages have
changed"; mark-config-resolved design D4, D5)."""

import subprocess
from pathlib import Path

import pytest

from gitrepo import AUTHOR, Repo, make_repo
from troupe.core.vcs import Marked, Resolve
from troupe_vcs_git import GitAdapter

ACTORS = ".troupe/actors"
YAML = f"{ACTORS}/tester.yaml"
MD = f"{ACTORS}/tester.md"
MERGED = b"runner: merged\n"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return make_repo(tmp_path)


def _write(repo: Repo, relative: str, data: bytes) -> None:
    path = repo.path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)  # these bytes exactly, on Windows too


def _merge(repo: Repo, branch: str = "feature") -> int:
    return subprocess.run(
        ["git", "merge", "-q", "--no-edit", branch],  # noqa: S607 - git from the test's PATH
        cwd=repo.path,
        env={**repo.env, **AUTHOR},
        capture_output=True,
        check=False,
    ).returncode


def _conflict(repo: Repo, path: str = YAML, *, removed: bool = False) -> None:
    """``path`` changed on main and changed (or, with ``removed``, removed) on feature, merged
    into main and left unmerged."""
    _write(repo, path, b"runner: a\n")
    repo.commit_all("base")
    repo.git("switch", "-q", "-c", "feature")
    if removed:
        repo.git("rm", "-q", path)
    else:
        _write(repo, path, b"runner: b\n")
    repo.commit_all("feature")
    repo.git("switch", "-q", "main")
    _write(repo, path, b"runner: c\n")
    repo.commit_all("main")
    assert _merge(repo) != 0


def _adapter(repo: Repo, theatre: Path | None = None) -> GitAdapter:
    return GitAdapter(theatre or repo.path, source=repo.env)


def _mark(repo: Repo, data: bytes | None, theatre: Path | None = None) -> Marked:
    adapter = _adapter(repo, theatre)
    sides = adapter.merge_sides_under(ACTORS)
    return adapter.mark_resolved({path: Resolve(s, data) for path, s in sides.items()})


def _index(repo: Repo) -> list[str]:
    return repo.git("ls-files", "-s").splitlines()


def _staged(repo: Repo, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f":0:{path}"],  # noqa: S607
        cwd=repo.path,
        env=repo.env,
        capture_output=True,
        check=True,
    ).stdout


# Requirement: The git adapter stages exactly the given bytes


def test_a_three_stage_conflict_ends_with_one_stage_0_entry_of_the_given_bytes(repo: Repo) -> None:
    _conflict(repo)
    assert _mark(repo, MERGED) == Marked({YAML: None})
    assert [line.split("\t")[1] for line in _index(repo)] == [YAML]
    assert _index(repo)[0].split(" ")[2].startswith("0\t")
    assert repo.git("ls-files", "-u") == ""
    assert _staged(repo, YAML) == MERGED


def test_after_marking_the_merge_commits_with_no_git_add(repo: Repo) -> None:
    _conflict(repo)
    _write(repo, YAML, MERGED)
    _mark(repo, MERGED)
    repo.git("commit", "-q", "--no-edit")
    assert repo.git("show", "HEAD:" + YAML).encode() == MERGED


def test_a_removal_leaves_no_entry_for_the_path(repo: Repo) -> None:
    _conflict(repo, MD, removed=True)
    assert repo.git("ls-files", "-u", "--", MD) != ""
    assert _mark(repo, None) == Marked({MD: None})
    assert repo.git("ls-files", "-s", "--", MD) == ""


def test_the_index_holds_the_given_bytes_whatever_the_working_file_holds(repo: Repo) -> None:
    _conflict(repo)
    _write(repo, YAML, b"edited after troupe wrote it\n")
    _mark(repo, MERGED)
    assert _staged(repo, YAML) == MERGED
    assert (repo.path / YAML).read_bytes() == b"edited after troupe wrote it\n"


def test_a_theatre_in_a_subdirectory_marks_its_own_path_and_adds_no_top_level_one(
    repo: Repo,
) -> None:
    _conflict(repo, f"sub/{YAML}")
    assert _mark(repo, MERGED, repo.path / "sub") == Marked({YAML: None})
    assert [line.split("\t")[1] for line in _index(repo)] == [f"sub/{YAML}"]
    assert _staged(repo, f"sub/{YAML}") == MERGED


def test_an_executable_ours_keeps_its_mode(repo: Repo) -> None:
    _write(repo, YAML, b"runner: a\n")
    repo.git("add", YAML)
    repo.git("update-index", "--chmod=+x", YAML)
    repo.git("commit", "-q", "-m", "base")
    repo.git("switch", "-q", "-c", "feature")
    _write(repo, YAML, b"runner: b\n")
    repo.git("commit", "-q", "-am", "feature")
    repo.git("switch", "-q", "main")
    _write(repo, YAML, b"runner: c\n")
    repo.git("commit", "-q", "-am", "main")
    assert _merge(repo) != 0
    _mark(repo, MERGED)
    assert _index(repo)[0].startswith("100755 ")


def test_a_sha256_repository_removes_a_path(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo.path / ".git").rename(tmp_path / "unused")  # start again, as a SHA-256 repository
    repo.git("init", "-q", "-b", "main", "--object-format=sha256")
    _conflict(repo, MD, removed=True)
    assert _mark(repo, None) == Marked({MD: None})
    assert repo.git("ls-files", "-s", "--", MD) == ""


def test_another_git_holding_the_index_lock_is_a_failure_that_changes_nothing(repo: Repo) -> None:
    _conflict(repo)
    index = _index(repo)
    lock = repo.path / ".git" / "index.lock"
    lock.write_bytes(b"")
    try:
        marked = _mark(repo, MERGED)
    finally:
        lock.unlink()
    assert marked.paths == {YAML: "failed"}
    assert marked.message is not None
    assert "index.lock" in marked.message
    assert _index(repo) == index


# Requirement: The git adapter leaves a path whose stages have changed


def test_a_path_the_person_resolved_after_the_read_is_left_and_reported_as_changed(
    repo: Repo,
) -> None:
    _conflict(repo)
    adapter = _adapter(repo)
    sides = adapter.merge_sides_under(ACTORS)
    _write(repo, YAML, b"the person's resolution\n")
    repo.git("add", YAML)
    index = _index(repo)
    marked = adapter.mark_resolved({YAML: Resolve(sides[YAML], MERGED)})
    assert marked == Marked({YAML: "index-changed"})
    assert _index(repo) == index


def test_an_aborted_merge_marks_nothing_and_is_reported_as_changed(repo: Repo) -> None:
    _conflict(repo)
    adapter = _adapter(repo)
    sides = adapter.merge_sides_under(ACTORS)
    repo.git("merge", "--abort")
    index = _index(repo)
    marked = adapter.mark_resolved({YAML: Resolve(sides[YAML], MERGED)})
    assert marked == Marked({YAML: "index-changed"})
    assert _index(repo) == index


def test_a_changed_path_doesnt_stop_another_from_being_marked(repo: Repo) -> None:
    _write(repo, YAML, b"runner: a\n")
    _write(repo, MD, b"a\n")
    repo.commit_all("base")
    repo.git("switch", "-q", "-c", "feature")
    _write(repo, YAML, b"runner: b\n")
    _write(repo, MD, b"b\n")
    repo.commit_all("feature")
    repo.git("switch", "-q", "main")
    _write(repo, YAML, b"runner: c\n")
    _write(repo, MD, b"c\n")
    repo.commit_all("main")
    assert _merge(repo) != 0
    adapter = _adapter(repo)
    sides = adapter.merge_sides_under(ACTORS)
    repo.git("add", MD)
    marked = adapter.mark_resolved(
        {YAML: Resolve(sides[YAML], MERGED), MD: Resolve(sides[MD], b"merged\n")}
    )
    assert marked == Marked({YAML: None, MD: "index-changed"})
    assert _staged(repo, YAML) == MERGED
    assert _staged(repo, MD) == (repo.path / MD).read_bytes()  # what the person's git add staged

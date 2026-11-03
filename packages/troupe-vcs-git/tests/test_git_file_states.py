"""The git adapter's file states, which the audit of a run's changes compares (spec: effects, "The
audit sees changes as git sees them"; declared-effects design D4)."""

from pathlib import Path

import pytest

from gitrepo import Repo, make_repo
from test_git_worktrees import adapter, git_in, put, worktree


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    repo = make_repo(tmp_path)
    put(repo, "src/a.txt", "one\n")
    put(repo, "src/b.txt", "bee\n")
    put(repo, ".troupe/events/x.jsonl", "{}\n")
    put(repo, ".gitignore", "build/\n")
    repo.commit_all("base")
    return repo


def test_a_clean_theatre_lists_its_tracked_files_and_leaves_out_troupes_own(repo: Repo) -> None:
    states = adapter(repo).file_states(repo.path)
    assert sorted(states) == [".gitignore", "src/a.txt", "src/b.txt"]


def test_a_clean_theatre_matches_its_head(repo: Repo) -> None:
    git = adapter(repo)
    head = git.head()
    assert head is not None
    assert git.file_states(repo.path) == git.file_states(repo.path, at=head)


def test_a_modified_file_has_a_new_id_and_the_others_keep_theirs(repo: Repo) -> None:
    git = adapter(repo)
    before = git.file_states(repo.path)
    put(repo, "src/a.txt", "edited\n")
    after = git.file_states(repo.path)
    assert after["src/a.txt"] != before["src/a.txt"]
    assert after["src/b.txt"] == before["src/b.txt"]


def test_an_untracked_file_is_listed_and_an_ignored_one_isnt(repo: Repo) -> None:
    put(repo, "loose.txt", "loose\n")
    put(repo, "build/ignored.bin", "ignored\n")
    states = adapter(repo).file_states(repo.path)
    assert "loose.txt" in states
    assert "build/ignored.bin" not in states


def test_a_deleted_file_is_gone_and_a_staged_one_is_listed(repo: Repo) -> None:
    (repo.path / "src" / "b.txt").unlink()
    put(repo, "new.txt", "new\n")
    repo.git("add", "new.txt")
    states = adapter(repo).file_states(repo.path)
    assert "src/b.txt" not in states
    assert "new.txt" in states


def test_the_same_content_has_the_same_id_wherever_it_is(repo: Repo) -> None:
    put(repo, "copy.txt", "one\n")
    states = adapter(repo).file_states(repo.path)
    assert states["copy.txt"] == states["src/a.txt"]


def test_a_change_under_troupe_isnt_listed(repo: Repo) -> None:
    put(repo, ".troupe/events/x.jsonl", "{}\n{}\n")
    put(repo, ".troupe/local/new.txt", "x\n")
    assert all(not path.startswith(".troupe/") for path in adapter(repo).file_states(repo.path))


def test_a_path_with_spaces_and_non_ascii_characters_is_listed_as_it_is(repo: Repo) -> None:
    put(repo, "notes/a file é.txt", "x\n")
    put(repo, "notes/tracked ü.txt", "y\n")
    repo.git("add", "notes/tracked ü.txt")
    states = adapter(repo).file_states(repo.path)
    assert "notes/a file é.txt" in states
    assert "notes/tracked ü.txt" in states


def test_a_theatre_in_a_subdirectory_lists_only_its_own_files_relative_to_it(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    put(repo, "outside.txt", "o\n")
    put(repo, "theatre/inside.txt", "i\n")
    put(repo, "theatre/.troupe/events/x.jsonl", "{}\n")
    repo.commit_all("base")
    put(repo, "theatre/loose.txt", "l\n")
    states = adapter(repo).file_states(repo.path / "theatre")
    assert sorted(states) == ["inside.txt", "loose.txt"]


def test_a_worktree_counts_what_the_actor_committed_against_its_baseline(
    repo: Repo, tmp_path: Path
) -> None:
    git, path, baseline = worktree(repo, tmp_path)
    before = git.file_states(path, at=baseline)
    (path / "src" / "a.txt").write_bytes(b"committed\n")
    git_in(repo, path, "commit", "-qam", "the actor's commit")
    (path / "src" / "b.txt").write_bytes(b"uncommitted\n")
    after = git.file_states(path)
    assert sorted(before) == sorted(after)
    assert after["src/a.txt"] != before["src/a.txt"]
    assert after["src/b.txt"] != before["src/b.txt"]
    assert after[".gitignore"] == before[".gitignore"]

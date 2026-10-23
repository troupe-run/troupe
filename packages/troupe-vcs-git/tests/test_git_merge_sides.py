"""The git adapter's merge sides, against real repositories (spec: vcs; config-projection-conflicts
design D2, D3)."""

import subprocess
from pathlib import Path

import pytest

from gitrepo import AUTHOR, Repo, make_repo
from troupe.core.vcs import MergeSides
from troupe_vcs_git import GitAdapter

ACTORS = ".troupe/actors"
YAML = f"{ACTORS}/tester.yaml"
MD = f"{ACTORS}/tester.md"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return make_repo(tmp_path)


def _sides(repo: Repo, theatre: Path | None = None) -> dict[str, MergeSides]:
    adapter = GitAdapter(theatre or repo.path, source=repo.env)
    return dict(adapter.merge_sides_under(ACTORS))


def _write(repo: Repo, relative: str, data: bytes) -> None:
    path = repo.path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)  # these bytes exactly, on Windows too


def _git_may_fail(repo: Repo, *args: str) -> int:
    """Run git where a non-zero exit (a merge that stops on a conflict) is expected."""
    completed = subprocess.run(
        ["git", *args],  # noqa: S607 - git from the test environment's PATH
        cwd=repo.path,
        env={**repo.env, **AUTHOR},
        capture_output=True,
        check=False,
    )
    return completed.returncode


def _branches(
    repo: Repo, base: dict[str, bytes | None], **branches: dict[str, bytes | None]
) -> None:
    """Commit ``base`` on main, then each branch's files on its own branch from it, ending on
    main. A value of None removes the file."""
    for relative, data in base.items():
        if data is not None:
            _write(repo, relative, data)
    repo.commit_all("base")
    for name, files in branches.items():
        if name != "main":
            repo.git("switch", "-q", "-c", name, "main")
        else:
            repo.git("switch", "-q", "main")
        for relative, data in files.items():
            if data is None:
                (repo.path / relative).unlink()
            else:
                _write(repo, relative, data)
        repo.commit_all(name)
    repo.git("switch", "-q", "main")


CHARACTER = b"First paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n"
FIRST_EDITED = CHARACTER.replace(b"First", b"Edited first")
THIRD_EDITED = CHARACTER.replace(b"Third", b"Edited third")
BOTH_EDITED = FIRST_EDITED.replace(b"Third", b"Edited third")


# Requirement: The git adapter reads a conflicted path's sides from the index


def test_a_content_conflict_reports_both_sides_byte_for_byte(repo: Repo) -> None:
    _branches(
        repo, {YAML: b"runner: a\n"}, feature=({YAML: b"runner: b\n"}), main={YAML: b"runner: c\n"}
    )
    assert _git_may_fail(repo, "merge", "-q", "--no-edit", "feature") != 0
    assert _sides(repo) == {YAML: MergeSides("conflicted", (b"runner: c\n", b"runner: b\n"))}


def test_a_modify_delete_conflict_reports_the_removed_side_as_absent(repo: Repo) -> None:
    _branches(repo, {MD: b"Old.\n"}, feature={MD: b"New.\n"}, main={MD: None})
    assert _git_may_fail(repo, "merge", "-q", "--no-edit", "feature") != 0
    assert _sides(repo) == {MD: MergeSides("conflicted", (None, b"New.\n"))}


def test_a_cherry_pick_that_stops_on_the_file_reports_it_conflicted(repo: Repo) -> None:
    _branches(
        repo, {YAML: b"runner: a\n"}, feature={YAML: b"runner: b\n"}, main={YAML: b"runner: c\n"}
    )
    assert _git_may_fail(repo, "cherry-pick", "feature") != 0
    assert _sides(repo) == {YAML: MergeSides("conflicted", (b"runner: c\n", b"runner: b\n"))}


def test_a_theatre_in_a_subdirectory_gets_theatre_relative_paths(repo: Repo) -> None:
    nested = f"sub/{YAML}"
    _branches(repo, {nested: b"a\n"}, feature={nested: b"b\n"}, main={nested: b"c\n"})
    assert _git_may_fail(repo, "merge", "-q", "--no-edit", "feature") != 0
    assert _sides(repo, repo.path / "sub") == {YAML: MergeSides("conflicted", (b"c\n", b"b\n"))}


def test_a_conflicted_path_outside_the_directory_is_left_out(repo: Repo) -> None:
    _branches(
        repo, {"notes.txt": b"a\n"}, feature={"notes.txt": b"b\n"}, main={"notes.txt": b"c\n"}
    )
    assert _git_may_fail(repo, "merge", "-q", "--no-edit", "feature") != 0
    assert _sides(repo) == {}


# Requirement: The git adapter reports a clean merge only when it reproduces it


def test_a_clean_merge_in_progress_reports_the_parents_and_what_the_index_holds(repo: Repo) -> None:
    _branches(
        repo,
        {MD: CHARACTER, YAML: b"runner: a\n"},
        feature={MD: FIRST_EDITED, YAML: b"runner: b\n"},
        main={MD: THIRD_EDITED, YAML: b"runner: c\n"},
    )
    assert _git_may_fail(repo, "merge", "-q", "--no-edit", "feature") != 0  # stopped by YAML
    sides = _sides(repo)
    assert sides[MD] == MergeSides("clean", (THIRD_EDITED, FIRST_EDITED), BOTH_EDITED)
    assert sides[YAML].kind == "conflicted"


def test_a_committed_clean_merge_reports_each_parents_version(repo: Repo) -> None:
    _branches(repo, {MD: CHARACTER}, feature={MD: FIRST_EDITED}, main={MD: THIRD_EDITED})
    repo.git("merge", "-q", "--no-edit", "feature")
    assert _sides(repo) == {MD: MergeSides("clean", (THIRD_EDITED, FIRST_EDITED), BOTH_EDITED)}


def test_a_merge_commit_edited_before_it_was_committed_is_left_out(repo: Repo) -> None:
    _branches(repo, {MD: CHARACTER}, feature={MD: FIRST_EDITED}, main={MD: THIRD_EDITED})
    repo.git("merge", "-q", "--no-commit", "--no-ff", "feature")
    _write(repo, MD, BOTH_EDITED + b"Added by hand.\n")
    repo.commit_all("merge")
    assert _sides(repo) == {}


def test_a_merge_committed_with_its_conflict_markers_is_left_out(repo: Repo) -> None:
    _branches(
        repo, {YAML: b"runner: a\n"}, feature={YAML: b"runner: b\n"}, main={YAML: b"runner: c\n"}
    )
    assert _git_may_fail(repo, "merge", "-q", "--no-edit", "feature") != 0
    repo.commit_all("merge, markers and all")
    assert _sides(repo) == {}


def test_an_octopus_merge_reports_no_clean_merges(repo: Repo) -> None:
    other = f"{ACTORS}/other.md"
    _branches(
        repo,
        {MD: CHARACTER, other: CHARACTER},
        one={MD: FIRST_EDITED},
        two={other: FIRST_EDITED},
        main={MD: THIRD_EDITED},
    )
    repo.git("merge", "-q", "--no-edit", "one", "two")
    assert len(repo.git("rev-parse", "HEAD^@").split()) == 3
    assert _sides(repo) == {}


def test_a_single_parent_head_with_no_merge_in_progress_reports_none(repo: Repo) -> None:
    _branches(repo, {MD: CHARACTER}, main={MD: THIRD_EDITED})
    assert _sides(repo) == {}


def test_a_path_the_merge_left_equal_to_one_parent_is_left_out(repo: Repo) -> None:
    other = f"{ACTORS}/other.md"
    _branches(
        repo,
        {MD: CHARACTER, other: CHARACTER},
        feature={other: FIRST_EDITED},
        main={MD: THIRD_EDITED},
    )
    repo.git("merge", "-q", "--no-edit", "feature")
    assert _sides(repo) == {}


def test_before_the_first_commit_there_are_no_merge_sides(repo: Repo) -> None:
    _write(repo, MD, CHARACTER)
    assert _sides(repo) == {}

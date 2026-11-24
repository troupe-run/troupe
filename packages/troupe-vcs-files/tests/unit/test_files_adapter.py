"""The plain filesystem adapter (spec: vcs, "The plain filesystem adapter")."""

from pathlib import Path

import pytest

from troupe.core.errors import TroupeError
from troupe.core.vcs import Marked, MergeSides, Resolve, is_committed, load_vcs


def test_it_reports_no_branch_no_head_and_no_identity(tmp_path: Path) -> None:
    vcs = load_vcs("files", tmp_path)
    assert vcs.name == "files"
    assert vcs.branch() is None
    assert vcs.head() is None
    assert vcs.configured_identities() == ()


def test_every_file_counts_as_committed(tmp_path: Path) -> None:
    (tmp_path / ".troupe" / "events").mkdir(parents=True)
    (tmp_path / ".troupe" / "events" / "a.jsonl").write_text("{}\n", encoding="utf-8")
    vcs = load_vcs("files", tmp_path)
    assert vcs.committed_under(".troupe/events") == {".troupe/events/a.jsonl"}
    assert is_committed(vcs, ".troupe/events/a.jsonl")


def test_a_missing_directory_has_nothing_committed_under_it(tmp_path: Path) -> None:
    assert load_vcs("files", tmp_path).committed_under(".troupe/events") == frozenset()


def test_it_reports_no_merge_sides_even_for_a_file_holding_conflict_markers(
    tmp_path: Path,
) -> None:
    actors = tmp_path / ".troupe" / "actors"
    actors.mkdir(parents=True)
    (actors / "tester.yaml").write_bytes(b"<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\n")
    assert load_vcs("files", tmp_path).merge_sides_under(".troupe/actors") == {}


def test_it_marks_nothing_resolved_and_says_it_has_no_index(tmp_path: Path) -> None:
    path = tmp_path / ".troupe/actors/tester.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"<<<<<<< ours\n")
    resolve = Resolve(MergeSides("conflicted", (b"a\n", b"b\n")), b"c\n")
    marked = load_vcs("files", tmp_path).mark_resolved({".troupe/actors/tester.yaml": resolve})
    assert marked == Marked({".troupe/actors/tester.yaml": "no-index"})
    assert path.read_bytes() == b"<<<<<<< ours\n"


def test_its_branch_token_never_changes(tmp_path: Path) -> None:
    vcs = load_vcs("files", tmp_path)
    before = vcs.branch_token()
    (tmp_path / "new.txt").write_text("x", encoding="utf-8")
    assert vcs.branch_token() == before


def test_an_unknown_adapter_is_refused_naming_the_installed_ones(tmp_path: Path) -> None:
    with pytest.raises(TroupeError) as caught:
        load_vcs("svn", tmp_path)
    assert caught.value.code == "vcs.unknown-adapter"
    assert {"files", "git"} <= set(caught.value.details["installed"])


# Requirement: The VCS port can make, diff, apply and remove worktrees

WORKTREE_CALLS: dict[str, tuple[object, ...]] = {
    "theatre_prefix": (),
    "differing_from_head": (),
    "add_worktree": (Path("wt"), "HEAD"),
    "fill_worktree": (Path("wt"), lambda source, destination: "copy", frozenset()),
    "capture": (Path("wt"), "HEAD", (".troupe",), Path("out.diff")),
    "check_apply": (Path("out.diff"),),
    "apply": (Path("out.diff"),),
    "remove_worktree": (Path("wt"),),
}


@pytest.mark.parametrize("operation", sorted(WORKTREE_CALLS))
def test_every_worktree_operation_is_refused_naming_the_adapter(
    tmp_path: Path, operation: str
) -> None:
    vcs = load_vcs("files", tmp_path)
    with pytest.raises(TroupeError) as caught:
        getattr(vcs, operation)(*WORKTREE_CALLS[operation])
    assert caught.value.code == "vcs.worktrees-unsupported"
    assert caught.value.details == {"adapter": "files"}
    assert list(tmp_path.iterdir()) == []


def test_its_shared_state_is_empty_and_never_changes(tmp_path: Path) -> None:
    vcs = load_vcs("files", tmp_path)
    assert vcs.shared_state().compare(vcs.shared_state()).empty


def test_every_directory_counts_as_being_in_a_repository(tmp_path: Path) -> None:
    load_vcs("files", tmp_path / "anywhere").check_repository()


# The audit's file states (spec: effects, "The audit sees changes as git sees them";
# declared-effects design D4)


def _write(root: Path, relative: str, data: bytes) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_file_states_list_every_file_but_git_and_troupes_own(tmp_path: Path) -> None:
    _write(tmp_path, "src/a.txt", b"one\n")
    _write(tmp_path, "build/out.bin", b"\x00")  # no ignore rules: it counts
    _write(tmp_path, ".git/config", b"x")
    _write(tmp_path, ".troupe/events/a.jsonl", b"{}\n")
    _write(tmp_path, "notes/a file é.txt", b"n\n")
    states = load_vcs("files", tmp_path).file_states(tmp_path)
    assert sorted(states) == ["build/out.bin", "notes/a file é.txt", "src/a.txt"]


def test_file_states_change_with_content_and_match_for_the_same_bytes(tmp_path: Path) -> None:
    vcs = load_vcs("files", tmp_path)
    _write(tmp_path, "a.txt", b"one\n")
    _write(tmp_path, "b.txt", b"one\n")
    before = vcs.file_states(tmp_path)
    assert before["a.txt"] == before["b.txt"]
    _write(tmp_path, "a.txt", b"two\n")
    assert vcs.file_states(tmp_path)["a.txt"] != before["a.txt"]


def test_file_states_at_a_commit_are_refused_with_no_history(tmp_path: Path) -> None:
    with pytest.raises(TroupeError) as caught:
        load_vcs("files", tmp_path).file_states(tmp_path, at="abc")
    assert caught.value.code == "vcs.worktrees-unsupported"

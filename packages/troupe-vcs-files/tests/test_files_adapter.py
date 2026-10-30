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

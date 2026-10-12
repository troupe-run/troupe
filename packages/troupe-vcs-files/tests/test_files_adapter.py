"""The plain filesystem adapter (spec: vcs, "The plain filesystem adapter")."""

from pathlib import Path

import pytest

from troupe.core.errors import TroupeError
from troupe.core.vcs import is_committed, load_vcs


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

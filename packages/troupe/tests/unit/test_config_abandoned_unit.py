"""The keep record of abandoned config edits: no record means none kept, an unreadable record counts
as none and is named in a notice, and keeping twice records one entry and prunes changes that are
gone (spec: config-hand-edits; abandoned-edits design D7).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_config_abandoned.py."""

from pathlib import Path

from troupe.core.config.abandoned import (
    KEPT,
    kept,
    write_kept,
)

# The keep record (design D7)


def test_no_record_means_none_kept(tmp_path: Path) -> None:
    assert kept(tmp_path) == (frozenset(), [])


def test_an_unreadable_record_counts_as_none_and_is_named(tmp_path: Path) -> None:
    (tmp_path / KEPT).parent.mkdir(parents=True)
    (tmp_path / KEPT).write_bytes(b"{not json")
    found, notices = kept(tmp_path)
    assert found == frozenset()
    assert [(n.code, n.path) for n in notices] == [("config.kept-unreadable", str(tmp_path / KEPT))]


def test_keeping_twice_records_one_entry_and_prunes_gone_changes(tmp_path: Path) -> None:
    write_kept(tmp_path, frozenset({"a", "gone"}), frozenset({"a", "b"}))
    write_kept(tmp_path, kept(tmp_path)[0] | {"a"}, frozenset({"a", "b"}))
    assert kept(tmp_path) == (frozenset({"a"}), [])
    assert (tmp_path / KEPT).read_bytes() == b'["a"]\n'

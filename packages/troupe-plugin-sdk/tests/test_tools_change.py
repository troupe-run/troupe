"""Write, Edit, Delete and Move (spec: runner-tools, "Writing and editing", "Deleting and moving",
"A failing call is an error result"; runner-sdk design D8)."""

import os
import stat
import sys
from pathlib import Path

import pytest

from sdk_tools import call, workspace
from troupe_plugin_sdk.effects import Effects
from troupe_plugin_sdk.tools import Tools

EVERYTHING = Effects(write=("**",), delete=("**",), move=("**",))


def _tools(tmp_path: Path, files: dict[str, bytes] | None = None) -> tuple[Tools, Path]:
    root = workspace(tmp_path, files)
    return Tools(root, EVERYTHING), root


# Write


def test_writing_a_new_file_in_a_new_directory_makes_it_with_exactly_the_content(
    tmp_path: Path,
) -> None:
    tools, root = _tools(tmp_path)
    step = call(tools, "Write", {"file_path": "out/new/a.txt", "content": "héllo"})
    assert (step.is_error, step.output) == (False, "Wrote 6 bytes to out/new/a.txt.")
    assert (root / "out" / "new" / "a.txt").read_bytes() == "héllo".encode()


@pytest.mark.parametrize("content", ["a\nb\n", "a\r\nb\r\n", "no newline"])
def test_writing_keeps_the_contents_bytes_exactly_on_every_platform(
    tmp_path: Path, content: str
) -> None:
    tools, root = _tools(tmp_path)
    call(tools, "Write", {"file_path": "a.txt", "content": content})
    assert (root / "a.txt").read_bytes() == content.encode()


def test_writing_replaces_a_whole_file_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"a.txt": b"old content that is longer"})
    call(tools, "Write", {"file_path": "a.txt", "content": "new"})
    assert (root / "a.txt").read_bytes() == b"new"
    assert [p.name for p in root.iterdir()] == ["a.txt"]


def test_writing_onto_a_directory_is_an_error(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"src/a.py": b""})
    step = call(tools, "Write", {"file_path": "src", "content": "x"})
    assert step.is_error
    assert step.output == "src is a directory, not a file."
    assert (root / "src" / "a.py").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no executable mode bit")
def test_writing_and_editing_keep_an_executable_files_mode(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"run.sh": b"echo a\n"})
    script = root / "run.sh"
    script.chmod(0o755)
    call(tools, "Edit", {"file_path": "run.sh", "old_string": "a", "new_string": "b"})
    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    call(tools, "Write", {"file_path": "run.sh", "content": "echo c\n"})
    assert stat.S_IMODE(script.stat().st_mode) == 0o755


def test_writing_a_read_only_file_keeps_it_read_only_or_fails_leaving_it_unchanged(
    tmp_path: Path,
) -> None:
    # On POSIX the directory's mode governs the replace, so it succeeds and the read-only mode is
    # copied. On Windows the read-only bit makes the replace fail: the call is an error that names
    # no host path, and the file is unchanged.
    tools, root = _tools(tmp_path, {"locked.txt": b"a"})
    locked = root / "locked.txt"
    locked.chmod(stat.S_IREAD)
    try:
        step = call(tools, "Write", {"file_path": "locked.txt", "content": "b"})
        if step.is_error:
            assert step.output.startswith("Write on locked.txt failed: ")
            assert locked.read_bytes() == b"a"
            assert str(root) not in step.output
        else:
            assert not os.access(locked, os.W_OK)
    finally:
        locked.chmod(stat.S_IREAD | stat.S_IWRITE)


# Edit


def test_editing_replaces_the_one_occurrence_and_keeps_crlf_line_endings(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"a.py": b"x = 1\r\ny = 2\r\n"})
    step = call(tools, "Edit", {"file_path": "a.py", "old_string": "y = 2", "new_string": "y = 3"})
    assert step.output == "Replaced 1 occurrence in a.py."
    assert (root / "a.py").read_bytes() == b"x = 1\r\ny = 3\r\n"


def test_an_ambiguous_edit_is_an_error_giving_the_count_and_the_file_is_unchanged(
    tmp_path: Path,
) -> None:
    tools, root = _tools(tmp_path, {"a.txt": b"a a"})
    step = call(tools, "Edit", {"file_path": "a.txt", "old_string": "a", "new_string": "b"})
    assert step.is_error
    assert "occurs 2 times" in step.output
    assert (root / "a.txt").read_bytes() == b"a a"


def test_replace_all_replaces_every_occurrence(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"a.txt": b"a a a"})
    step = call(
        tools,
        "Edit",
        {"file_path": "a.txt", "old_string": "a", "new_string": "b", "replace_all": True},
    )
    assert step.output == "Replaced 3 occurrences in a.txt."
    assert (root / "a.txt").read_bytes() == b"b b b"


@pytest.mark.parametrize(
    ("old", "new", "says"),
    [
        ("missing", "x", "old_string isn't in a.txt"),
        ("", "x", "old_string is empty"),
        ("a", "a", "the same"),
    ],
)
def test_an_edit_that_cant_apply_is_an_error_and_the_file_is_unchanged(
    tmp_path: Path, old: str, new: str, says: str
) -> None:
    tools, root = _tools(tmp_path, {"a.txt": b"a"})
    step = call(tools, "Edit", {"file_path": "a.txt", "old_string": old, "new_string": new})
    assert step.is_error
    assert says in step.output
    assert (root / "a.txt").read_bytes() == b"a"


def test_editing_a_missing_file_is_an_error(tmp_path: Path) -> None:
    tools, _ = _tools(tmp_path)
    step = call(tools, "Edit", {"file_path": "a.txt", "old_string": "a", "new_string": "b"})
    assert (step.is_error, step.output) == (True, "a.txt doesn't exist.")


# Delete


def test_deleting_a_file_removes_it(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"out/old.txt": b"x"})
    step = call(tools, "Delete", {"file_path": "out/old.txt"})
    assert step.output == "Deleted out/old.txt."
    assert not (root / "out" / "old.txt").exists()
    assert (root / "out").is_dir()


def test_deleting_a_directory_is_an_error_saying_only_files_can_be_deleted(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"src/a.py": b""})
    step = call(tools, "Delete", {"file_path": "src"})
    assert step.is_error
    assert "Only files can be deleted" in step.output
    assert (root / "src" / "a.py").exists()


def test_deleting_a_missing_file_is_an_error(tmp_path: Path) -> None:
    tools, _ = _tools(tmp_path)
    assert call(tools, "Delete", {"file_path": "gone.txt"}).output == "gone.txt doesn't exist."


# Move


def test_moving_into_a_new_directory_makes_it(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"drafts/a.md": b"# a"})
    step = call(tools, "Move", {"source": "drafts/a.md", "destination": "drafts/old/a.md"})
    assert step.output == "Moved drafts/a.md to drafts/old/a.md."
    assert (root / "drafts" / "old" / "a.md").read_bytes() == b"# a"
    assert not (root / "drafts" / "a.md").exists()


def test_moving_onto_an_existing_file_is_an_error_and_both_are_unchanged(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, {"a.txt": b"a", "b.txt": b"b"})
    step = call(tools, "Move", {"source": "a.txt", "destination": "b.txt"})
    assert step.is_error
    assert "b.txt already exists" in step.output
    assert ((root / "a.txt").read_bytes(), (root / "b.txt").read_bytes()) == (b"a", b"b")


def test_moving_a_missing_file_is_an_error(tmp_path: Path) -> None:
    tools, _ = _tools(tmp_path)
    step = call(tools, "Move", {"source": "a.txt", "destination": "b.txt"})
    assert (step.is_error, step.output) == (True, "a.txt doesn't exist.")

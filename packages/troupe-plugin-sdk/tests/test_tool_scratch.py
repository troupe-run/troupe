"""The run's scratch directory, which needs no effect, and .troupe/, which no effect allows
changing (spec: runner-tools, "The scratch directory needs no effect", "Paths are
workspace-relative", "The repository's metadata is out of reach" and "Tool definitions tell the
model where it may work"; declared-effects design D7)."""

import os
import sys
from pathlib import Path

import pytest

from sdk_tools import call, workspace
from troupe_plugin_sdk import paths
from troupe_plugin_sdk.effects import READ_ONLY, Effects
from troupe_plugin_sdk.tools import Tools


def _scratch(tmp_path: Path) -> Path:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return scratch


def test_a_read_only_actor_writes_to_scratch_and_nothing_in_the_workspace_changes(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path, {"README.md": b"hi\n"})
    scratch = _scratch(tmp_path)
    tools = Tools(root, READ_ONLY, scratch=scratch)
    target = str(scratch / "notes.txt")
    step = call(tools, "Write", {"file_path": target, "content": "draft"})
    assert not step.is_error, step.output
    assert (scratch / "notes.txt").read_text(encoding="utf-8") == "draft"
    assert sorted(p.name for p in root.iterdir()) == ["README.md"]


def test_every_changing_tool_works_in_scratch_for_a_read_only_actor(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    scratch = _scratch(tmp_path)
    tools = Tools(root, READ_ONLY, scratch=scratch)
    a, b = str(scratch / "a.txt"), str(scratch / "sub" / "b.txt")
    assert not call(tools, "Write", {"file_path": a, "content": "one two"}).is_error
    edit = {"file_path": a, "old_string": "one", "new_string": "three"}
    assert not call(tools, "Edit", edit).is_error
    assert not call(tools, "Read", {"file_path": a}).is_error
    assert not call(tools, "Move", {"source": a, "destination": b}).is_error
    assert call(tools, "Glob", {"pattern": "**/*.txt", "path": str(scratch)}).output == b
    assert (
        call(tools, "Grep", {"pattern": "three", "path": str(scratch)}).output == f"{b}:1:three two"
    )
    assert not call(tools, "Delete", {"file_path": b}).is_error
    assert not (scratch / "sub" / "b.txt").exists()


def test_moving_a_scratch_file_into_the_workspace_needs_write_for_the_destination(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    scratch = _scratch(tmp_path)
    (scratch / "report.md").write_bytes(b"r")
    tools = Tools(root, Effects(write=("out/**",)), scratch=scratch)
    refused = call(
        tools, "Move", {"source": str(scratch / "report.md"), "destination": "src/report.md"}
    )
    assert refused.is_error
    assert "write effect for src/report.md" in refused.output
    moved = call(
        tools, "Move", {"source": str(scratch / "report.md"), "destination": "out/report.md"}
    )
    assert not moved.is_error, moved.output
    assert (root / "out" / "report.md").read_bytes() == b"r"


def test_moving_a_workspace_file_out_to_scratch_needs_delete_for_the_source(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path, {"a.txt": b"a"})
    scratch = _scratch(tmp_path)
    tools = Tools(root, Effects(move=("**",)), scratch=scratch)
    step = call(tools, "Move", {"source": "a.txt", "destination": str(scratch / "a.txt")})
    assert step.is_error
    assert "delete effect for a.txt" in step.output
    assert (root / "a.txt").exists()


def test_a_scratch_path_that_climbs_out_is_refused(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    scratch = _scratch(tmp_path)
    tools = Tools(root, READ_ONLY, scratch=scratch)
    escape = str(scratch) + os.sep + ".." + os.sep + "escape.txt"
    step = call(tools, "Write", {"file_path": escape, "content": "x"})
    assert step.is_error
    assert "'..'" in step.output
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="a symbolic link needs a privilege on Windows")
def test_a_link_out_of_scratch_is_refused(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    scratch = _scratch(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (scratch / "out").symlink_to(outside, target_is_directory=True)
    tools = Tools(root, READ_ONLY, scratch=scratch)
    step = call(tools, "Write", {"file_path": str(scratch / "out" / "a.txt"), "content": "x"})
    assert step.is_error
    assert "outside the scratch directory" in step.output
    assert not (outside / "a.txt").exists()


def test_an_absolute_path_outside_scratch_names_the_scratch_directory(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    scratch = _scratch(tmp_path)
    tools = Tools(root, READ_ONLY, scratch=scratch)
    elsewhere = str(tmp_path / "elsewhere.txt")
    step = call(tools, "Read", {"file_path": elsewhere})
    assert step.is_error
    assert "relative to the workspace" in step.output
    assert str(scratch) in step.output


def test_with_no_scratch_an_absolute_path_says_the_run_has_none(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    tools = Tools(root, READ_ONLY)
    step = call(tools, "Write", {"file_path": str(tmp_path / "a.txt"), "content": "x"})
    assert step.is_error
    assert "no scratch directory" in step.output
    assert not (tmp_path / "a.txt").exists()


def test_scratch_inside_the_workspace_is_refused(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    (root / "tmp").mkdir()
    with pytest.raises(ValueError, match="overlap"):
        Tools(root, READ_ONLY, scratch=root / "tmp")


def test_writing_into_troupe_is_refused_whatever_the_effects(tmp_path: Path) -> None:
    root = workspace(tmp_path, {".troupe/actors/lead.yaml": b"runner: scripted\n"})
    tools = Tools(root, Effects(write=("**",)))
    step = call(tools, "Write", {"file_path": ".troupe/actors/lead.yaml", "content": "x"})
    assert step.is_error
    assert ".troupe/, troupe's own state" in step.output
    assert (root / ".troupe" / "actors" / "lead.yaml").read_bytes() == b"runner: scripted\n"


def test_moving_out_of_troupe_is_refused_naming_the_source(tmp_path: Path) -> None:
    root = workspace(tmp_path, {".troupe/events/a.jsonl": b"{}\n"})
    tools = Tools(root, Effects(move=("**",)))
    step = call(tools, "Move", {"source": ".troupe/events/a.jsonl", "destination": "a.jsonl"})
    assert step.is_error
    assert ".troupe/events/a.jsonl" in step.output
    assert (root / ".troupe" / "events" / "a.jsonl").exists()
    assert not (root / "a.jsonl").exists()


def test_reading_troupe_is_allowed(tmp_path: Path) -> None:
    root = workspace(tmp_path, {".troupe/actors/x.yaml": b"runner: scripted\n"})
    step = call(Tools(root), "Read", {"file_path": ".troupe/actors/x.yaml"})
    assert not step.is_error
    assert "runner: scripted" in step.output


def test_the_write_tools_description_names_the_scratch_directory(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    scratch = _scratch(tmp_path)
    [write] = [d for d in Tools(root, scratch=scratch).offered() if d.name == "Write"]
    assert str(scratch) in write.description
    assert "Temporary files" in write.description
    [plain] = [d for d in Tools.definitions() if d.name == "Write"]
    assert "scratch" not in plain.description


@pytest.mark.parametrize("path", ["C:/Windows/win.ini", "C:\\Windows\\win.ini"])
def test_a_drive_path_outside_scratch_gets_the_same_answer_whatever_the_platform_calls_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    # On Windows a drive path is absolute. Only a path inside the scratch directory may take the
    # scratch route, so every other one gets the platform-independent answer, as on POSIX.
    monkeypatch.setattr(paths, "_is_absolute", lambda text: True)
    root = workspace(tmp_path)
    tools = Tools(root, READ_ONLY, scratch=_scratch(tmp_path))
    step = call(tools, "Read", {"file_path": path})
    assert step.is_error
    assert ("colon" in step.output) or ("backslash" in step.output)

"""Config's files in a real git theatre: a clean merge of two branches is left as it is, conflict
markers typed by hand are refused, a flush waits for another process writing config and says so,
and troupe's git attribute keeps a file's line endings under autocrlf (spec: config-files;
config-model design D7, D8, D9).

Its tests that stay in their own process are in unit/test_config_files.py."""

import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from config_files_shared import CONFIG, _actor_file, _theatre
from configtesting import TESTER
from gitrepo import make_repo
from troupe.core.config.projection import (
    flush,
    render,
)
from troupe.core.errors import TroupeError


def test_a_clean_git_merge_of_two_branches_files_is_left_as_it_is(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    theatre = repo.path
    flush(theatre, CONFIG, {})
    repo.commit_all("tester")
    repo.git("switch", "-q", "-c", "feature")
    runner_changed = {"actors": {"tester": {**TESTER, "expect": ["out/other.txt"]}}}
    flush(theatre, runner_changed, {})
    repo.commit_all("expect")
    repo.git("switch", "-q", "main")
    character_changed = {"actors": {"tester": {**TESTER, "character": "Changed on main."}}}
    flush(theatre, character_changed, {})
    repo.commit_all("character")
    repo.git("merge", "-q", "--no-edit", "feature")
    merged = {
        "actors": {
            "tester": {**TESTER, "expect": ["out/other.txt"], "character": "Changed on main."}
        }
    }
    assert flush(theatre, merged, {}).actions == ()


def test_conflict_markers_typed_by_hand_outside_any_merge_are_refused_and_left_alone(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    theatre = repo.path
    flush(theatre, CONFIG, {})
    repo.commit_all("tester")
    marked = b"<<<<<<< mine\nrunner: a\n=======\nrunner: b\n>>>>>>> theirs\n"
    _actor_file(theatre).write_bytes(marked)
    with pytest.raises(TroupeError) as caught:
        flush(theatre, CONFIG, {})
    assert caught.value.code == "config.file-not-troupes"
    assert "conflict markers" in caught.value.problem
    assert _actor_file(theatre).read_bytes() == marked


# Requirement: Config writes queue


def test_a_flush_waits_for_another_process_writing_config_and_says_it_is_waiting(
    tmp_path: Path,
) -> None:
    theatre = _theatre(tmp_path)
    holder = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        from troupe.core.config.projection import locked
        with locked(Path({str(theatre / ".troupe")!r})):
            print("held", flush=True)
            time.sleep(2.5)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "held"
        waits: list[float] = []
        started = time.monotonic()
        flush(theatre, CONFIG, {}, on_wait=lambda _path, waited: waits.append(waited))
        assert time.monotonic() - started > 1.0
        assert waits
    finally:
        child.wait(timeout=30)
    assert _actor_file(theatre).exists()


# Requirement: The theatre's git files hold what troupe needs ("Line endings on Windows")


def _checked_out_again(repo: Any, theatre: Path) -> bytes:  # noqa: ANN401
    repo.git("config", "core.autocrlf", "true")
    _actor_file(theatre).unlink()
    repo.git("checkout", "--", ".troupe/actors/tester.yaml")
    return _actor_file(theatre).read_bytes()


def test_a_config_file_checked_out_with_autocrlf_keeps_troupes_line_endings(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    theatre = repo.path
    flush(theatre, CONFIG, {})
    repo.commit_all("tester")
    written = render(CONFIG)["actors/tester.yaml"]
    assert _checked_out_again(repo, theatre) == written
    assert flush(theatre, CONFIG, {}).actions == ()


def test_without_troupes_attribute_autocrlf_would_change_the_file_and_it_would_be_refused(
    tmp_path: Path,
) -> None:
    # The control: shows the test above can fail, so its passing means the attribute works.
    repo = make_repo(tmp_path)
    theatre = repo.path
    flush(theatre, CONFIG, {})
    attributes = theatre / ".troupe" / ".gitattributes"
    attributes.write_text(attributes.read_text("utf-8").replace("actors/** -text", ""), "utf-8")
    repo.commit_all("tester, without the attribute")
    assert b"\r\n" in _checked_out_again(repo, theatre)
    with pytest.raises(TroupeError) as caught:
        flush(theatre, {"actors": {"tester": {**TESTER, "expect": []}}}, {})
    assert caught.value.code == "config.file-not-troupes"

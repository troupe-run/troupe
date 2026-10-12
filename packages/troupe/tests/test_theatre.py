"""Finding the theatre from where a command starts (spec: cli; perform-status-logs design D3)."""

from pathlib import Path

import pytest

from troupe.core.errors import TroupeError
from troupe.core.theatre import find_theatre


def test_the_start_directory_is_the_theatre_when_it_holds_dot_troupe(tmp_path: Path) -> None:
    (tmp_path / ".troupe").mkdir()
    assert find_theatre(tmp_path) == tmp_path


def test_from_a_subdirectory_the_nearest_ancestor_holding_dot_troupe_is_the_theatre(
    tmp_path: Path,
) -> None:
    (tmp_path / ".troupe").mkdir()
    deep = tmp_path / "src" / "pkg"
    deep.mkdir(parents=True)
    assert find_theatre(deep) == tmp_path


def test_the_nearest_theatre_wins_over_one_further_up(tmp_path: Path) -> None:
    (tmp_path / ".troupe").mkdir()
    inner = tmp_path / "inner"
    (inner / ".troupe").mkdir(parents=True)
    assert find_theatre(inner / ".troupe") == inner


def test_with_no_theatre_above_it_fails_naming_the_start_and_creates_nothing(
    tmp_path: Path,
) -> None:
    start = tmp_path / "nowhere"
    start.mkdir()
    with pytest.raises(TroupeError) as caught:
        find_theatre(start)
    assert caught.value.code == "theatre.not-found"
    assert caught.value.path == str(start)
    assert "mkdir .troupe" in caught.value.fix
    assert not (start / ".troupe").exists()
    assert sorted(tmp_path.iterdir()) == [start]


def test_a_dot_troupe_that_is_a_file_does_not_make_a_theatre(tmp_path: Path) -> None:
    start = tmp_path / "project"
    start.mkdir()
    (start / ".troupe").write_text("not a directory", encoding="utf-8")
    with pytest.raises(TroupeError) as caught:
        find_theatre(start)
    assert caught.value.code == "theatre.not-found"

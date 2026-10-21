"""Finding the theatre from where a command starts, and the theatre's own git files (spec: cli,
config-files; perform-status-logs design D3; config-model design D12)."""

from pathlib import Path

import pytest

from troupe.core.errors import TroupeError
from troupe.core.theatre import GIT_FILES, ensure_git_files, find_theatre


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


# Requirement: The theatre's git files hold what troupe needs


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_missing_git_files_are_written_with_every_pattern_and_why(tmp_path: Path) -> None:
    ensure_git_files(tmp_path / ".troupe")
    assert _lines(tmp_path / ".troupe" / ".gitignore") == [
        "# Added by troupe: troupe's local state: derived, per clone, never committed.",
        "local/",
        "# Added by troupe: config files troupe is part-way through writing.",
        ".*.troupe~",
    ]
    attributes = _lines(tmp_path / ".troupe" / ".gitattributes")
    assert attributes[1::2] == ["events/** -text", "actors/** -text"]
    assert all(line.startswith("# Added by troupe: ") for line in attributes[::2])


def test_a_persons_own_lines_stay_unchanged_and_in_place(tmp_path: Path) -> None:
    ignore = tmp_path / ".troupe" / ".gitignore"
    ignore.parent.mkdir()
    ignore.write_bytes(b"# mine\nlocal/\nscratch/\n")
    ensure_git_files(tmp_path / ".troupe")
    assert _lines(ignore) == [
        "# mine",
        "local/",
        "scratch/",
        "# Added by troupe: config files troupe is part-way through writing.",
        ".*.troupe~",
    ]


def test_a_file_missing_one_pattern_gains_only_that_one(tmp_path: Path) -> None:
    attributes = tmp_path / ".troupe" / ".gitattributes"
    attributes.parent.mkdir()
    attributes.write_bytes(b"events/** -text")  # no final newline
    ensure_git_files(tmp_path / ".troupe")
    assert attributes.read_bytes().split(b"\n")[:3] == [
        b"events/** -text",
        b"# Added by troupe: config files are byte-exact, so they match what troupe wrote.",
        b"actors/** -text",
    ]


def test_a_file_with_crlf_line_endings_is_appended_to_with_crlf(tmp_path: Path) -> None:
    ignore = tmp_path / ".troupe" / ".gitignore"
    ignore.parent.mkdir()
    ignore.write_bytes(b"local/\r\n")
    ensure_git_files(tmp_path / ".troupe")
    assert ignore.read_bytes() == (
        b"local/\r\n# Added by troupe: config files troupe is part-way through writing.\r\n"
        b".*.troupe~\r\n"
    )


def test_a_second_time_changes_nothing(tmp_path: Path) -> None:
    ensure_git_files(tmp_path / ".troupe")
    before = {name: (tmp_path / ".troupe" / name).read_bytes() for name, _ in GIT_FILES}
    ensure_git_files(tmp_path / ".troupe")
    assert {name: (tmp_path / ".troupe" / name).read_bytes() for name, _ in GIT_FILES} == before


def test_a_deleted_troupe_line_comes_back(tmp_path: Path) -> None:
    ignore = tmp_path / ".troupe" / ".gitignore"
    ignore.parent.mkdir()
    ignore.write_bytes(b"local/\n")
    ensure_git_files(tmp_path / ".troupe")
    ignore.write_bytes(b"local/\n")
    ensure_git_files(tmp_path / ".troupe")
    assert ".*.troupe~" in _lines(ignore)

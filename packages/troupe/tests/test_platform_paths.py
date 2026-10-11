"""Tests for friendly path display (spec: platform)."""

import os
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from troupe.platform.paths import friendly

PART = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=8).map(
    lambda part: "p" + part
)
PARTS = st.lists(PART, min_size=1, max_size=4)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home" / "someone"
    path.mkdir(parents=True)
    return path


# Requirement: Paths are shown in a friendly full form


def test_a_path_under_home_is_shown_as_tilde_separator_and_the_rest(home: Path) -> None:
    assert friendly(home / "Projects" / "theatre", home=home) == f"~{os.sep}Projects{os.sep}theatre"


def test_the_home_directory_itself_is_shown_as_tilde(home: Path) -> None:
    assert friendly(home, home=home) == "~"


def test_a_path_outside_home_is_shown_as_an_absolute_path(home: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "theatre"
    assert friendly(outside, home=home) == str(outside)


def test_the_current_directory_is_shown_in_full_not_as_dot(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    theatre = home / "theatre"
    theatre.mkdir()
    monkeypatch.chdir(theatre)
    assert friendly(".", home=home) == f"~{os.sep}theatre"
    assert friendly("notes.md", home=home) == f"~{os.sep}theatre{os.sep}notes.md"


def test_the_default_home_is_the_user_s_home_directory() -> None:
    assert friendly(Path.home() / "x") == f"~{os.sep}x"


def test_home_matching_follows_the_platform_s_case_sensitivity(home: Path) -> None:
    other_case = Path(str(home).upper()) / "theatre"
    shown = friendly(other_case, home=home)
    if sys.platform in ("win32", "darwin"):
        assert shown == f"~{os.sep}theatre"
    else:
        assert shown == str(other_case)


@given(parts=PARTS)
def test_paths_under_home_always_start_with_tilde_and_separator(parts: list[str]) -> None:
    home = Path.home()
    shown = friendly(home.joinpath(*parts), home=home)
    assert shown == "~" + os.sep + os.sep.join(parts)


@given(parts=PARTS)
def test_paths_outside_home_are_absolute_and_never_start_with_tilde(parts: list[str]) -> None:
    home = Path.home() / "nobody-home-here"
    outside = Path(Path.home().anchor).joinpath("elsewhere", *parts)
    shown = friendly(outside, home=home)
    assert not shown.startswith("~")
    assert Path(shown).is_absolute()


@given(parts=PARTS)
def test_relative_paths_are_never_shown_relative(parts: list[str]) -> None:
    shown = friendly(os.path.join(*parts))
    assert shown.startswith("~" + os.sep) or Path(shown).is_absolute()

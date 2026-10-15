"""The supported Python versions are one decision, checked in one place (spec: python-support).

Each property is broken in a copy of the real files, one at a time, to show the check catches it
and names the file. The last test runs the check on the real files."""

import re
import shutil
from pathlib import Path

import pytest
from conftest import REPO
from hypothesis import assume, given
from hypothesis import strategies as st

import python_versions
import release_config
from python_versions import CI, PIN, PYPROJECT, BoundError

BOUND = ">=3.12,<3.14"


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """The files the check reads, copied from the repository."""
    for name in (PYPROJECT, CI, PIN):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / name, tmp_path / name)
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / PYPROJECT, tmp_path / path / PYPROJECT)
    return tmp_path


def replace(root: Path, name: str, old: str, new: str) -> None:
    """Replace the one occurrence of old in a copied file, failing if there isn't exactly one."""
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{name} has {text.count(old)} copies of {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def set_bound(root: Path, name: str, bound: str) -> None:
    replace(root, name, f'requires-python = "{BOUND}"', f'requires-python = "{bound}"')


def set_matrix(root: Path, entries: str) -> None:
    replace(root, CI, 'python: ["3.12", "3.13"]', f"python: [{entries}]")


def test_the_copy_of_the_real_files_has_no_problems(copy: Path) -> None:
    assert python_versions.problems(copy) == []


def test_the_supported_versions_are_the_minors_the_root_bound_allows(copy: Path) -> None:
    assert python_versions.supported(copy) == ["3.12", "3.13"]


def test_a_member_with_a_different_bound_is_named_with_the_roots_bound(copy: Path) -> None:
    member = "plugins/runner-scripted/pyproject.toml"
    set_bound(copy, member, ">=3.12")
    assert python_versions.problems(copy) == [
        f'{member} has requires-python = ">=3.12", not the root\'s "{BOUND}": set it to "{BOUND}".'
    ]


def test_a_member_with_no_bound_is_named(copy: Path) -> None:
    member = "packages/troupe-vcs-git/pyproject.toml"
    replace(copy, member, f'requires-python = "{BOUND}"\n', "")
    assert python_versions.problems(copy) == [
        f'{member} has no requires-python, not the root\'s "{BOUND}": set it to "{BOUND}".'
    ]


@pytest.mark.parametrize("bound", [">=3.12", "~=3.12", ">=3.12,<3.14,!=3.13", ">=3.14,<3.12"])
def test_a_root_bound_not_of_the_form_is_named_and_nothing_else_is_checked(
    copy: Path, bound: str
) -> None:
    set_bound(copy, PYPROJECT, bound)
    assert python_versions.problems(copy) == [
        f'{PYPROJECT} has requires-python = "{bound}": it must be ">=3.X,<3.Y" with X below Y, '
        'for example ">=3.12,<3.14".'
    ]


def test_a_root_with_no_bound_is_named(copy: Path) -> None:
    replace(copy, PYPROJECT, f'requires-python = "{BOUND}"\n', "")
    assert python_versions.problems(copy) == [
        f'{PYPROJECT} has no requires-python: it must be ">=3.X,<3.Y" with X below Y, '
        'for example ">=3.12,<3.14".'
    ]


def test_a_version_missing_from_the_ci_matrix_is_named(copy: Path) -> None:
    set_matrix(copy, '"3.12"')
    assert python_versions.problems(copy) == [
        f'{CI} doesn\'t test 3.13, which requires-python "{BOUND}" in {PYPROJECT} supports: add '
        "it to the matrix, or narrow the bound."
    ]


def test_a_version_in_the_ci_matrix_outside_the_bound_is_named(copy: Path) -> None:
    set_matrix(copy, '"3.12", "3.13", "3.14"')
    assert python_versions.problems(copy) == [
        f'{CI} tests 3.14, which requires-python "{BOUND}" in {PYPROJECT} doesn\'t allow: widen '
        "the bound, or remove it from the matrix."
    ]


def test_a_ci_file_with_no_python_matrix_is_named(copy: Path) -> None:
    replace(copy, CI, 'python: ["3.12", "3.13"]', "pythons: []")
    assert python_versions.problems(copy) == [
        f"{CI} has 0 'python: [...]' lines: keep exactly one, in the check job's matrix, listing "
        'the supported versions as quoted strings, like python: ["3.12", "3.13"].'
    ]


def test_a_ci_file_with_two_python_matrices_is_named(copy: Path) -> None:
    replace(copy, CI, 'python: ["3.12", "3.13"]', 'python: ["3.12", "3.13"]\n        python: []')
    assert python_versions.problems(copy) == [
        f"{CI} has 2 'python: [...]' lines: keep exactly one, in the check job's matrix, listing "
        'the supported versions as quoted strings, like python: ["3.12", "3.13"].'
    ]


@pytest.mark.parametrize("entry", ["3.13", '"3.13.1"', '"pypy3.13"', '""'])
def test_a_ci_matrix_entry_that_isnt_a_quoted_minor_version_is_named(
    copy: Path, entry: str
) -> None:
    set_matrix(copy, f'"3.12", {entry}')
    assert python_versions.problems(copy) == [
        f"{CI} lists {entry} in its Python matrix: each entry must be a quoted minor version, "
        'like "3.13" (unquoted, YAML reads 3.10 as the number 3.1).'
    ]


def test_a_pin_above_the_lowest_supported_version_is_named(copy: Path) -> None:
    (copy / PIN).write_text("3.13\n", encoding="utf-8")
    assert python_versions.problems(copy) == [
        f"{PIN} says 3.13, not 3.12, the lowest supported version: set it to 3.12."
    ]


def test_a_missing_pin_is_named(copy: Path) -> None:
    (copy / PIN).unlink()
    assert python_versions.problems(copy) == [
        f"{PIN} is missing: create it holding 3.12, the lowest supported version."
    ]


def test_a_ruff_target_that_isnt_the_lowest_supported_version_is_named(copy: Path) -> None:
    replace(copy, PYPROJECT, 'target-version = "py312"', 'target-version = "py313"')
    assert python_versions.problems(copy) == [
        f'{PYPROJECT} has [tool.ruff] target-version = "py313", not "py312" for 3.12, the lowest '
        'supported version: set it to "py312".'
    ]


def test_a_mypy_version_that_isnt_the_lowest_supported_version_is_named(copy: Path) -> None:
    replace(copy, PYPROJECT, 'python_version = "3.12"', 'python_version = "3.13"')
    assert python_versions.problems(copy) == [
        f'{PYPROJECT} has [tool.mypy] python_version = "3.13", not "3.12", the lowest supported '
        'version: set it to "3.12".'
    ]


def test_widening_the_bound_and_the_matrix_together_has_no_problems(copy: Path) -> None:
    """The way the next version is added (issue #104, Part 2): both move, and nothing else."""
    for path in ["", *(f"{member}/" for member in release_config.members(copy))]:
        set_bound(copy, f"{path}{PYPROJECT}", ">=3.12,<3.16")
    set_matrix(copy, '"3.12", "3.13", "3.14", "3.15"')
    assert python_versions.problems(copy) == []
    assert python_versions.supported(copy) == ["3.12", "3.13", "3.14", "3.15"]


def test_the_real_repository_has_no_problems() -> None:
    assert python_versions.problems(REPO) == []


# The form a bound must take, written independently of the check's own pattern.
SPACE = st.text(alphabet=" ", max_size=2)
FORM = re.compile(r" *>= *3\.(0|[1-9][0-9]*) *, *< *3\.(0|[1-9][0-9]*) *")


@given(
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=1, max_value=20),
    st.lists(SPACE, min_size=6, max_size=6),
)
def test_any_bound_of_the_form_gives_exactly_the_minors_it_allows(
    low: int, width: int, spaces: list[str]
) -> None:
    a, b, c, d, e, f = spaces
    bound = f"{a}>={b}3.{low}{c},{d}<{e}3.{low + width}{f}"
    assert python_versions.parse_bound(bound) == [f"3.{m}" for m in range(low, low + width)]


@given(st.text(alphabet=" <>=,.0123456789~!3", max_size=20))
def test_any_other_bound_is_refused_naming_pyproject(bound: str) -> None:
    match = FORM.fullmatch(bound)
    assume(match is None or int(match[1]) >= int(match[2]))
    with pytest.raises(BoundError, match=re.escape(f'{PYPROJECT} has requires-python = "')):
        python_versions.parse_bound(bound)

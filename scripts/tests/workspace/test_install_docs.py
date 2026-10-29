"""Every install command the docs give is the one the install check runs (spec: installation;
install-with-uv design D3), and the README names the Python versions troupe supports. (The install
page's are checked by core's test_the_install_page_gives_the_python_versions_troupe_declares.)

Each property is broken in a copy of the real pages to show the check catches it and names the
page and line. The last tests run it on the real pages."""

import shutil
from pathlib import Path

import pytest
from conftest import REPO

import install_check
import python_versions

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

INSTALL_PAGES = ("README.md", "docs/opening-night/install.md")
"""The pages that say how to install troupe."""
PYTHON_PAGE = "README.md"
"""The install page checked here for the Python versions: core's tests check the user docs' one."""
OTHER_PAGES = ("packages/troupe-run/README.md",)
COMMAND = 'uv tool install "'
"""What marks a line as a copy of the install command: the command with its quoted URL."""


def pages(root: Path) -> list[str]:
    """Every page that may give the install command, relative to root."""
    found = {*INSTALL_PAGES, *OTHER_PAGES}
    found |= {path.relative_to(root).as_posix() for path in (root / "docs").rglob("*.md")}
    return sorted(found)


def expected() -> list[str]:
    return [
        install_check.command(install_check.REPOSITORY, ref)
        for ref in install_check.DOCUMENTED_REFS
    ]


def problems(root: Path) -> list[str]:
    found: list[str] = []
    allowed = expected()
    for page in pages(root):
        lines = (root / page).read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if COMMAND in line and line.strip() not in allowed:
                found.append(
                    f"{page}:{number} gives the install command as {line.strip()!r}: give it as "
                    f"{allowed[0]!r}, with `main` or `<commit>` as the ref "
                    "(scripts/install_check.py's TEMPLATE)."
                )
    versions = python_versions.supported(root)
    needs = f"Python {versions[0]} to {versions[-1]}"
    for page in INSTALL_PAGES:
        if COMMAND not in (root / page).read_text(encoding="utf-8"):
            found.append(f"{page} doesn't give the install command: give {allowed[0]!r}.")
    if needs not in (root / PYTHON_PAGE).read_text(encoding="utf-8"):
        found.append(
            f"{PYTHON_PAGE} doesn't say troupe needs {needs}, the versions the root "
            "pyproject.toml's requires-python allows: say it in those words."
        )
    return found


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """The pages, and the root pyproject.toml the Python bound is read from."""
    shutil.copy(REPO / "pyproject.toml", tmp_path / "pyproject.toml")
    for page in pages(REPO):
        (tmp_path / page).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / page, tmp_path / page)
    return tmp_path


def line_of(root: Path, page: str, text: str) -> int:
    lines = (root / page).read_text(encoding="utf-8").splitlines()
    return next(number for number, line in enumerate(lines, start=1) if text in line)


def test_the_copy_of_the_real_pages_has_no_problems(copy: Path) -> None:
    assert problems(copy) == []


def test_a_command_that_names_another_subdirectory_is_named_with_its_page_and_line(
    copy: Path,
) -> None:
    page = "README.md"
    text = (copy / page).read_text(encoding="utf-8")
    good = install_check.command(install_check.REPOSITORY, "main")
    bad = good.replace("packages/troupe-run", "packages/troupe")
    assert good in text, f"{page} no longer gives {good!r}: update the case"
    (copy / page).write_text(text.replace(good, bad, 1), encoding="utf-8")
    assert problems(copy) == [
        f"{page}:{line_of(copy, page, bad)} gives the install command as {bad!r}: give it as "
        f"{good!r}, with `main` or `<commit>` as the ref (scripts/install_check.py's TEMPLATE)."
    ]


def test_a_command_on_any_docs_page_is_checked(copy: Path) -> None:
    page = "docs/the-company/the-house.md"
    bad = 'uv tool install "git+https://github.com/troupe-run/troupe@v1#subdirectory=packages/troupe-run"'
    with (copy / page).open("a", encoding="utf-8") as file:
        file.write(f"\n{bad}\n")
    [problem] = problems(copy)
    assert problem.startswith(f"{page}:{line_of(copy, page, bad)} gives the install command as")


def test_a_readme_without_the_python_versions_is_named(copy: Path) -> None:
    page = PYTHON_PAGE
    versions = python_versions.supported(REPO)
    needs = f"Python {versions[0]} to {versions[-1]}"
    text = (copy / page).read_text(encoding="utf-8")
    assert needs in text, f"{page} no longer says {needs!r}: update the case"
    (copy / page).write_text(text.replace(needs, "a recent Python"), encoding="utf-8")
    assert problems(copy) == [
        f"{page} doesn't say troupe needs {needs}, the versions the root "
        "pyproject.toml's requires-python allows: say it in those words."
    ]


def test_every_install_command_in_the_docs_is_the_one_the_install_check_runs() -> None:
    assert problems(REPO) == []

"""Every install command the docs give is the one the install check runs (spec: installation;
install-with-uv design D3), and the README names the Python versions troupe supports. (The install
page's are checked by core's test_the_install_page_gives_the_python_versions_troupe_declares.)

A command may name the bundle's release tag only at the version the release manifest gives it, and
only between release-please's markers in the pages each release updates, so every release moves it
(install-from-tag design D2, D3). The README's and the install page's `main` command sits between
the markers too, so switching it to the tag is a one-line edit (#208).

Each property is broken in a copy of the real pages to show the check catches it and names the
page and line. The last tests run it on the real pages."""

import json
import shutil
from pathlib import Path

import pytest
from conftest import REPO

import install_check
import python_versions
import release_config

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

INSTALL_PAGES = release_config.TAGGED_PAGES
"""The pages that say how to install troupe: each release moves the tag their command names."""
PYTHON_PAGE = "README.md"
"""The install page checked here for the Python versions: core's tests check the user docs' one."""
OTHER_PAGES = ("packages/troupe-run/README.md",)
COMMAND = 'uv tool install "'
"""What marks a line as a copy of the install command: the command with its quoted URL."""
START = "<!-- x-release-please-start-version -->"
END = "<!-- x-release-please-end -->"
"""release-please's markers: its generic updater rewrites the versions between them."""
NO_RELEASE = "0.0.0"
"""The manifest's version for a package that hasn't been released."""
_BEFORE, _AFTER = install_check.command(install_check.REPOSITORY, "{ref}").split("{ref}")


def pages(root: Path) -> list[str]:
    """Every page that may give the install command, relative to root."""
    found = {*INSTALL_PAGES, *OTHER_PAGES}
    found |= {path.relative_to(root).as_posix() for path in (root / "docs").rglob("*.md")}
    return sorted(found)


def expected(root: Path) -> list[str]:
    """The commands the docs may give: main, a commit, and the bundle's tag once it's released."""
    refs = list(install_check.DOCUMENTED_REFS)
    version = release_config.bundle_version(root)
    if version != NO_RELEASE:
        refs.append(install_check.TAG_PREFIX + version)
    return [install_check.command(install_check.REPOSITORY, ref) for ref in refs]


def ref_of(command: str) -> str | None:
    """The ref a copy of the command names, when it's otherwise the documented form."""
    if command.startswith(_BEFORE) and command.endswith(_AFTER):
        return command[len(_BEFORE) : len(command) - len(_AFTER)]
    return None


def marked(lines: list[str]) -> set[int]:
    """The line numbers between a start marker and its end."""
    inside, found = False, set()
    for number, line in enumerate(lines, start=1):
        if line.strip() == START:
            inside = True
        elif line.strip() == END:
            inside = False
        elif inside:
            found.add(number)
    return found


def _tag_problem(root: Path, page: str, number: int, ref: str) -> str | None:
    """What's wrong with a command naming a release tag on a page, or None."""
    version = release_config.bundle_version(root)
    where = f"{page}:{number} names {ref}, but"
    gives = f"{release_config.MANIFEST} gives {release_config.bundle_path(root)} {version}"
    if version == NO_RELEASE:
        return (
            f"{where} {gives}: there's no release to name yet. Give `main` or `<commit>` until "
            "the first release."
        )
    if ref != install_check.TAG_PREFIX + version:
        return f"{where} {gives}: name {install_check.TAG_PREFIX}{version}."
    if page not in INSTALL_PAGES:
        return (
            f"{where} only {' and '.join(INSTALL_PAGES)} are moved to each new release: give "
            "`main` or `<commit>` here."
        )
    return None


def problems(root: Path) -> list[str]:
    found: list[str] = []
    allowed = expected(root)
    for page in pages(root):
        lines = (root / page).read_text(encoding="utf-8").splitlines()
        between = marked(lines)
        for number, line in enumerate(lines, start=1):
            if COMMAND not in line:
                continue
            ref = ref_of(line.strip())
            if ref is not None and ref.startswith(install_check.TAG_PREFIX):
                problem = _tag_problem(root, page, number, ref)
                if problem is not None:
                    found.append(problem)
                    continue
            elif line.strip() not in allowed:
                found.append(
                    f"{page}:{number} gives the install command as {line.strip()!r}: give it as "
                    f"{allowed[0]!r}, with `main`, `<commit>` or the bundle's release tag as the "
                    "ref (scripts/install_check.py's TEMPLATE)."
                )
                continue
            moved = ref == "main" or (ref or "").startswith(install_check.TAG_PREFIX)
            if page in INSTALL_PAGES and moved and number not in between:
                found.append(
                    f"{page}:{number} gives the install command outside release-please's markers, "
                    f"so a release wouldn't move its tag: put its code block between {START} and "
                    f"{END}."
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
    """The pages, the root pyproject.toml the Python bound is read from, and the release files."""
    shutil.copy(REPO / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(REPO / release_config.MANIFEST, tmp_path / release_config.MANIFEST)
    shutil.copy(REPO / release_config.CONFIG, tmp_path / release_config.CONFIG)
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
        f"{good!r}, with `main`, `<commit>` or the bundle's release tag as the ref "
        "(scripts/install_check.py's TEMPLATE)."
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


MAIN = install_check.command(install_check.REPOSITORY, "main")


def released(root: Path, version: str) -> None:
    """Set the bundle's version in the copy's release manifest, as a release pull request does."""
    path = root / release_config.MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest[release_config.bundle_path(root)] = version
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def tagged(root: Path, page: str, version: str) -> str:
    """Switch the page's main command to the bundle's tag at version, as #208 does."""
    text = (root / page).read_text(encoding="utf-8")
    assert MAIN in text, f"{page} no longer gives {MAIN!r}: update the case"
    command = install_check.command(install_check.REPOSITORY, f"troupe-run-v{version}")
    (root / page).write_text(text.replace(MAIN, command), encoding="utf-8")
    return command


def test_a_command_that_names_cores_tag_is_named_with_its_page_and_line(copy: Path) -> None:
    page = "README.md"
    released(copy, "0.1.0")
    text = (copy / page).read_text(encoding="utf-8")
    bad = MAIN.replace("@main", "@troupe-v0.1.0")
    (copy / page).write_text(text.replace(MAIN, bad), encoding="utf-8")
    assert problems(copy) == [
        f"{page}:{line_of(copy, page, bad)} gives the install command as {bad!r}: give it as "
        f"{MAIN!r}, with `main`, `<commit>` or the bundle's release tag as the ref "
        "(scripts/install_check.py's TEMPLATE)."
    ]


def test_the_bundles_tag_before_any_release_is_named_with_the_manifests_version(
    copy: Path,
) -> None:
    page = "README.md"
    released(copy, "0.0.0")
    command = tagged(copy, page, "0.1.0")
    assert problems(copy) == [
        f"{page}:{line_of(copy, page, command)} names troupe-run-v0.1.0, but "
        ".release-please-manifest.json gives packages/troupe-run 0.0.0: there's no release to "
        "name yet. Give `main` or `<commit>` until the first release."
    ]


def test_the_bundles_tag_at_its_released_version_passes_on_both_install_pages(
    copy: Path,
) -> None:
    released(copy, "0.1.0")
    for page in INSTALL_PAGES:
        tagged(copy, page, "0.1.0")
    assert problems(copy) == []


def test_the_bundles_tag_at_another_version_is_named_with_the_tag_expected(copy: Path) -> None:
    page = "docs/opening-night/install.md"
    released(copy, "0.2.0")
    command = tagged(copy, page, "0.1.0")
    assert problems(copy) == [
        f"{page}:{line_of(copy, page, command)} names troupe-run-v0.1.0, but "
        ".release-please-manifest.json gives packages/troupe-run 0.2.0: name troupe-run-v0.2.0."
    ]


def test_the_bundles_tag_on_a_page_no_release_moves_is_named(copy: Path) -> None:
    page = "docs/the-company/the-house.md"
    released(copy, "0.1.0")
    command = install_check.command(install_check.REPOSITORY, "troupe-run-v0.1.0")
    with (copy / page).open("a", encoding="utf-8") as file:
        file.write(f"\n{START}\n{command}\n{END}\n")
    assert problems(copy) == [
        f"{page}:{line_of(copy, page, command)} names troupe-run-v0.1.0, but only README.md and "
        "docs/opening-night/install.md are moved to each new release: give `main` or `<commit>` "
        "here."
    ]


@pytest.mark.parametrize("ref", ["main", "troupe-run-v0.1.0"])
def test_a_command_after_the_end_marker_is_named_with_its_page_and_line(
    copy: Path, ref: str
) -> None:
    page = "docs/opening-night/install.md"
    released(copy, "0.1.0")
    command = install_check.command(install_check.REPOSITORY, ref)
    text = (copy / page).read_text(encoding="utf-8")
    assert f"{END}\n" in text, f"{page} no longer has {END}: update the case"
    text = text.replace(MAIN, "uv --version").replace(f"{END}\n", f"{END}\n\n{command}\n", 1)
    (copy / page).write_text(text, encoding="utf-8")
    assert problems(copy) == [
        f"{page}:{line_of(copy, page, command)} gives the install command outside "
        "release-please's markers, so a release wouldn't move its tag: put its code block "
        f"between {START} and {END}."
    ]


def test_the_commit_command_outside_the_markers_passes(copy: Path) -> None:
    page = "docs/opening-night/install.md"
    lines = (copy / page).read_text(encoding="utf-8").splitlines()
    commit = install_check.command(install_check.REPOSITORY, "<commit>")
    assert line_of(copy, page, commit) not in marked(lines)
    assert problems(copy) == []


def test_every_install_command_in_the_docs_is_the_one_the_install_check_runs() -> None:
    assert problems(REPO) == []

"""troupe-run installs troupe with everything it bundles (spec: installation; install-with-uv D6).

Each property is broken in a copy of the real files, one at a time, to show the check catches it
and names the package and the file. The last test runs the check on the real files."""

import shutil
import tomllib
from pathlib import Path

import pytest
from conftest import REPO

import bundle
import release_config
from bundle import BUNDLE_PYPROJECT, CORE_PYPROJECT


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """The root pyproject.toml and every member's, copied from the repository."""
    shutil.copy(REPO / "pyproject.toml", tmp_path / "pyproject.toml")
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / "pyproject.toml", tmp_path / path / "pyproject.toml")
    return tmp_path


def replace(root: Path, name: str, old: str, new: str) -> None:
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} isn't in {name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_the_copy_of_the_real_files_has_no_problems(copy: Path) -> None:
    assert bundle.problems(copy) == []


def test_a_new_package_the_bundle_leaves_out_is_named_with_the_bundles_pyproject(
    copy: Path,
) -> None:
    (copy / "packages/troupe-new").mkdir()
    (copy / "packages/troupe-new/pyproject.toml").write_text(
        '[project]\nname = "troupe-new"\nversion = "0.0.1.dev0"\n', encoding="utf-8"
    )
    assert bundle.problems(copy) == [
        "troupe-new (packages/troupe-new) isn't a dependency of troupe-run: add "
        f'"troupe-new" to the dependencies in {BUNDLE_PYPROJECT}, so an install brings it.'
    ]


def test_a_runner_plugin_the_bundle_leaves_out_is_named(copy: Path) -> None:
    replace(copy, BUNDLE_PYPROJECT, '    "troupe-runner-scripted",\n', "")
    assert bundle.problems(copy) == [
        "troupe-runner-scripted (plugins/runner-scripted) isn't a dependency of troupe-run: add "
        f'"troupe-runner-scripted" to the dependencies in {BUNDLE_PYPROJECT}, so an install '
        "brings it."
    ]


def test_a_bundle_dependency_that_isnt_a_workspace_member_is_named(copy: Path) -> None:
    replace(copy, BUNDLE_PYPROJECT, '    "troupe",\n', '    "troupe",\n    "troupe-vcs-svn",\n')
    assert bundle.problems(copy) == [
        "troupe-run depends on troupe-vcs-svn, which isn't a workspace member: remove it from "
        f"the dependencies in {BUNDLE_PYPROJECT}."
    ]


def test_a_core_dependency_on_an_adapter_is_named_with_core_and_the_bundle(copy: Path) -> None:
    replace(copy, CORE_PYPROJECT, "dependencies = [\n", 'dependencies = [\n    "troupe_vcs_git",\n')
    assert bundle.problems(copy) == [
        f"troupe depends on troupe-vcs-git in {CORE_PYPROJECT}, but core declares no dependency "
        f"on a workspace member: remove it there. troupe-run ({BUNDLE_PYPROJECT}) is what brings "
        "it into an install."
    ]


def test_a_bundle_command_that_runs_something_else_names_both_targets(copy: Path) -> None:
    replace(copy, BUNDLE_PYPROJECT, 'troupe = "troupe.cli:main"', 'troupe = "troupe_run:main"')
    assert bundle.problems(copy) == [
        "troupe-run's troupe command runs 'troupe_run:main', but troupe's runs "
        f"'troupe.cli:main': set [project.scripts] troupe = 'troupe.cli:main' in "
        f"{BUNDLE_PYPROJECT}."
    ]


def test_a_bundle_without_a_troupe_command_is_named(copy: Path) -> None:
    replace(copy, BUNDLE_PYPROJECT, 'troupe = "troupe.cli:main"\n', "")
    assert bundle.problems(copy) == [
        "troupe-run declares no troupe command, but troupe's runs 'troupe.cli:main': set "
        f"[project.scripts] troupe = 'troupe.cli:main' in {BUNDLE_PYPROJECT}."
    ]


def test_a_missing_bundle_is_named(copy: Path) -> None:
    (copy / BUNDLE_PYPROJECT).unlink()
    assert bundle.problems(copy) == [
        f"{BUNDLE_PYPROJECT} doesn't exist: the troupe-run package installs troupe with "
        "everything it bundles, so every workspace member needs it."
    ]


def test_the_bundle_names_its_dependencies_without_versions() -> None:
    # The root's workspace sources pin each one to the installed commit (design D1); a version
    # here would be a second, unchecked statement of what's installed.
    project = tomllib.loads((REPO / BUNDLE_PYPROJECT).read_text(encoding="utf-8"))["project"]
    assert all(release_config.requirement_name(r) == r for r in project["dependencies"])


def test_troupe_run_installs_troupe_with_every_workspace_member() -> None:
    assert bundle.problems(REPO) == []

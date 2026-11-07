"""troupe-run installs troupe with everything it bundles (spec: installation; install-with-uv D6).

Each property is broken in a copy of the real files, one at a time, to show the check catches it
and names the package and the file. The last test runs the check on the real files."""

import json
import shutil
import tomllib
from pathlib import Path

import bundle_state
import pytest
from conftest import REPO

import bundle
import release_config
from bundle import BUNDLE_PYPROJECT, CORE_PYPROJECT
from release_config import CONFIG, MANIFEST


@pytest.fixture(params=["unpinned", "pinned"])
def copy(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """The root pyproject.toml and every member's, with the release config and manifest, copied
    from the repository, and then the bundle as it is before its first pin, or after it, so no
    test can assume which the repository is in (#229)."""
    for name in ("pyproject.toml", CONFIG, MANIFEST):
        shutil.copy(REPO / name, tmp_path / name)
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / "pyproject.toml", tmp_path / path / "pyproject.toml")
    bundle_state.copy_runner_table(REPO, tmp_path)
    bundle_state.unpinned(tmp_path)
    if request.param == "pinned":
        bundle_state.pinned(tmp_path)
    return tmp_path


def replace(root: Path, name: str, old: str, new: str) -> None:
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} isn't in {name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_the_copy_has_no_problems(copy: Path) -> None:
    """The real files, with the bundle unpinned or pinned: both states are ones the check
    accepts."""
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
    bundle_state.set_dependency(copy, "troupe-runner-scripted", None)
    assert bundle.problems(copy) == [
        "troupe-runner-scripted (plugins/runner-scripted) isn't a dependency of troupe-run: add "
        f'"troupe-runner-scripted" to the dependencies in {BUNDLE_PYPROJECT}, so an install '
        "brings it."
    ]


def test_a_bundle_dependency_that_isnt_a_workspace_member_is_named(copy: Path) -> None:
    replace(
        copy, BUNDLE_PYPROJECT, "dependencies = [\n", 'dependencies = [\n    "troupe-vcs-svn",\n'
    )
    assert bundle.problems(copy) == [
        "troupe-run depends on troupe-vcs-svn, which isn't a workspace member: remove it from "
        f"the dependencies in {BUNDLE_PYPROJECT}."
    ]


def test_a_core_dependency_on_an_adapter_is_named_with_core_and_the_bundle(copy: Path) -> None:
    replace(copy, CORE_PYPROJECT, "dependencies = [\n", 'dependencies = [\n    "troupe_vcs_git",\n')
    assert bundle.problems(copy) == [
        f"troupe depends on troupe-vcs-git in {CORE_PYPROJECT}, but core declares no dependency "
        f"on a workspace member but troupe-plugin-sdk: remove it there. troupe-run "
        f"({BUNDLE_PYPROJECT}) is what brings it into an install."
    ]


def test_core_depending_on_the_plugin_sdk_bare_has_no_problems(copy: Path) -> None:
    core = tomllib.loads((copy / CORE_PYPROJECT).read_text(encoding="utf-8"))["project"]
    assert "troupe-plugin-sdk" in core["dependencies"]
    assert bundle.problems(copy) == []


def _release(root: Path, path: str, version: str) -> None:
    manifest = root / MANIFEST
    versions = json.loads(manifest.read_bytes())
    versions[path] = version
    manifest.write_bytes((json.dumps(versions, indent=2) + "\n").encode("utf-8"))


def test_a_pinned_core_with_the_released_sdk_bare_names_both_and_the_bundle(copy: Path) -> None:
    _release(copy, "packages/troupe-plugin-sdk", "0.1.0")
    bundle_state.set_dependency(
        copy, "troupe", release_config.pin("troupe", "0.1.0", "packages/troupe")
    )
    bundle_state.set_dependency(copy, "troupe-plugin-sdk", "troupe-plugin-sdk")
    # In the pinned state the runner plugins, which depend on the SDK too, are pinned and named.
    found = bundle.problems(copy)
    assert (
        "troupe-run pins troupe, which depends on troupe-plugin-sdk, but names troupe-plugin-sdk "
        f"bare in {BUNDLE_PYPROJECT}: pin it at its latest release too, so an install of the "
        "bundle's tag never looks it up on a package index."
    ) in found
    assert all("but names troupe-plugin-sdk bare" in problem for problem in found)


def test_a_pinned_core_with_the_unreleased_sdk_bare_has_no_problems(copy: Path) -> None:
    _release(copy, "packages/troupe-plugin-sdk", "0.0.0")
    bundle_state.set_dependency(
        copy, "troupe", release_config.pin("troupe", "0.1.0", "packages/troupe")
    )
    bundle_state.set_dependency(copy, "troupe-plugin-sdk", "troupe-plugin-sdk")
    assert bundle.problems(copy) == []


def test_a_pinned_core_with_the_released_sdk_pinned_has_no_problems(copy: Path) -> None:
    _release(copy, "packages/troupe-plugin-sdk", "0.1.0")
    sdk = release_config.pin("troupe-plugin-sdk", "0.1.0", "packages/troupe-plugin-sdk")
    bundle_state.set_dependency(
        copy, "troupe", release_config.pin("troupe", "0.1.0", "packages/troupe")
    )
    bundle_state.set_dependency(copy, "troupe-plugin-sdk", sdk)
    assert bundle.problems(copy) == []


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


def test_the_bundle_names_each_dependency_bare_or_pinned_at_a_tag() -> None:
    # A commit install takes each one from that commit (design D1), and a tag install from its pin
    # (release-each-package design D2, D3); a version range would be a third, unchecked statement
    # of what's installed. release_config.py names a malformed pin.
    project = tomllib.loads((REPO / BUNDLE_PYPROJECT).read_text(encoding="utf-8"))["project"]
    paths = {name: path for path, name in release_config.members(REPO).items()}
    for _, requirement in release_config.bundle_requirements(project):
        name = release_config.requirement_name(requirement)
        release_config.pinned_version(requirement, name, paths[name])


def test_a_pinned_dependency_counts_as_a_dependency(copy: Path) -> None:
    # troupe-vcs-git depends on troupe, which has released, so troupe is pinned too, and troupe on
    # the SDK, released and pinned here so the test holds whether or not the repository's SDK has
    # released (refuse-bare-bundle-member task 4.1).
    pinned = release_config.pin("troupe-vcs-git", "0.1.1", "packages/troupe-vcs-git")
    bundle_state.set_dependency(copy, "troupe-vcs-git", pinned)
    bundle_state.set_dependency(
        copy, "troupe", release_config.pin("troupe", "0.1.0", "packages/troupe")
    )
    _release(copy, "packages/troupe-plugin-sdk", "0.1.0")
    bundle_state.set_dependency(
        copy,
        "troupe-plugin-sdk",
        release_config.pin("troupe-plugin-sdk", "0.1.0", "packages/troupe-plugin-sdk"),
    )
    assert bundle.problems(copy) == []


def test_a_pinned_adapter_with_released_core_bare_is_named(copy: Path) -> None:
    # In the pinned state every adapter is pinned, so each is named; vcs-git is among them.
    pinned = release_config.pin("troupe-vcs-git", "0.1.1", "packages/troupe-vcs-git")
    bundle_state.set_dependency(copy, "troupe-vcs-git", pinned)
    bundle_state.set_dependency(copy, "troupe", "troupe")
    found = bundle.problems(copy)
    assert (
        "troupe-run pins troupe-vcs-git, which depends on troupe, but names troupe bare in "
        f"{BUNDLE_PYPROJECT}: pin it at its latest release too, so an install of the bundle's "
        "tag never looks it up on a package index."
    ) in found
    assert all("but names troupe bare" in problem for problem in found)


def test_troupe_run_installs_troupe_with_every_workspace_member() -> None:
    assert bundle.problems(REPO) == []


# Runners with client libraries are optional extras of troupe-run, named after their runner, and
# 'all' names every one (spec: installation; runner-extras design D2, D4, D5). No shipped runner has
# a library yet, so each case adds a fixture runner, lm-studio, as #291 will.

RUNNER_TABLE = bundle_state.RUNNER_TABLE
LM_STUDIO = "troupe-runner-lm-studio"
LM_STUDIO_PATH = "plugins/runner-lm-studio"


def test_the_bundle_has_an_all_extra_with_no_runner_in_it_yet(copy: Path) -> None:
    """Every shipped runner depends only on the SDK, so 'all' adds nothing to the base yet."""
    assert bundle_state.extras(copy) == {"all": []}
    assert bundle.problems(copy) == []


def test_a_bundle_without_an_all_extra_is_named(copy: Path) -> None:
    bundle_state.set_extras(copy, {})
    assert bundle.problems(copy) == [
        f"troupe-run has no 'all' extra: add all = [...] under [project.optional-dependencies] "
        f"in {BUNDLE_PYPROJECT}, naming every runner in an extra, so troupe-run[all] installs "
        "every runner."
    ]


def test_a_library_backed_runner_in_its_extra_and_in_all_has_no_problems(copy: Path) -> None:
    bundle_state.add_runner(copy, "lm-studio", extra="lm-studio")
    assert bundle_state.extras(copy) == {"lm-studio": [LM_STUDIO], "all": [LM_STUDIO]}
    assert bundle.problems(copy) == []


def test_a_library_backed_runner_in_the_base_dependencies_is_named_with_its_extra(
    copy: Path,
) -> None:
    bundle_state.add_runner(copy, "lm-studio", in_extra=True)
    assert bundle.problems(copy) == [
        f"{LM_STUDIO} ({LM_STUDIO_PATH}) depends on lmstudio, beyond troupe-plugin-sdk, so it's "
        f"an optional extra of troupe-run: move it from the dependencies in {BUNDLE_PYPROJECT} to "
        "its runner's extra, 'lm-studio', and to 'all'."
    ]


def test_a_library_backed_runner_in_no_extra_is_named_with_its_extra(copy: Path) -> None:
    bundle_state.add_runner(copy, "lm-studio", extra="lm-studio")
    bundle_state.set_extras(copy, {"all": []})
    assert bundle.problems(copy) == [
        f"{LM_STUDIO} ({LM_STUDIO_PATH}) depends on lmstudio, beyond troupe-plugin-sdk, so "
        f"troupe-run has it in an extra named after its runner: add it to the 'lm-studio' extra, "
        f"and to 'all', in {BUNDLE_PYPROJECT}."
    ]


def test_an_extra_named_after_the_library_names_the_extra_and_the_runner(copy: Path) -> None:
    bundle_state.add_runner(copy, "lm-studio", extra="lmstudio")
    assert bundle.problems(copy) == [
        f"troupe-run's extra 'lmstudio' isn't named after a runner core knows ({RUNNER_TABLE}): "
        "troupe-run's extras are its runners', each named exactly as core's runner table names "
        f"it, and 'all'. It holds {LM_STUDIO}, whose runner is 'lm-studio': rename the extra to "
        f"'lm-studio' in {BUNDLE_PYPROJECT}."
    ]


def test_an_extra_that_isnt_a_runners_is_named(copy: Path) -> None:
    bundle_state.set_extras(copy, {"dev": [], "all": []})
    assert bundle.problems(copy) == [
        f"troupe-run's extra 'dev' isn't named after a runner core knows ({RUNNER_TABLE}): "
        "troupe-run's extras are its runners', each named exactly as core's runner table names "
        f"it, and 'all'. Remove it from {BUNDLE_PYPROJECT}."
    ]


def test_an_sdk_only_runner_given_an_extra_is_named_with_the_base_dependencies(copy: Path) -> None:
    held = next(
        r
        for _, r in bundle_state.dependency_lines(
            bundle_state.bundle_pyproject(copy).read_text(encoding="utf-8")
        )
        if release_config.requirement_name(r) == "troupe-runner-scripted"
    )
    bundle_state.set_dependency(copy, "troupe-runner-scripted", None)
    bundle_state.set_extras(copy, {"scripted": [held], "all": [held]})
    assert bundle.problems(copy) == [
        "troupe-run has troupe-runner-scripted in its 'scripted' extra, but "
        "plugins/runner-scripted depends only on troupe-plugin-sdk, so it's in the base install: "
        f"move it to the dependencies in {BUNDLE_PYPROJECT}, and remove the extra."
    ]


def test_a_runner_left_out_of_all_is_named(copy: Path) -> None:
    bundle_state.add_runner(copy, "lm-studio", extra="lm-studio")
    bundle_state.set_extras(copy, {"lm-studio": [LM_STUDIO], "all": []})
    assert bundle.problems(copy) == [
        f"troupe-run's 'all' extra doesn't name {LM_STUDIO}, which its 'lm-studio' extra holds: "
        f"add {LM_STUDIO!r} to 'all' in {BUNDLE_PYPROJECT}."
    ]


def test_all_naming_a_runner_no_extra_holds_is_named(copy: Path) -> None:
    held = next(
        r
        for _, r in bundle_state.dependency_lines(
            bundle_state.bundle_pyproject(copy).read_text(encoding="utf-8")
        )
        if release_config.requirement_name(r) == "troupe-runner-scripted"
    )
    bundle_state.set_extras(copy, {"all": [held]})
    assert bundle.problems(copy) == [
        "troupe-run's 'all' extra names troupe-runner-scripted, which no runner's extra holds: "
        f"remove it from 'all' in {BUNDLE_PYPROJECT}."
    ]


def test_all_pinning_another_version_names_both_references(copy: Path) -> None:
    bundle_state.add_runner(copy, "lm-studio", extra="lm-studio")
    new = release_config.pin(LM_STUDIO, "0.1.1", LM_STUDIO_PATH)
    old = release_config.pin(LM_STUDIO, "0.1.0", LM_STUDIO_PATH)
    bundle_state.set_extras(copy, {"lm-studio": [new], "all": [old]})
    assert bundle.problems(copy) == [
        f"troupe-run's 'all' extra names {old!r}, but its 'lm-studio' extra names {new!r}: make "
        f"them the same in {BUNDLE_PYPROJECT}."
    ]


def test_a_table_saying_base_for_a_runner_in_an_extra_is_named(copy: Path) -> None:
    bundle_state.add_runner(copy, "lm-studio", extra="lm-studio", in_extra=False)
    assert bundle.problems(copy) == [
        f"core's runner table ({RUNNER_TABLE}) says the 'lm-studio' runner is in the base "
        f"install, but {LM_STUDIO} depends on more than troupe-plugin-sdk, so troupe-run has it in "
        "an extra: set in_extra=True on its entry."
    ]


def test_a_table_saying_extra_for_a_base_runner_is_named(copy: Path) -> None:
    bundle_state.add_runner(copy, "plain", library=None, in_extra=True)
    assert bundle.problems(copy) == [
        f"core's runner table ({RUNNER_TABLE}) says the 'plain' runner is in an extra, but "
        "troupe-runner-plain depends only on troupe-plugin-sdk, so it's in the base install: set "
        "in_extra=False on its entry."
    ]


def test_a_library_backed_plugin_core_has_no_runner_for_is_named(copy: Path) -> None:
    bundle_state.add_runner(copy, "lm-studio", extra="lm-studio")
    table = copy / RUNNER_TABLE
    text = table.read_text(encoding="utf-8")
    start = text.index('    "lm-studio": Runner(')
    end = text.index("    ),\n", start) + len("    ),\n")
    table.write_text(text[:start] + text[end:], encoding="utf-8")
    assert (
        f"{LM_STUDIO} ({LM_STUDIO_PATH}) depends on lmstudio, beyond troupe-plugin-sdk, but "
        f"core's runner table ({RUNNER_TABLE}) has no runner whose package is "
        "troupe_runner_lm_studio: add its entry there, so its extra can be named after it."
    ) in bundle.problems(copy)


def test_a_missing_runner_table_is_named(copy: Path) -> None:
    (copy / RUNNER_TABLE).unlink()
    assert bundle.problems(copy) == [
        f"{RUNNER_TABLE} doesn't exist, or has no RUNNERS table: the bundle check reads each "
        "runner's name, and whether it's in an extra, from it."
    ]


def test_a_pinned_extra_runner_with_the_released_sdk_bare_names_both(copy: Path) -> None:
    """releases: "An extra's runner pins the released SDK bare"."""
    bundle_state.add_runner(copy, "lm-studio", extra="lm-studio")
    _release(copy, LM_STUDIO_PATH, "0.1.0")
    _release(copy, "packages/troupe-plugin-sdk", "0.1.0")
    pinned = release_config.pin(LM_STUDIO, "0.1.0", LM_STUDIO_PATH)
    bundle_state.set_extras(copy, {"lm-studio": [pinned], "all": [pinned]})
    bundle_state.set_dependency(copy, "troupe-plugin-sdk", "troupe-plugin-sdk")
    assert (
        f"troupe-run pins {LM_STUDIO}, which depends on troupe-plugin-sdk, but names "
        f"troupe-plugin-sdk bare in {BUNDLE_PYPROJECT}: pin it at its latest release too, so an "
        "install of the bundle's tag never looks it up on a package index."
    ) in bundle.problems(copy)

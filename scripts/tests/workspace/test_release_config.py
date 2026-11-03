"""Every workspace member is configured for release (spec: releases; release-automation D10).

Each property is broken in a copy of the real files, one at a time, to show the check catches it
and names the member and the file. The last test runs the check on the real files."""

import json
import shutil
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import bundle_state
import pytest
from conftest import REPO

import bundle as bundle_check
import release_config
from release_config import CONFIG, LOCK, MANIFEST, PROTOCOL, PROTOCOL_RECORD


def next_minor(version: str) -> str:
    """The version a pre-1.0 feature release moves to (spec: releases, "Pre-1.0 versioning")."""
    major, minor, _ = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


def release(root: Path) -> None:
    """Leave root as a release pull request releasing every member and the protocol would: each
    manifest version bumped, and the recorded protocol version set to the protocol's new one. The
    bundle releases only while its commits aren't excluded, which is while it names nothing bare
    (refuse-bare-bundle-member design D2), and a release pull request leaves the exclusion as it
    was."""
    config = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    held = {path for path, entry in config["packages"].items() if "exclude-paths" in entry}
    edit_json(
        root,
        MANIFEST,
        lambda m: m.update({path: next_minor(v) for path, v in m.items() if path not in held}),
    )
    (root / PROTOCOL_RECORD).write_text(
        json.dumps({"version": released(root)}) + "\n", encoding="utf-8"
    )


@pytest.fixture(params=["unpinned", "pinned"])
def bundle(request: pytest.FixtureRequest) -> str:
    """The bundle's state in the copy: before its first pin, or after it (#229)."""
    state: str = request.param
    return state


@pytest.fixture(params=["as-is", "released"])
def copy(tmp_path: Path, request: pytest.FixtureRequest, bundle: str) -> Path:
    """The files the check reads, copied from the repository, with the bundle as it is before its
    first pin or after it, and then, for "released", as a release pull request leaves them, so no
    test can assume the versions on main (#188) or the bundle's pins (#229)."""
    for name in ("pyproject.toml", CONFIG, MANIFEST, LOCK):
        shutil.copy(REPO / name, tmp_path / name)
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / "pyproject.toml", tmp_path / path / "pyproject.toml")
    (tmp_path / PROTOCOL_RECORD).parent.mkdir(parents=True)
    shutil.copy(REPO / PROTOCOL_RECORD, tmp_path / PROTOCOL_RECORD)
    bundle_state.unpinned(tmp_path)
    if bundle == "pinned":
        bundle_state.pinned(tmp_path)
    if request.param == "released":
        release(tmp_path)
    return tmp_path


def edit_json(root: Path, name: str, change: Callable[[dict[str, Any]], None]) -> None:
    path = root / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def released(root: Path) -> str:
    """The protocol's version in root's manifest: the one the check's messages name."""
    version: str = json.loads((root / MANIFEST).read_text(encoding="utf-8"))[PROTOCOL]
    return version


def test_the_copy_has_no_problems(copy: Path) -> None:
    """The real files, with the bundle unpinned or pinned, as-is or released: every state is one
    the check accepts."""
    assert release_config.problems(copy) == []


def test_a_member_missing_from_the_config_is_named_with_the_config_file(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"].pop("packages/troupe-vcs-git"))
    assert release_config.problems(copy) == [
        f"packages/troupe-vcs-git (troupe-vcs-git) has no entry in {CONFIG}: add one under "
        "'packages'."
    ]


def test_a_new_package_without_release_config_is_named(copy: Path) -> None:
    (copy / "packages/troupe-new").mkdir()
    (copy / "packages/troupe-new/pyproject.toml").write_text(
        '[project]\nname = "troupe-new"\nversion = "0.0.1.dev0"\n', encoding="utf-8"
    )
    assert release_config.problems(copy) == [
        f"packages/troupe-new (troupe-new) has no entry in {CONFIG}: add one under 'packages'.",
        f'packages/troupe-new (troupe-new) has no version in {MANIFEST}: add "packages/troupe-new" '
        "at the version it last released, its latest troupe-new-v<version> tag (`git ls-remote "
        "--tags --sort=-v:refname origin 'troupe-new-v*'`), or at \"0.0.0\" if it has none.",
    ]


def test_a_member_missing_from_the_manifest_is_named_with_the_file_and_its_tags(copy: Path) -> None:
    # A member missing from the manifest is a new one, and a new one is bare until it releases.
    bundle_state.set_dependency(copy, "troupe-runner-scripted", "troupe-runner-scripted")
    bundle_state.exclude(copy)
    edit_json(copy, MANIFEST, lambda m: m.pop("plugins/runner-scripted"))
    assert release_config.problems(copy) == [
        f"plugins/runner-scripted (troupe-runner-scripted) has no version in {MANIFEST}: add "
        '"plugins/runner-scripted" at the version it last released, its latest '
        "troupe-runner-scripted-v<version> tag (`git ls-remote --tags --sort=-v:refname origin "
        "'troupe-runner-scripted-v*'`), or at \"0.0.0\" if it has none."
    ]


def test_a_config_entry_for_a_path_that_isnt_a_member_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"].update({"packages/gone": {}}))
    assert release_config.problems(copy) == [
        f"{CONFIG} has an entry for packages/gone, which isn't a workspace member: remove it."
    ]


def test_a_manifest_version_for_a_path_that_isnt_a_member_is_named(copy: Path) -> None:
    edit_json(copy, MANIFEST, lambda m: m.update({"packages/gone": "0.0.0"}))
    assert release_config.problems(copy) == [
        f"{MANIFEST} has a version for packages/gone, which isn't a workspace member: remove it."
    ]


@pytest.mark.parametrize("key", ["package-name", "component"])
def test_a_package_name_or_component_that_isnt_the_project_name_is_named(
    copy: Path, key: str
) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"]["packages/troupe"].update({key: "core"}))
    assert release_config.problems(copy) == [
        f"packages/troupe's '{key}' in {CONFIG} is 'core': set it to its project name 'troupe'."
    ]


def test_a_member_that_isnt_released_as_python_is_named(copy: Path) -> None:
    edit_json(
        copy, CONFIG, lambda c: c["packages"]["packages/troupe"].update({"release-type": "simple"})
    )
    assert release_config.problems(copy) == [
        f"packages/troupe's 'release-type' in {CONFIG} is 'simple': set it to 'python'."
    ]


def test_a_lock_update_with_another_packages_jsonpath_is_named(copy: Path) -> None:
    wrong = {"type": "toml", "path": "/uv.lock", "jsonpath": release_config.lock_jsonpath("troupe")}
    edit_json(
        copy,
        CONFIG,
        lambda c: c["packages"]["packages/troupe-vcs-files"].update({"extra-files": [wrong]}),
    )
    [problem] = release_config.problems(copy)
    assert problem.startswith(
        f"packages/troupe-vcs-files (troupe-vcs-files) doesn't update its version in {LOCK}"
    )
    assert release_config.lock_jsonpath("troupe-vcs-files") in problem


def test_a_member_missing_from_the_lock_is_named_with_the_fix(copy: Path) -> None:
    lock = copy / LOCK
    text = lock.read_text(encoding="utf-8")
    assert text.count('name = "troupe-vcs-files"\n') == 1
    lock.write_text(
        text.replace('name = "troupe-vcs-files"\n', 'name = "renamed"\n'), encoding="utf-8"
    )
    assert release_config.problems(copy) == [
        f"{LOCK} has 0 packages named 'troupe-vcs-files', so packages/troupe-vcs-files's "
        "'extra-files' JSONPath doesn't match exactly one: run `uv lock`."
    ]


def bundle_member(root: Path) -> str:
    """The bundle's directory among root's workspace members."""
    [path] = [path for path, name in release_config.members(root).items() if name == "troupe-run"]
    return path


def version_of(root: Path, path: str) -> str:
    version: str = json.loads((root / MANIFEST).read_text(encoding="utf-8"))[path]
    return version


def path_of(root: Path, name: str) -> str:
    [path] = [path for path, member in release_config.members(root).items() if member == name]
    return path


def pin(root: Path, name: str, requirement: str) -> str:
    """Name `requirement` in place of the bundle's dependency on name. Returns the file's path."""
    relative = f"{bundle_member(root)}/pyproject.toml"
    pyproject = root / relative
    text = pyproject.read_text(encoding="utf-8")
    [line] = [line for line in text.splitlines() if line.strip().startswith(f'"{name}')]
    pyproject.write_text(text.replace(line, f'    "{requirement}",'), encoding="utf-8")
    return relative


def pinned(root: Path, name: str, version: str) -> str:
    """The pin the check expects for name at version (design D2)."""
    return (
        f"{name} @ git+{release_config.REPOSITORY}@{name}-v{version}"
        f"#subdirectory={path_of(root, name)}"
    )


def set_version(root: Path, path: str, version: str) -> None:
    edit_json(root, MANIFEST, lambda m: m.update({path: version}))


@pytest.mark.parametrize("group_name", ["troupe", "adapters"])
def test_a_linked_group_is_named(copy: Path, group_name: str) -> None:
    plugin = {"type": "linked-versions", "groupName": group_name, "components": ["troupe"]}
    edit_json(copy, CONFIG, lambda c: c.update({"plugins": [plugin]}))
    assert release_config.problems(copy) == [
        f"{CONFIG} links the components in {group_name!r} ('linked-versions'): remove the "
        "plugin, since every package versions on its own (#218)."
    ]


def test_a_pin_at_the_released_version_passes(copy: Path) -> None:
    path = path_of(copy, "troupe-vcs-git")
    set_version(copy, path, "0.1.1")
    pin(copy, "troupe-vcs-git", pinned(copy, "troupe-vcs-git", "0.1.1"))
    assert release_config.problems(copy) == []


def test_a_pin_behind_the_released_version_passes(copy: Path) -> None:
    """Moving it is the pinning pull request's job, after the release (design D8)."""
    path = path_of(copy, "troupe-vcs-git")
    set_version(copy, path, "0.2.0")
    pin(copy, "troupe-vcs-git", pinned(copy, "troupe-vcs-git", "0.1.1"))
    assert release_config.problems(copy) == []


MALFORMED = {
    "another-repository": "troupe-vcs-git @ git+https://github.com/someone/troupe"
    "@troupe-vcs-git-v0.1.1#subdirectory=packages/troupe-vcs-git",
    "another-subdirectory": "troupe-vcs-git @ git+https://github.com/troupe-run/troupe"
    "@troupe-vcs-git-v0.1.1#subdirectory=packages/troupe-vcs-files",
    "another-components-tag": "troupe-vcs-git @ git+https://github.com/troupe-run/troupe"
    "@troupe-vcs-files-v0.1.1#subdirectory=packages/troupe-vcs-git",
    "a-branch": "troupe-vcs-git @ git+https://github.com/troupe-run/troupe"
    "@main#subdirectory=packages/troupe-vcs-git",
    "no-subdirectory": "troupe-vcs-git @ git+https://github.com/troupe-run/troupe@troupe-vcs-git-v0.1.1",
    "a-marker": "troupe-vcs-git @ git+https://github.com/troupe-run/troupe"
    "@troupe-vcs-git-v0.1.1#subdirectory=packages/troupe-vcs-git ; os_name == 'nt'",
    "a-version-range": "troupe-vcs-git>=0.1",
}


@pytest.mark.parametrize("requirement", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_malformed_pin_is_named_with_the_expected_form(copy: Path, requirement: str) -> None:
    path = path_of(copy, "troupe-vcs-git")
    set_version(copy, path, "0.1.1")
    pyproject = pin(copy, "troupe-vcs-git", requirement)
    assert release_config.problems(copy) == [
        f"troupe-vcs-git's dependency in {pyproject} is {requirement!r}: pin it as "
        f'"{pinned(copy, "troupe-vcs-git", "0.1.1")}", or name it bare.'
    ]


def test_a_pin_ahead_of_the_release_names_both_versions(copy: Path) -> None:
    path = path_of(copy, "troupe-vcs-git")
    set_version(copy, path, "0.1.0")
    pyproject = pin(copy, "troupe-vcs-git", pinned(copy, "troupe-vcs-git", "0.2.0"))
    assert release_config.problems(copy) == [
        f"{pyproject} pins troupe-vcs-git at 0.2.0, but {MANIFEST} gives {path} 0.1.0: pin a "
        "version it has released, at most 0.1.0."
    ]


def test_a_pin_before_the_first_release_is_named(copy: Path) -> None:
    path = path_of(copy, "troupe-vcs-git")
    set_version(copy, path, "0.0.0")
    pyproject = pin(copy, "troupe-vcs-git", pinned(copy, "troupe-vcs-git", "0.0.0"))
    assert release_config.problems(copy) == [
        f"{pyproject} pins troupe-vcs-git at 0.0.0, but {MANIFEST} gives {path} 0.0.0: it hasn't "
        'released, so name it bare ("troupe-vcs-git") until the pinning pull request pins it.'
    ]


def exclude(root: Path, paths: list[str]) -> None:
    edit_json(
        root, CONFIG, lambda c: c["packages"][bundle_member(root)].update({"exclude-paths": paths})
    )


def unexcluded(root: Path) -> None:
    edit_json(root, CONFIG, lambda c: c["packages"][bundle_member(root)].pop("exclude-paths", None))


def bare(root: Path) -> list[str]:
    """The workspace members the bundle in root names bare, sorted: what the rule reads."""
    workspace = {release_config.normalise(n): n for n in release_config.members(root).values()}
    text = (root / bundle_member(root) / "pyproject.toml").read_text(encoding="utf-8")
    requirements = tomllib.loads(text)["project"]["dependencies"]
    return sorted(
        workspace[release_config.requirement_name(r)]
        for r in requirements
        if r.strip() in workspace.values()
    )


def missing(root: Path, names: list[str]) -> str:
    """The message for a bundle that names `names` bare without the exclusion."""
    path = bundle_member(root)
    them = "them" if len(names) > 1 else "it"
    each = "each" if len(names) > 1 else names[0]
    return (
        f"{path}/pyproject.toml names {release_config.listed(names)} bare, but {path}'s entry in "
        f'{CONFIG} doesn\'t exclude its commits: add "exclude-paths": ["{path}"] to it, so no '
        f"release pull request releases troupe-run until {each} has released and the pinning pull "
        f"request pins {them}. A tag install would otherwise look {them} up on a package index."
    )


@pytest.fixture
def everything_pinned(tmp_path: Path) -> Path:
    """The real files with every member released at 0.1.0 or later, the bundle pinning each and
    released at 0.1.0, and no exclusion, whatever state the repository is in (#229)."""
    for name in ("pyproject.toml", CONFIG, MANIFEST, LOCK):
        shutil.copy(REPO / name, tmp_path / name)
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / "pyproject.toml", tmp_path / path / "pyproject.toml")
    (tmp_path / PROTOCOL_RECORD).parent.mkdir(parents=True)
    shutil.copy(REPO / PROTOCOL_RECORD, tmp_path / PROTOCOL_RECORD)
    bundle_state.unpinned(tmp_path)
    edit_json(
        tmp_path,
        MANIFEST,
        lambda m: m.update({p: "0.1.0" for p, v in m.items() if v == "0.0.0" and p != PROTOCOL}),
    )
    bundle_state.pinned(tmp_path)
    assert bare(tmp_path) == []
    return tmp_path


def test_a_new_member_with_the_exclusion_has_no_problems(everything_pinned: Path) -> None:
    """bundle_state.add_member builds a state both checks accept (refuse-bare-bundle-member D5)."""
    bundle_state.add_member(everything_pinned, "troupe-example")
    bundle_state.exclude(everything_pinned)
    assert release_config.problems(everything_pinned) == []
    assert bundle_check.problems(everything_pinned) == []


def test_a_new_member_bare_after_the_bundles_first_release_without_the_exclusion_is_named(
    everything_pinned: Path,
) -> None:
    """#262: the bundle at 0.1.0, a member added after it, and nothing keeping the bundle out of
    release pull requests."""
    manifest = json.loads((everything_pinned / MANIFEST).read_text(encoding="utf-8"))
    assert manifest[bundle_member(everything_pinned)] == "0.1.0"
    bundle_state.add_member(everything_pinned, "troupe-example")
    assert release_config.problems(everything_pinned) == [
        missing(everything_pinned, ["troupe-example"])
    ]


def test_every_bare_member_is_named_in_one_problem(everything_pinned: Path) -> None:
    bundle_state.add_member(everything_pinned, "troupe-example")
    bundle_state.add_member(everything_pinned, "troupe-other")
    assert release_config.problems(everything_pinned) == [
        missing(everything_pinned, ["troupe-example", "troupe-other"])
    ]


def test_bare_members_without_the_exclusion_are_named_in_every_state(copy: Path) -> None:
    """Unpinned or pinned, as-is or released: with a member bare, the exclusion is needed."""
    names = bare(copy)
    if not names:
        bundle_state.set_dependency(copy, "troupe-vcs-git", "troupe-vcs-git")
        names = ["troupe-vcs-git"]
    unexcluded(copy)
    assert release_config.problems(copy) == [missing(copy, names)]


@pytest.mark.parametrize("version", ["0.0.0", "0.1.0"])
def test_an_exclusion_with_nothing_bare_is_named_whether_or_not_the_bundle_released(
    everything_pinned: Path, version: str
) -> None:
    path = bundle_member(everything_pinned)
    set_version(everything_pinned, path, version)
    exclude(everything_pinned, [path])
    assert release_config.problems(everything_pinned) == [
        f"{path}'s 'exclude-paths' in {CONFIG} is still set, but troupe-run names no workspace "
        "member bare: remove it, or troupe-run's commits never release."
    ]


@pytest.mark.parametrize("paths", [["packages"], ["packages/troupe-run/src"], []])
def test_an_exclusion_of_anything_else_while_a_member_is_bare_is_named(
    everything_pinned: Path, paths: list[str]
) -> None:
    path = bundle_member(everything_pinned)
    bundle_state.add_member(everything_pinned, "troupe-example")
    exclude(everything_pinned, paths)
    assert release_config.problems(everything_pinned) == [
        f"{path}'s 'exclude-paths' in {CONFIG} is {json.dumps(paths)}: make it "
        f'["{path}"], which keeps troupe-run out of release pull requests while it names '
        "troupe-example bare."
    ]


def test_a_malformed_pin_isnt_counted_as_bare(everything_pinned: Path) -> None:
    """Only the pin check's message appears: the member isn't bare, it's wrong."""
    requirement = MALFORMED["a-version-range"]
    pyproject = pin(everything_pinned, "troupe-vcs-git", requirement)
    [problem] = release_config.problems(everything_pinned)
    assert problem.startswith(f"troupe-vcs-git's dependency in {pyproject} is {requirement!r}")


def test_a_missing_protocol_entry_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"].pop("protocol"))
    assert release_config.problems(copy) == [
        f"protocol has no entry in {CONFIG}: add one with 'release-type': 'simple' and "
        "'component': 'protocol'."
    ]


def test_a_protocol_entry_released_as_python_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"]["protocol"].update({"release-type": "python"}))
    assert release_config.problems(copy) == [
        f"protocol's entry in {CONFIG} needs 'release-type': 'simple' and 'component': 'protocol'."
    ]


def test_a_config_without_prerelease_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: c.pop("prerelease", None))
    assert release_config.problems(copy) == [
        f"{CONFIG} doesn't set 'prerelease': set it to true at the top level, so releases before "
        "1.0 are pre-releases."
    ]


@pytest.mark.parametrize("value", [False, "true", 1], ids=["false", "string", "one"])
def test_a_prerelease_that_isnt_true_is_named_with_its_value(copy: Path, value: object) -> None:
    edit_json(copy, CONFIG, lambda c: c.update({"prerelease": value}))
    assert release_config.problems(copy) == [
        f"{CONFIG}'s 'prerelease' is {json.dumps(value)}: set it to true."
    ]


@pytest.mark.parametrize("path", ["packages/troupe", PROTOCOL])
@pytest.mark.parametrize("value", [True, False], ids=["true", "false"])
def test_an_entry_that_sets_prerelease_itself_is_named(copy: Path, path: str, value: bool) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"][path].update({"prerelease": value}))
    assert release_config.problems(copy) == [
        f"{path}'s entry in {CONFIG} sets 'prerelease': remove it, so it takes the top-level "
        "setting."
    ]


SECTIONS: list[dict[str, Any]] = [
    {"type": "feat", "section": "Features"},
    {"type": "fix", "section": "Bug Fixes"},
    {"type": "perf", "section": "Performance Improvements"},
    {"type": "revert", "section": "Reverts"},
    {"type": "docs", "section": "Documentation", "hidden": True},
    {"type": "deps", "section": "Dependencies", "hidden": True},
    {"type": "style", "section": "Styles", "hidden": True},
    {"type": "chore", "section": "Miscellaneous Chores", "hidden": True},
    {"type": "refactor", "section": "Code Refactoring", "hidden": True},
    {"type": "test", "section": "Tests", "hidden": True},
    {"type": "build", "section": "Build System", "hidden": True},
    {"type": "ci", "section": "Continuous Integration", "hidden": True},
]
"""The changelog sections, written out here rather than read from the check, so a change to the
check's copy fails a test (changelog-commit-paths design D3)."""

HISTORY = {
    "commit-batch-size": (
        100,
        "so a pull request's commits rarely fall on two pages of history (#223)",
    ),
    "commit-search-depth": (
        1000,
        "so every commit since the last release reaches the changelogs",
    ),
    "changelog-sections": (
        SECTIONS,
        "so only feat, fix, perf, revert and breaking changes are listed, and only they release",
    ),
}
"""Each history setting, the value it must have and why (changelog-commit-paths design D4)."""


@pytest.mark.parametrize("key", HISTORY)
def test_a_config_without_a_history_setting_is_named_with_its_value(copy: Path, key: str) -> None:
    edit_json(copy, CONFIG, lambda c: c.pop(key, None))
    value, why = HISTORY[key]
    assert release_config.problems(copy) == [
        f"{CONFIG} doesn't set '{key}': set it to {json.dumps(value)} at the top level, {why}."
    ]


def _shown(sections: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """sections with kind's section no longer hidden."""
    return [
        {k: v for k, v in s.items() if k != "hidden"} if s["type"] == kind else s for s in sections
    ]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("commit-batch-size", 10),
        ("commit-batch-size", "100"),
        ("commit-batch-size", 100.0),
        ("commit-search-depth", 500),
        ("commit-search-depth", "1000"),
        ("changelog-sections", _shown(SECTIONS, "docs")),
        ("changelog-sections", SECTIONS[1:]),
        ("changelog-sections", [SECTIONS[1], SECTIONS[0], *SECTIONS[2:]]),
        ("changelog-sections", []),
    ],
    ids=[
        "batch-10",
        "batch-string",
        "batch-float",
        "depth-500",
        "depth-string",
        "docs-shown",
        "feat-missing",
        "reordered",
        "empty",
    ],
)
def test_a_history_setting_with_another_value_is_named_with_both_values(
    copy: Path, key: str, value: object
) -> None:
    edit_json(copy, CONFIG, lambda c: c.update({key: value}))
    want, why = HISTORY[key]
    assert release_config.problems(copy) == [
        f"{CONFIG}'s '{key}' is {json.dumps(value)}: set it to {json.dumps(want)}, {why}."
    ]


@pytest.mark.parametrize("path", ["packages/troupe", PROTOCOL])
def test_an_entry_that_sets_its_own_changelog_sections_is_named(copy: Path, path: str) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"][path].update({"changelog-sections": SECTIONS}))
    assert release_config.problems(copy) == [
        f"{path}'s entry in {CONFIG} sets 'changelog-sections': remove it, so it takes the "
        "top-level setting."
    ]


RECORD_UPDATE = {"type": "json", "path": f"/{PROTOCOL_RECORD}", "jsonpath": "$.version"}
"""What keeps the recorded protocol version in step with a protocol release (design D2)."""


@pytest.mark.parametrize(
    "extra_files",
    [
        [],
        [{**RECORD_UPDATE, "jsonpath": "$.protocol"}],
        [RECORD_UPDATE, {"type": "toml", "path": "/uv.lock", "jsonpath": "$.version"}],
    ],
    ids=["none", "another-jsonpath", "an-extra-update"],
)
def test_a_protocol_entry_that_doesnt_update_the_record_exactly_is_named(
    copy: Path, extra_files: list[dict[str, str]]
) -> None:
    edit_json(
        copy, CONFIG, lambda c: c["packages"]["protocol"].update({"extra-files": extra_files})
    )
    assert release_config.problems(copy) == [
        f"protocol's entry in {CONFIG} doesn't write the protocol version troupe records: make "
        f"its 'extra-files' [{json.dumps(RECORD_UPDATE)}]."
    ]


def test_a_protocol_entry_with_no_extra_files_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"]["protocol"].pop("extra-files"))
    assert release_config.problems(copy) == [
        f"protocol's entry in {CONFIG} doesn't write the protocol version troupe records: make "
        f"its 'extra-files' [{json.dumps(RECORD_UPDATE)}]."
    ]


def test_a_missing_record_is_named_with_the_manifests_version(copy: Path) -> None:
    (copy / PROTOCOL_RECORD).unlink()
    assert release_config.problems(copy) == [
        f'{PROTOCOL_RECORD} is missing: add it, holding {{"version": "{released(copy)}"}}, the '
        f"protocol's version in {MANIFEST}."
    ]


@pytest.mark.parametrize(
    "content",
    [b"not json\n", b'["0.0.0"]\n', b'{"version": "0.0.0", "extra": 1}\n', b'{"version": 0}\n'],
    ids=["not-json", "not-an-object", "an-extra-key", "not-a-string"],
)
def test_a_record_that_doesnt_hold_only_a_version_is_named(copy: Path, content: bytes) -> None:
    (copy / PROTOCOL_RECORD).write_bytes(content)
    assert release_config.problems(copy) == [
        f'{PROTOCOL_RECORD} must hold only {{"version": "<version>"}}: set it to '
        f'{{"version": "{released(copy)}"}}, the protocol\'s version in {MANIFEST}.'
    ]


def test_a_record_that_differs_from_the_manifest_names_both_files_and_versions(
    copy: Path,
) -> None:
    manifest = released(copy)
    major = int(manifest.split(".")[0])
    different = f"{major + 1}.0.0"
    assert different != manifest
    (copy / PROTOCOL_RECORD).write_text(json.dumps({"version": different}), encoding="utf-8")
    assert release_config.problems(copy) == [
        f"{PROTOCOL_RECORD} records protocol {different}, but {MANIFEST} has {manifest}: a "
        f"protocol release pull request sets it. To correct it by hand, set it to {manifest}."
    ]


def test_the_protocol_missing_from_the_manifest_is_named_with_the_file_and_its_tags(
    copy: Path,
) -> None:
    edit_json(copy, MANIFEST, lambda m: m.pop("protocol"))
    assert release_config.problems(copy) == [
        f'protocol has no version in {MANIFEST}: add "protocol" at the version it last released, '
        "its latest protocol-v<version> tag (`git ls-remote --tags --sort=-v:refname origin "
        "'protocol-v*'`), or at \"0.0.0\" if it has none."
    ]


@pytest.mark.parametrize("page", release_config.TAGGED_PAGES)
def test_a_bundle_that_doesnt_move_an_install_pages_tag_is_named_with_the_update(
    copy: Path, page: str
) -> None:
    path = release_config.bundle_path(copy)
    update = release_config.page_update(page)

    def remove(config: dict[str, Any]) -> None:
        config["packages"][path]["extra-files"].remove(update)

    edit_json(copy, CONFIG, remove)
    assert release_config.problems(copy) == [
        f"{path} (troupe-run) doesn't move the tag {page}'s install command names: add "
        f"{json.dumps(update)} to its 'extra-files' in {CONFIG}."
    ]


def test_every_workspace_member_is_configured_for_release() -> None:
    assert release_config.problems(REPO) == []

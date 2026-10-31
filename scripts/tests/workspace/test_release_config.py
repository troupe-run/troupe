"""Every workspace member is configured for release (spec: releases; release-automation D10).

Each property is broken in a copy of the real files, one at a time, to show the check catches it
and names the member and the file. The last test runs the check on the real files."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO

import release_config
from release_config import CONFIG, LOCK, MANIFEST, PROTOCOL, PROTOCOL_RECORD


def next_minor(version: str) -> str:
    """The version a pre-1.0 feature release moves to (spec: releases, "Pre-1.0 versioning")."""
    major, minor, _ = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


def release(root: Path) -> None:
    """Leave root as a release pull request releasing every member and the protocol would: each
    manifest version bumped, and the recorded protocol version set to the protocol's new one."""
    edit_json(root, MANIFEST, lambda m: m.update({path: next_minor(v) for path, v in m.items()}))
    (root / PROTOCOL_RECORD).write_text(
        json.dumps({"version": released(root)}) + "\n", encoding="utf-8"
    )


@pytest.fixture(params=["as-is", "released"])
def copy(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """The files the check reads, copied from the repository, and then, for "released", as a
    release pull request leaves them, so no test can assume the versions on main (#188)."""
    for name in ("pyproject.toml", CONFIG, MANIFEST, LOCK):
        shutil.copy(REPO / name, tmp_path / name)
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / "pyproject.toml", tmp_path / path / "pyproject.toml")
    (tmp_path / PROTOCOL_RECORD).parent.mkdir(parents=True)
    shutil.copy(REPO / PROTOCOL_RECORD, tmp_path / PROTOCOL_RECORD)
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


def group(config: dict[str, Any]) -> list[str]:
    components: list[str] = config["plugins"][0]["components"]
    return components


def test_the_copy_of_the_real_files_has_no_problems(copy: Path) -> None:
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
    found = release_config.problems(copy)
    assert (
        f"packages/troupe-new (troupe-new) has no entry in {CONFIG}: add one under 'packages'."
        in found
    )
    assert (
        f'packages/troupe-new (troupe-new) has no version in {MANIFEST}: add "packages/troupe-new" '
        "at the version it last released, its latest troupe-new-v<version> tag (`git ls-remote "
        "--tags --sort=-v:refname origin 'troupe-new-v*'`), or at \"0.0.0\" if it has none."
    ) in found
    assert (
        f"troupe-new isn't in the 'troupe' linked group in {CONFIG}: add it to its 'components'."
        in found
    )


def test_a_member_missing_from_the_manifest_is_named_with_the_file_and_its_tags(copy: Path) -> None:
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


def test_a_package_left_out_of_the_linked_group_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: group(c).remove("troupe-store-text"))
    assert release_config.problems(copy) == [
        f"troupe-store-text isn't in the 'troupe' linked group in {CONFIG}: add it to its "
        "'components'."
    ]


RUNNERS = ("troupe-runner-claude-code", "troupe-runner-scripted")
"""The runner plugins the bundle ships, so they're in the linked group (#214)."""


def leave_out(name: str) -> Callable[[dict[str, Any]], None]:
    """Take name out of the linked group, whether or not it's there."""

    def change(config: dict[str, Any]) -> None:
        config["plugins"][0]["components"] = [c for c in group(config) if c != name]

    return change


def put_in(name: str) -> Callable[[dict[str, Any]], None]:
    """Put name in the linked group, whether or not it's there."""

    def change(config: dict[str, Any]) -> None:
        if name not in group(config):
            group(config).append(name)

    return change


def bundle_member(root: Path) -> str:
    """The bundle's directory among root's workspace members."""
    [path] = [path for path, name in release_config.members(root).items() if name == "troupe-run"]
    return path


def unbundle(root: Path, name: str) -> None:
    """Drop name from the bundle's dependencies, as moving it to its own repository would."""
    pyproject = root / bundle_member(root) / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert text.count(f'    "{name}",\n') == 1
    pyproject.write_text(text.replace(f'    "{name}",\n', ""), encoding="utf-8")


@pytest.mark.parametrize("runner", RUNNERS)
def test_a_bundled_runner_left_out_of_the_linked_group_is_named(copy: Path, runner: str) -> None:
    edit_json(copy, CONFIG, leave_out(runner))
    assert release_config.problems(copy) == [
        f"{runner} isn't in the 'troupe' linked group in {CONFIG}, but troupe-run ships it: add it "
        "to its 'components'."
    ]


def test_a_plugin_the_bundle_doesnt_ship_in_the_linked_group_is_named(copy: Path) -> None:
    unbundle(copy, "troupe-runner-scripted")
    edit_json(copy, CONFIG, put_in("troupe-runner-scripted"))
    assert release_config.problems(copy) == [
        f"troupe-runner-scripted is in the 'troupe' linked group in {CONFIG}, but troupe-run "
        "doesn't ship it: remove it."
    ]


def test_a_component_that_isnt_a_member_in_the_linked_group_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, put_in("troupe-gone"))
    assert release_config.problems(copy) == [
        f"troupe-gone is in the 'troupe' linked group in {CONFIG}, but it isn't a workspace "
        "member: remove it."
    ]


def test_without_the_bundle_the_group_is_checked_against_packages_alone(copy: Path) -> None:
    """bundle.py names the missing bundle; this check doesn't add a message per runner."""
    path = bundle_member(copy)
    (copy / path / "pyproject.toml").unlink()
    edit_json(copy, CONFIG, leave_out("troupe-store-text"))
    assert release_config.problems(copy) == [
        f"{CONFIG} has an entry for {path}, which isn't a workspace member: remove it.",
        f"{MANIFEST} has a version for {path}, which isn't a workspace member: remove it.",
        f"troupe-store-text isn't in the 'troupe' linked group in {CONFIG}: add it to its "
        "'components'.",
        f"troupe-run is in the 'troupe' linked group in {CONFIG}, but it isn't a workspace member: "
        "remove it.",
    ]


def test_the_protocol_in_the_linked_group_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: group(c).append("protocol"))
    assert release_config.problems(copy) == [
        f"protocol is in the 'troupe' linked group in {CONFIG}, but it's released on its own: "
        "remove it from 'components'."
    ]


def test_a_missing_linked_group_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: c.update({"plugins": []}))
    assert release_config.problems(copy) == [
        f"{CONFIG} has 0 'linked-versions' plugins named 'troupe': keep exactly one."
    ]


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

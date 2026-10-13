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
from release_config import CONFIG, LOCK, MANIFEST


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """The files the check reads, copied from the repository."""
    for name in ("pyproject.toml", CONFIG, MANIFEST, LOCK):
        shutil.copy(REPO / name, tmp_path / name)
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / "pyproject.toml", tmp_path / path / "pyproject.toml")
    return tmp_path


def edit_json(root: Path, name: str, change: Callable[[dict[str, Any]], None]) -> None:
    path = root / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


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
        f"packages/troupe-new (troupe-new) has no version in {MANIFEST}: "
        'add "packages/troupe-new": "0.0.0".'
    ) in found
    assert (
        f"troupe-new isn't in the 'troupe' linked group in {CONFIG}: add it to its 'components'."
        in found
    )


def test_a_member_missing_from_the_manifest_is_named_with_the_manifest_file(copy: Path) -> None:
    edit_json(copy, MANIFEST, lambda m: m.pop("plugins/runner-scripted"))
    assert release_config.problems(copy) == [
        f"plugins/runner-scripted (troupe-runner-scripted) has no version in {MANIFEST}: add "
        '"plugins/runner-scripted": "0.0.0".'
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


def test_a_plugin_in_the_linked_group_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: group(c).append("troupe-runner-scripted"))
    assert release_config.problems(copy) == [
        f"troupe-runner-scripted is in the 'troupe' linked group in {CONFIG}, but only packages/* "
        "members and protocol belong there: remove it."
    ]


def test_the_protocol_left_out_of_the_linked_group_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: group(c).remove("protocol"))
    assert release_config.problems(copy) == [
        f"protocol isn't in the 'troupe' linked group in {CONFIG}: add it to its 'components'."
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


def test_a_protocol_entry_with_a_lock_update_is_named(copy: Path) -> None:
    edit_json(copy, CONFIG, lambda c: c["packages"]["protocol"].update({"extra-files": []}))
    assert release_config.problems(copy) == [
        f"protocol's entry in {CONFIG} has 'extra-files', but it isn't a Python package and has "
        f"nothing in {LOCK}: remove them."
    ]


def test_the_protocol_missing_from_the_manifest_is_named(copy: Path) -> None:
    edit_json(copy, MANIFEST, lambda m: m.pop("protocol"))
    assert release_config.problems(copy) == [
        f'protocol has no version in {MANIFEST}: add "protocol": "0.0.0".'
    ]


def test_every_workspace_member_is_configured_for_release() -> None:
    assert release_config.problems(REPO) == []

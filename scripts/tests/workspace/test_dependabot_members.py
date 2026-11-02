"""Dependabot proposes no version for a workspace member (spec: releases; dependabot-uv-resolve
design D3 to D5).

Each property is broken in a copy of the real files, one at a time, to show the check catches it and
names the member or the file. The copies' `.github/dependabot.yml` carries the ignores
troupe-run/infrastructure delivers (`troupe` and `troupe-*`), so no test depends on whether the real
file has them yet. The last test runs the check on the real files."""

import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO

import dependabot_members
import release_config
from dependabot_members import CONFIG

DELIVERED = ["troupe", "troupe-*"]


def members() -> dict[str, str]:
    """Each workspace member's project name mapped to its path."""
    return {name: path for path, name in release_config.members(REPO).items()}


def read(root: Path) -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load((root / CONFIG).read_text(encoding="utf-8"))
    return config


def write(root: Path, config: dict[str, Any]) -> None:
    (root / CONFIG).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def uv_entry(config: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = next(
        update for update in config["updates"] if update["package-ecosystem"] == "uv"
    )
    return entry


def set_ignores(root: Path, ignores: Sequence[object]) -> None:
    config = read(root)
    uv_entry(config)["ignore"] = list(ignores)
    write(root, config)


def names(*patterns: str) -> list[dict[str, Any]]:
    return [{"dependency-name": pattern} for pattern in patterns]


def uncovered(name: str) -> str:
    return dependabot_members.uncovered(name, members()[name])


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """The root pyproject.toml, every member's, and .github/dependabot.yml with the delivered
    ignores in its uv entry."""
    shutil.copy(REPO / "pyproject.toml", tmp_path / "pyproject.toml")
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / "pyproject.toml", tmp_path / path / "pyproject.toml")
    (tmp_path / CONFIG).parent.mkdir(parents=True)
    shutil.copy(REPO / CONFIG, tmp_path / CONFIG)
    set_ignores(tmp_path, names(*DELIVERED))
    return tmp_path


def test_the_copy_has_no_problems(copy: Path) -> None:
    assert dependabot_members.problems(copy) == []


def test_every_member_the_ignores_miss_is_named_with_the_file_and_infrastructures_policy(
    copy: Path,
) -> None:
    set_ignores(copy, names("troupe"))
    problems = dependabot_members.problems(copy)
    assert problems == [uncovered(name) for name in sorted(members()) if name != "troupe"]
    assert all(CONFIG in problem and "troupe-run/infrastructure" in problem for problem in problems)


def test_a_member_named_outside_the_ignores_is_named(copy: Path) -> None:
    path = members()["troupe-runner-scripted"]
    manifest = copy / path / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        text.replace('name = "troupe-runner-scripted"', 'name = "scripted-runner"', 1),
        encoding="utf-8",
    )
    assert dependabot_members.problems(copy) == [
        dependabot_members.uncovered("scripted-runner", path)
    ]


@pytest.mark.parametrize(
    "limit", [{"versions": [">=0.5"]}, {"update-types": ["version-update:semver-major"]}]
)
def test_an_ignore_limited_to_some_updates_covers_nothing(
    copy: Path, limit: dict[str, Any]
) -> None:
    set_ignores(copy, [{"dependency-name": "troupe", **limit}, *names("troupe-*")])
    assert dependabot_members.problems(copy) == [uncovered("troupe")]


def test_names_differing_only_in_case_and_separators_match(copy: Path) -> None:
    set_ignores(copy, names("TROUPE", "Troupe_Vcs.Git"))
    assert dependabot_members.problems(copy) == [
        uncovered(name) for name in sorted(members()) if name not in {"troupe", "troupe-vcs-git"}
    ]


def test_a_star_matches_any_run_of_characters_including_none(copy: Path) -> None:
    set_ignores(copy, names("troupe*"))
    assert dependabot_members.problems(copy) == []


@pytest.mark.parametrize("pattern", ["troupe-vcs-gi?", "troupe-vcs-gi[t]"])
def test_only_a_star_is_a_wildcard(copy: Path, pattern: str) -> None:
    others = [name for name in members() if name != "troupe-vcs-git"]
    set_ignores(copy, names(*others, pattern))
    assert dependabot_members.problems(copy) == [uncovered("troupe-vcs-git")]


def test_a_missing_file_is_named(copy: Path) -> None:
    (copy / CONFIG).unlink()
    assert dependabot_members.problems(copy) == [f"{CONFIG}: missing, {dependabot_members.FIX}"]


def test_a_file_that_isnt_yaml_is_named(copy: Path) -> None:
    (copy / CONFIG).write_text("updates: [\n", encoding="utf-8")
    [problem] = dependabot_members.problems(copy)
    assert problem.startswith(f"{CONFIG}: not valid YAML")


def test_a_file_with_no_uv_entry_is_named(copy: Path) -> None:
    config = read(copy)
    config["updates"] = [u for u in config["updates"] if u["package-ecosystem"] != "uv"]
    write(copy, config)
    assert dependabot_members.problems(copy) == [dependabot_members.NO_UV_ENTRY]


def test_a_uv_entry_for_another_directory_doesnt_count(copy: Path) -> None:
    config = read(copy)
    uv_entry(config)["directory"] = "/packages/troupe"
    write(copy, config)
    assert dependabot_members.problems(copy) == [dependabot_members.NO_UV_ENTRY]


@pytest.mark.parametrize("ignore", ["troupe", {"versions": [">=1"]}, {"dependency-name": 3}])
def test_a_malformed_ignore_is_named_rather_than_skipped(copy: Path, ignore: object) -> None:
    set_ignores(copy, [ignore, *names(*DELIVERED)])
    [problem] = dependabot_members.problems(copy)
    assert problem.startswith(f"{CONFIG}: the uv entry's ignore {ignore!r}")


@pytest.mark.xfail(
    reason="the ignores aren't delivered until troupe-run/infrastructure#259; remove this marker "
    "when they are (dependabot-uv-resolve task 3.2)",
    strict=True,
)
def test_dependabot_ignores_every_workspace_member() -> None:
    assert dependabot_members.problems(REPO) == []

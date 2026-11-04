"""The import contracts cover every plugin, and the plugin SDK stays dependency-free (spec:
plugin-sdk; runner-sdk design D13).

Each property is broken in a copy of the real files, one at a time, to show the check catches it
and names what to fix. The last test runs the check on the real files."""

import shutil
from pathlib import Path

import pytest
from conftest import REPO

import plugin_imports
import release_config
from plugin_imports import PYPROJECT, SDK_PATH


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """The root pyproject.toml and each member's, with each member's import packages, copied."""
    shutil.copy(REPO / PYPROJECT, tmp_path / PYPROJECT)
    for path in release_config.members(REPO):
        (tmp_path / path).mkdir(parents=True)
        shutil.copy(REPO / path / PYPROJECT, tmp_path / path / PYPROJECT)
        for package in plugin_imports.import_packages(REPO, path):
            (tmp_path / path / "src" / package).mkdir(parents=True)
            (tmp_path / path / "src" / package / "__init__.py").write_bytes(b"")
    return tmp_path


def replace(root: Path, name: str, old: str, new: str) -> None:
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} isn't in {name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def add_plugin(root: Path, directory: str, project: str, package: str) -> None:
    (root / "plugins" / directory / "src" / package).mkdir(parents=True)
    (root / "plugins" / directory / "src" / package / "__init__.py").write_bytes(b"")
    (root / "plugins" / directory / PYPROJECT).write_text(
        f'[project]\nname = "{project}"\nversion = "0.0.0"\ndependencies = []\n', encoding="utf-8"
    )


def test_the_unchanged_copy_has_no_problems(copy: Path) -> None:
    assert plugin_imports.problems(copy) == []


def test_a_new_plugin_left_out_of_every_contract_is_named_with_each_contract(copy: Path) -> None:
    add_plugin(copy, "runner-local-model", "troupe-runner-local-model", "troupe_runner_local_model")

    found = plugin_imports.problems(copy)

    assert len(found) == 3
    assert all("troupe_runner_local_model (plugins/runner-local-model)" in p for p in found)
    assert any("root_packages" in p for p in found)
    assert any('"plugins import nothing from troupe"' in p for p in found)
    assert any('"plugins are independent of each other"' in p for p in found)


def test_a_plugin_removed_from_the_forbidden_contracts_sources_is_named(copy: Path) -> None:
    replace(
        copy,
        PYPROJECT,
        'source_modules = ["troupe_runner_claude_code", "troupe_runner_ollama", '
        '"troupe_runner_openai_chat", "troupe_runner_scripted"]',
        'source_modules = ["troupe_runner_claude_code", "troupe_runner_ollama", '
        '"troupe_runner_openai_chat"]',
    )

    found = plugin_imports.problems(copy)

    assert len(found) == 1
    assert "troupe_runner_scripted (plugins/runner-scripted)" in found[0]
    assert '"plugins import nothing from troupe"' in found[0]
    assert PYPROJECT in found[0]


def test_a_workspace_package_the_plugins_contract_doesnt_forbid_is_named(copy: Path) -> None:
    replace(copy, PYPROJECT, '"troupe", "troupe_run", ', '"troupe", ')

    found = plugin_imports.problems(copy)

    assert found == [
        f'"plugins import nothing from troupe" in {PYPROJECT} doesn\'t forbid troupe_run: add it '
        "to the contract's forbidden_modules, since a plugin imports only the plugin SDK."
    ]


def test_the_plugins_contract_forbidding_the_sdk_is_named(copy: Path) -> None:
    forbidding = '"troupe", "troupe_run", "troupe_plugin_sdk", '
    replace(copy, PYPROJECT, '"troupe", "troupe_run", ', forbidding)

    found = plugin_imports.problems(copy)

    assert len(found) == 1
    assert "forbids troupe_plugin_sdk" in found[0]


def test_a_missing_contract_is_named(copy: Path) -> None:
    replace(
        copy,
        PYPROJECT,
        'name = "plugins are independent of each other"',
        'name = "something else"',
    )

    found = plugin_imports.problems(copy)

    assert len(found) == 1
    assert 'no import contract named "plugins are independent of each other"' in found[0]


def test_a_dependency_the_sdk_declares_is_named_with_its_file(copy: Path) -> None:
    replace(copy, f"{SDK_PATH}/{PYPROJECT}", "dependencies = []", 'dependencies = ["pydantic>=2"]')

    found = plugin_imports.problems(copy)

    assert found == [
        f"{SDK_PATH}/{PYPROJECT} depends on 'pydantic>=2': remove it. The plugin SDK uses the "
        "standard library only, so a plugin inherits nothing else."
    ]


def test_the_real_import_contracts_cover_every_plugin_and_the_sdk_has_no_dependencies() -> None:
    assert plugin_imports.problems(REPO) == []
